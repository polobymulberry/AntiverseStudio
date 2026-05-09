#!/usr/bin/env python3
"""跨终端 Blender 渲染并发池：同仓库内最多 N 路（默认 7）并行，其余 FIFO 排队并打印粗估等待/完成时间。

用法（在仓库根目录）::

    python scripts/blender_render_pool.py -- blender -b ... -P ... -- --pass covers ...

环境变量:

- ``BLENDER_POOL_MAX``: 最大并发数，默认 7。
- ``BLENDER_POOL_NAME``: 池子名，用于隔离不同 sqlite（默认 ``default``）。
- ``FIGSHION3D_REPO_ROOT``: 仓库根；未设置时从本脚本位置推断。
- ``BLENDER_POOL_EST_SECONDS_COVERS`` / ``BLENDER_POOL_EST_SECONDS_VIDEOS`` /
  ``BLENDER_POOL_EST_SECONDS_WHITE_MESH`` / ``BLENDER_POOL_EST_SECONDS_DEFAULT``:
  无历史统计时用于 ETA 的默认秒数。
- ``BLENDER_POOL_TICK_SEC``: ``BLENDER_POOL_LOG=full`` 时等待/运行中 ETA 打印间隔，默认 5 秒。
- ``BLENDER_POOL_LOG``: 池子自身日志量。``full``=按 ``BLENDER_POOL_TICK_SEC`` 频繁打 ETA；``minimal``（默认）=任务开始/结束必打完整指令与 run_id，中间状态按 ``BLENDER_POOL_LOG_INTERVAL``；``quiet``=仅开始/结束，排队与运行中不打 ETA。
- ``BLENDER_POOL_LOG_INTERVAL``: 与 ``minimal`` 合用，中间状态间隔秒数，默认 120；设为 ``0`` 则排队/运行中完全不刷 ETA（仍保留起止横幅）。

**槽位权重**：每个经本脚本启动的 Blender 任务（外层一次 ``Popen``）在池中占 **1** 槽，与命令行 ``--workers`` 无关。
Stage11 多 worker 时，**实际并行渲片数**由 ``common/blender_render_pool_lease`` 在子进程内用 sqlite 租约限制在
``BLENDER_POOL_MAX`` 以内；故两个 ``--workers 6`` 任务可同时被外层接纳，第二路会按剩余租约只先拉起若干子进程
（例如只剩 1 格时先跑 1 个子 Blender 处理其分片），而不会在外层因 6+6>7 整单阻塞。

**入队规则**：只要 ``已用外层任务数 + 1 <= BLENDER_POOL_MAX`` 即立即执行，不要求等待队列为空。

**Ctrl+C / kill**：子进程 ``start_new_session=True`` 独立进程组；并注册 ``SIGINT``/``SIGTERM``
在信号里对 Blender **进程组**发 ``SIGTERM``，数秒后 ``SIGKILL``（信号处理中不调 flock/SQLite，避免死锁）。
"""

from __future__ import annotations

import fcntl
import json
import os
import shlex
import signal
import sqlite3
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

DEFAULT_POOL_MAX = 7
DEFAULT_TICK = 5.0
DEFAULT_EST_COVERS = 25 * 60
DEFAULT_EST_VIDEOS = 90 * 60
DEFAULT_EST_OTHER = 30 * 60
_SLEEP_SLICE = 0.25


def _interruptible_sleep(seconds: float, stop: Callable[[], bool] | None = None) -> None:
    """可尽快响应停止标志或 Ctrl+C 的睡眠（拆成短段）。"""
    if seconds <= 0:
        return
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if stop is not None and stop():
            return
        time.sleep(min(_SLEEP_SLICE, end - time.monotonic()))


@dataclass
class _RuntimeCtx:
    """供信号处理与主循环共享；信号里只杀子进程、置位，不做 SQLite。"""

    stop: bool = False
    proc: subprocess.Popen[bytes] | None = None


def _blender_tree_stop(proc: subprocess.Popen[bytes]) -> None:
    """终止 Blender 及其子进程（会话首进程即进程组组长时 killpg 有效）。"""
    if proc.poll() is not None:
        return
    pid = proc.pid
    try:
        if hasattr(os, "killpg"):
            os.killpg(pid, signal.SIGTERM)
        else:
            proc.terminate()
    except ProcessLookupError:
        return
    except PermissionError:
        proc.terminate()
    deadline = time.monotonic() + 10.0
    while proc.poll() is None and time.monotonic() < deadline:
        time.sleep(0.05)
    if proc.poll() is not None:
        return
    try:
        if hasattr(os, "killpg"):
            os.killpg(pid, signal.SIGKILL)
        else:
            proc.kill()
    except ProcessLookupError:
        pass
    except PermissionError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass


def _install_signal_handlers(ctx: _RuntimeCtx) -> tuple[Callable[..., Any], Callable[..., Any]]:
    def _handler(signum: int, frame: object | None) -> None:
        ctx.stop = True
        p = ctx.proc
        if p is not None and p.poll() is None:
            _blender_tree_stop(p)

    prev_int = signal.signal(signal.SIGINT, _handler)
    prev_term = signal.signal(signal.SIGTERM, _handler)
    return prev_int, prev_term


def _cleanup_holder_lease(
    state: _PoolState,
    holder_pid: int,
    my_wait_id: int | None,
) -> None:
    """释放本客户端在 waiting/running 中的记录（持 scheduler 锁）。"""
    with _scheduler_lock(state.lock_path):
        conn = _connect(state.db_path)
        if my_wait_id is not None:
            conn.execute("DELETE FROM waiting WHERE id = ?", (my_wait_id,))
        conn.execute("DELETE FROM waiting WHERE holder_pid = ?", (holder_pid,))
        _delete_running_for_holder(conn, holder_pid)


def _repo_root() -> Path:
    env = (os.environ.get("FIGSHION3D_REPO_ROOT") or "").strip()
    if env:
        return Path(env).resolve()
    return Path(__file__).resolve().parents[1]


def _pool_dir(repo: Path) -> Path:
    name = (os.environ.get("BLENDER_POOL_NAME") or "default").strip() or "default"
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)[:64]
    return repo / "var" / "blender_render_pool" / safe


def _db_path(repo: Path) -> Path:
    return _pool_dir(repo) / "state.sqlite"


def _lock_path(repo: Path) -> Path:
    return _pool_dir(repo) / "scheduler.lock"


def _pool_max() -> int:
    raw = (os.environ.get("BLENDER_POOL_MAX") or str(DEFAULT_POOL_MAX)).strip()
    try:
        n = int(raw, 10)
    except ValueError:
        return DEFAULT_POOL_MAX
    return max(1, min(64, n))


def _tick_sec() -> float:
    try:
        return max(1.0, float(os.environ.get("BLENDER_POOL_TICK_SEC") or DEFAULT_TICK))
    except ValueError:
        return DEFAULT_TICK


def _pool_run_id(holder_pid: int) -> str:
    return f"{time.strftime('%Y%m%d-%H%M%S')}-{holder_pid}"


def _pool_invocation_text() -> str:
    """当前池子进程的完整命令行（可粘贴复跑），已 shell 转义。"""
    script = str(Path(sys.argv[0]).resolve())
    parts = [sys.executable, script, *sys.argv[1:]]
    return " ".join(shlex.quote(p) for p in parts)


def _log_profile() -> tuple[str, float]:
    """返回 (档位, 中间状态间隔秒)。档位: full | minimal | quiet。"""
    raw = (os.environ.get("BLENDER_POOL_LOG") or "minimal").strip().lower()
    if raw in ("full", "verbose", "1", "true", "yes"):
        return "full", _tick_sec()
    if raw in ("quiet", "off", "none", "0", "false", "no"):
        return "quiet", 0.0
    try:
        interval = float(os.environ.get("BLENDER_POOL_LOG_INTERVAL", "120"))
    except ValueError:
        interval = 120.0
    return "minimal", max(0.0, interval)


def _print_task_banner(
    *,
    run_id: str,
    pass_name: str,
    holder_pid: int,
    invocation: str,
    pool_max: int,
    slot_cost: int,
    log_mode: str,
) -> None:
    sep = "=" * 16
    print(f"\n[池子] {sep} 任务开始 run_id={run_id} pass={pass_name} holder_pid={holder_pid} {sep}", flush=True)
    print(f"[池子] 完整指令（复跑）:\n{invocation}", flush=True)
    print(
        f"[池子] BLENDER_POOL_MAX={pool_max}，外层槽权重={slot_cost}；"
        f"日志档位 BLENDER_POOL_LOG={log_mode!r}（设 full 可恢复频繁 ETA）",
        flush=True,
    )


def _print_task_footer(
    *,
    run_id: str,
    pass_name: str,
    exit_code: int | None,
    duration_sec: float,
    invocation: str,
    note: str | None = None,
) -> None:
    sep = "=" * 16
    dur = _format_eta(duration_sec) if duration_sec >= 0 else "未知"
    code = "?" if exit_code is None else str(exit_code)
    tail = f" {note}" if note else ""
    print(
        f"\n[池子] {sep} 任务结束 run_id={run_id} pass={pass_name} 退出码={code} 历时≈{dur}{tail} {sep}",
        flush=True,
    )
    print(f"[池子] 完整指令（对照）:\n{invocation}", flush=True)


def _parse_pass_from_argv(argv: list[str]) -> str:
    for i, a in enumerate(argv):
        if a == "--pass" and i + 1 < len(argv):
            return (argv[i + 1] or "").strip() or "unknown"
    return "unknown"


def _slot_cost(argv: list[str], pool_max: int) -> int:
    """每个池任务占 1 外层槽；``--workers`` 仅影响 Stage11 子进程数，由 ``blender_render_pool_lease`` 再限全局渲片并发。

    ``pool_max`` 与 ``argv`` 仍参与签名，便于将来扩展；当前恒返回 1。
    """
    _ = argv
    _ = pool_max
    return 1


def _running_weight_sum(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COALESCE(SUM(slot_weight), 0) AS s FROM running").fetchone()
    return int(row["s"]) if row else 0


def _default_est_seconds(pass_name: str) -> float:
    key = pass_name.lower().replace("-", "_")
    if key == "covers":
        return float(os.environ.get("BLENDER_POOL_EST_SECONDS_COVERS") or DEFAULT_EST_COVERS)
    if key == "videos":
        return float(os.environ.get("BLENDER_POOL_EST_SECONDS_VIDEOS") or DEFAULT_EST_VIDEOS)
    if key == "white_mesh":
        return float(os.environ.get("BLENDER_POOL_EST_SECONDS_WHITE_MESH") or DEFAULT_EST_OTHER)
    try:
        return float(os.environ.get("BLENDER_POOL_EST_SECONDS_DEFAULT") or DEFAULT_EST_OTHER)
    except ValueError:
        return DEFAULT_EST_OTHER


def _argv_summary(argv: list[str], max_len: int = 120) -> str:
    s = " ".join(argv)
    return s if len(s) <= max_len else s[: max_len - 3] + "..."


def _split_pool_argv(argv: list[str]) -> tuple[list[str], list[str]]:
    if "--" not in argv:
        print(
            "[blender_render_pool] 用法: python scripts/blender_render_pool.py -- <blender 及后续参数>\n"
            "示例: python scripts/blender_render_pool.py -- blender -b ... -P ... -- --pass covers ...",
            file=sys.stderr,
        )
        sys.exit(2)
    idx = argv.index("--")
    return argv[:idx], argv[idx + 1 :]


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        PRAGMA journal_mode = WAL;
        CREATE TABLE IF NOT EXISTS running (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            holder_pid INTEGER NOT NULL,
            blender_pid INTEGER,
            pass_name TEXT NOT NULL,
            argv_summary TEXT NOT NULL,
            started_at REAL NOT NULL,
            slot_weight INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS waiting (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            enqueued_at REAL NOT NULL,
            holder_pid INTEGER NOT NULL,
            pass_name TEXT NOT NULL,
            argv_json TEXT NOT NULL,
            slot_weight INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS duration_stats (
            pass_name TEXT PRIMARY KEY,
            avg_seconds REAL NOT NULL,
            sample_count INTEGER NOT NULL,
            last_updated REAL NOT NULL
        );
        """
    )
    conn.commit()


def _migrate_slot_weight_columns(conn: sqlite3.Connection) -> None:
    """旧库无 slot_weight 列时补齐。"""
    for table in ("running", "waiting"):
        cols = {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}
        if "slot_weight" not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN slot_weight INTEGER NOT NULL DEFAULT 1")
    conn.commit()


def _reap_stale(conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT id, holder_pid, blender_pid FROM running").fetchall()
    for row in rows:
        rid = int(row["id"])
        holder_pid = int(row["holder_pid"] or 0)
        blender_pid = int(row["blender_pid"] or 0)
        alive = _pid_alive(blender_pid) if blender_pid else _pid_alive(holder_pid)
        if not alive:
            conn.execute("DELETE FROM running WHERE id = ?", (rid,))
    for row in conn.execute("SELECT id, holder_pid FROM waiting").fetchall():
        wid = int(row["id"])
        hp = int(row["holder_pid"] or 0)
        if not _pid_alive(hp):
            conn.execute("DELETE FROM waiting WHERE id = ?", (wid,))


def _get_avg_seconds(conn: sqlite3.Connection, pass_name: str) -> float:
    row = conn.execute(
        "SELECT avg_seconds FROM duration_stats WHERE pass_name = ?",
        (pass_name,),
    ).fetchone()
    if row is not None and row["avg_seconds"] is not None and float(row["avg_seconds"]) > 0:
        return float(row["avg_seconds"])
    return _default_est_seconds(pass_name)


def _update_duration_stats(conn: sqlite3.Connection, pass_name: str, duration_sec: float) -> None:
    row = conn.execute(
        "SELECT avg_seconds, sample_count FROM duration_stats WHERE pass_name = ?",
        (pass_name,),
    ).fetchone()
    now = time.time()
    if row is None:
        conn.execute(
            "INSERT INTO duration_stats (pass_name, avg_seconds, sample_count, last_updated) VALUES (?,?,?,?)",
            (pass_name, duration_sec, 1, now),
        )
    else:
        old_avg = float(row["avg_seconds"])
        n = int(row["sample_count"])
        new_n = n + 1
        new_avg = (old_avg * n + duration_sec) / new_n
        conn.execute(
            "UPDATE duration_stats SET avg_seconds = ?, sample_count = ?, last_updated = ? WHERE pass_name = ?",
            (new_avg, new_n, now, pass_name),
        )


@contextmanager
def _scheduler_lock(lock_path: Path) -> Iterator[None]:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+", encoding="utf-8") as lf:
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lf.fileno(), fcntl.LOCK_UN)


@dataclass
class _PoolState:
    repo: Path
    db_path: Path
    lock_path: Path
    pool_max: int


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=60.0)
    conn.row_factory = sqlite3.Row
    _init_db(conn)
    _migrate_slot_weight_columns(conn)
    return conn


def _enqueue_or_run(
    state: _PoolState,
    conn: sqlite3.Connection,
    pass_name: str,
    argv_summary: str,
    argv_json: str,
    holder_pid: int,
    slot_cost: int,
) -> tuple[str, int | None]:
    """在已持有 scheduler 锁且同一 conn 内调用。"""
    _reap_stale(conn)
    run_w = _running_weight_sum(conn)

    if run_w + slot_cost <= state.pool_max:
        conn.execute(
            "INSERT INTO running (holder_pid, blender_pid, pass_name, argv_summary, started_at, slot_weight) "
            "VALUES (?,?,?,?,?,?)",
            (holder_pid, None, pass_name, argv_summary, time.time(), slot_cost),
        )
        conn.commit()
        rid = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
        return "running", rid

    conn.execute(
        "INSERT INTO waiting (enqueued_at, holder_pid, pass_name, argv_json, slot_weight) VALUES (?,?,?,?,?)",
        (time.time(), holder_pid, pass_name, argv_json, slot_cost),
    )
    conn.commit()
    wid = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    return "waiting", wid


def _try_promote(
    state: _PoolState,
    conn: sqlite3.Connection,
    my_wait_id: int,
    holder_pid: int,
    pass_name: str,
    argv_summary: str,
) -> bool:
    """已持锁。若轮到本等待行且空权重足够，移入 running 并返回 True。"""
    _reap_stale(conn)
    run_w = _running_weight_sum(conn)
    head = conn.execute(
        "SELECT id, slot_weight FROM waiting ORDER BY id ASC LIMIT 1"
    ).fetchone()
    if head is None or int(head["id"]) != my_wait_id:
        return False
    head_cost = int(head["slot_weight"] or 1)
    if run_w + head_cost > state.pool_max:
        return False
    conn.execute("DELETE FROM waiting WHERE id = ?", (my_wait_id,))
    conn.execute(
        "INSERT INTO running (holder_pid, blender_pid, pass_name, argv_summary, started_at, slot_weight) "
        "VALUES (?,?,?,?,?,?)",
        (holder_pid, None, pass_name, argv_summary, time.time(), head_cost),
    )
    conn.commit()
    return True


def _delete_running_for_holder(conn: sqlite3.Connection, holder_pid: int) -> None:
    conn.execute("DELETE FROM running WHERE holder_pid = ?", (holder_pid,))
    conn.commit()


def _format_eta(seconds: float) -> str:
    if seconds <= 0 or seconds > 86400 * 7:
        return "未知"
    return str(timedelta(seconds=int(seconds)))


def _wait_message(
    state: _PoolState,
    conn: sqlite3.Connection,
    my_wait_id: int,
    pass_name: str,
) -> str:
    run_w = _running_weight_sum(conn)
    n_tasks = int(conn.execute("SELECT COUNT(*) AS c FROM running").fetchone()["c"])
    ahead = int(conn.execute("SELECT COUNT(*) AS c FROM waiting WHERE id < ?", (my_wait_id,)).fetchone()["c"])
    avg_sec = _get_avg_seconds(conn, pass_name)
    mx = state.pool_max
    # 排队中：粗估与前方人数、池上限有关（不依赖「权重已满」才非零）
    est_wait = max(avg_sec * 0.3, float(ahead + 1) * avg_sec / max(1, mx))
    avg_min = avg_sec / 60.0
    est_min = est_wait / 60.0
    return (
        f"[池子] 已用槽权重 {run_w}/{mx}（外层任务 {n_tasks} 个）| 你在等待队列中，前方 {ahead} 个任务 | "
        f"「{pass_name}」历史/默认均次约 {avg_min:.1f} 分（粗估再等约 {est_min:.1f} 分，仅供参考）"
    )


def _running_message(
    conn: sqlite3.Connection, pass_name: str, started_at: float, pool_max: int
) -> str:
    elapsed = max(0.0, time.time() - started_at)
    avg_sec = _get_avg_seconds(conn, pass_name)
    remain = max(0.0, avg_sec - elapsed)
    eta_clock = datetime.now(timezone.utc) + timedelta(seconds=remain)
    eta_local = eta_clock.astimezone().strftime("%H:%M")
    run_w = _running_weight_sum(conn)
    return (
        f"[池子] 本任务已运行 {_format_eta(elapsed)} | 全局槽权重 {run_w}/{pool_max} | "
        f"预计总时长约 {_format_eta(avg_sec)} | 粗估完成约 {eta_local}（本地时，仅供参考）"
    )


def main() -> None:
    _, blender_argv = _split_pool_argv(sys.argv[1:])
    if not blender_argv:
        print("[blender_render_pool] `--` 后不能为空。", file=sys.stderr)
        sys.exit(2)

    repo = _repo_root()
    state = _PoolState(
        repo=repo,
        db_path=_db_path(repo),
        lock_path=_lock_path(repo),
        pool_max=_pool_max(),
    )
    pass_name = _parse_pass_from_argv(blender_argv)
    argv_summary = _argv_summary(blender_argv)
    argv_json = json.dumps(blender_argv, ensure_ascii=False)
    holder_pid = os.getpid()
    tick = _tick_sec()
    slot_cost = _slot_cost(blender_argv, state.pool_max)
    log_mode, log_interval = _log_profile()
    run_id = _pool_run_id(holder_pid)
    invocation = _pool_invocation_text()

    _print_task_banner(
        run_id=run_id,
        pass_name=pass_name,
        holder_pid=holder_pid,
        invocation=invocation,
        pool_max=state.pool_max,
        slot_cost=slot_cost,
        log_mode=log_mode,
    )

    my_wait_id: int | None = None
    ctx = _RuntimeCtx()
    prev_sigint: Callable[..., Any] | int = signal.SIG_DFL
    prev_sigterm: Callable[..., Any] | int = signal.SIG_DFL
    signals_installed = False

    try:
        prev_sigint, prev_sigterm = _install_signal_handlers(ctx)
        signals_installed = True

        with _scheduler_lock(state.lock_path):
            conn = _connect(state.db_path)
            mode, token = _enqueue_or_run(
                state,
                conn,
                pass_name,
                argv_summary,
                argv_json,
                holder_pid,
                slot_cost,
            )
        if mode == "waiting":
            my_wait_id = token

        def _stopped() -> bool:
            return ctx.stop

        last_pool_log = 0.0
        wait_first_status = True
        while my_wait_id is not None and not ctx.stop:
            with _scheduler_lock(state.lock_path):
                conn = _connect(state.db_path)
                promoted = _try_promote(
                    state, conn, my_wait_id, holder_pid, pass_name, argv_summary
                )
            if promoted:
                my_wait_id = None
                break
            now = time.time()
            should_log = False
            if log_mode == "full" and now - last_pool_log >= tick:
                should_log = True
            elif log_mode == "minimal":
                if wait_first_status:
                    should_log = True
                    wait_first_status = False
                elif log_interval > 0 and now - last_pool_log >= log_interval:
                    should_log = True
            if should_log:
                with _scheduler_lock(state.lock_path):
                    conn = _connect(state.db_path)
                    print(_wait_message(state, conn, my_wait_id, pass_name), flush=True)
                last_pool_log = now
            _interruptible_sleep(tick, _stopped)

        if ctx.stop:
            _cleanup_holder_lease(state, holder_pid, my_wait_id)
            print("\n[池子] 已中断并释放队列/槽位。", flush=True)
            _print_task_footer(
                run_id=run_id,
                pass_name=pass_name,
                exit_code=None,
                duration_sec=-1.0,
                invocation=invocation,
                note="用户中断",
            )
            sys.exit(130)

        started_at = time.time()
        with _scheduler_lock(state.lock_path):
            conn = _connect(state.db_path)
            row = conn.execute(
                "SELECT started_at FROM running WHERE holder_pid = ? ORDER BY id DESC LIMIT 1",
                (holder_pid,),
            ).fetchone()
            if row is not None:
                started_at = float(row["started_at"])

        proc = subprocess.Popen(blender_argv, start_new_session=True)
        ctx.proc = proc
        print(
            f"[池子] run_id={run_id} Blender 子进程已启动 blender_pid={proc.pid}",
            flush=True,
        )
        with _scheduler_lock(state.lock_path):
            conn = _connect(state.db_path)
            conn.execute(
                "UPDATE running SET blender_pid = ? WHERE holder_pid = ?",
                (proc.pid, holder_pid),
            )
            conn.commit()

        last_pool_log = 0.0
        run_first_status = True
        while proc.poll() is None and not ctx.stop:
            now = time.time()
            should_log = False
            if log_mode == "full" and now - last_pool_log >= tick:
                should_log = True
            elif log_mode == "minimal":
                if run_first_status:
                    should_log = True
                    run_first_status = False
                elif log_interval > 0 and now - last_pool_log >= log_interval:
                    should_log = True
            if should_log:
                with _scheduler_lock(state.lock_path):
                    conn = _connect(state.db_path)
                    print(_running_message(conn, pass_name, started_at, state.pool_max), flush=True)
                last_pool_log = now
            _interruptible_sleep(min(1.0, tick), _stopped)

        if ctx.stop and proc.poll() is None:
            _blender_tree_stop(proc)

        try:
            proc.wait(timeout=120)
        except subprocess.TimeoutExpired:
            _blender_tree_stop(proc)
            proc.wait(timeout=60)

        if ctx.stop:
            _cleanup_holder_lease(state, holder_pid, None)
            print("\n[池子] 已中断并释放队列/槽位。", flush=True)
            _print_task_footer(
                run_id=run_id,
                pass_name=pass_name,
                exit_code=None,
                duration_sec=max(0.0, time.time() - started_at),
                invocation=invocation,
                note="渲染中中断",
            )
            sys.exit(130)

        duration = max(0.0, time.time() - started_at)
        with _scheduler_lock(state.lock_path):
            conn = _connect(state.db_path)
            _delete_running_for_holder(conn, holder_pid)
            _update_duration_stats(conn, pass_name, duration)
        rc = int(proc.returncode or 0)
        _print_task_footer(
            run_id=run_id,
            pass_name=pass_name,
            exit_code=rc,
            duration_sec=duration,
            invocation=invocation,
            note="成功" if rc == 0 else "Blender 非零退出",
        )
        sys.exit(rc)
    finally:
        if signals_installed:
            signal.signal(signal.SIGINT, prev_sigint)
            signal.signal(signal.SIGTERM, prev_sigterm)


if __name__ == "__main__":
    main()
