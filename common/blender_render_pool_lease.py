"""Blender 渲染进程在 ``BLENDER_POOL_MAX`` 下的全局租约（与 ``scripts/blender_render_pool.py`` 共用 sqlite 目录）。

Stage11 ``--workers N>1`` 时：外层池子每任务仅占权重 **1**；实际并行渲片数由本模块在子进程内
``acquire_render_slot`` / ``release_render_slot`` 限制。``spawn_parallel_blenders`` 在拉起子进程前调用
``compute_spawn_worker_count``，按当前租约占用数得到 ``min(N, max(1, 剩余))``；若无剩余则阻塞至至少空出一格。

非 Stage11 的 Blender 任务可不使用本模块，仅受外层池并发数限制。
"""

from __future__ import annotations

import fcntl
import os
import sqlite3
import time
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

_SLEEP = 0.25


def _repo_root() -> Path:
    env = (os.environ.get("ANTIVERSESTUDIO_REPO_ROOT") or "").strip()
    if env:
        return Path(env).resolve()
    return Path(__file__).resolve().parents[1]


def _pool_dir(repo: Path) -> Path:
    name = (os.environ.get("BLENDER_POOL_NAME") or "default").strip() or "default"
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)[:64]
    return repo / "var" / "blender_render_pool" / safe


def _db_path(repo: Path) -> Path:
    return _pool_dir(repo) / "state.sqlite"


def _lease_lock_path(repo: Path) -> Path:
    return _pool_dir(repo) / "render_slot.lock"


def _pool_max() -> int:
    raw = (os.environ.get("BLENDER_POOL_MAX") or "7").strip()
    try:
        n = int(raw, 10)
    except ValueError:
        return 7
    return max(1, min(64, n))


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


@contextmanager
def _lease_file_lock(lock_path: Path) -> Iterator[None]:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+", encoding="utf-8") as lf:
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lf.fileno(), fcntl.LOCK_UN)


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=60.0)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_lease_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS render_leases (
            blender_pid INTEGER PRIMARY KEY,
            created_at REAL NOT NULL
        );
        """
    )
    conn.commit()


def _reap_stale_leases(conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT blender_pid FROM render_leases").fetchall()
    for row in rows:
        pid = int(row["blender_pid"])
        if pid > 0 and not _pid_alive(pid):
            conn.execute("DELETE FROM render_leases WHERE blender_pid = ?", (pid,))
    conn.commit()


def _lease_count(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) AS c FROM render_leases").fetchone()
    return int(row["c"]) if row else 0


def compute_spawn_worker_count(
    wanted: int,
    *,
    stop: Callable[[], bool] | None = None,
) -> int:
    """在全局租约限制下，本批应拉起的子 Blender 数量（至少为 1，至多 ``wanted``）。"""
    wanted = max(1, int(wanted))
    repo = _repo_root()
    lock_path = _lease_lock_path(repo)
    db_path = _db_path(repo)
    while True:
        if stop is not None and stop():
            raise SystemExit(130)
        with _lease_file_lock(lock_path):
            conn = _connect(db_path)
            _ensure_lease_table(conn)
            _reap_stale_leases(conn)
            used = _lease_count(conn)
            mx = _pool_max()
            free = mx - used
            if free >= 1:
                return min(wanted, free)
        time.sleep(_SLEEP)


def acquire_render_slot(*, stop: Callable[[], bool] | None = None) -> None:
    """阻塞直到能占用一格全局渲片租约（当前进程 PID 写入 ``render_leases``）。"""
    repo = _repo_root()
    lock_path = _lease_lock_path(repo)
    db_path = _db_path(repo)
    my_pid = os.getpid()
    while True:
        if stop is not None and stop():
            raise SystemExit(130)
        with _lease_file_lock(lock_path):
            conn = _connect(db_path)
            _ensure_lease_table(conn)
            _reap_stale_leases(conn)
            if _lease_count(conn) < _pool_max():
                conn.execute(
                    "INSERT OR REPLACE INTO render_leases (blender_pid, created_at) VALUES (?, ?)",
                    (my_pid, time.time()),
                )
                conn.commit()
                return
        time.sleep(_SLEEP)


def release_render_slot() -> None:
    """释放本进程占用的渲片租约（幂等）。"""
    repo = _repo_root()
    lock_path = _lease_lock_path(repo)
    db_path = _db_path(repo)
    with _lease_file_lock(lock_path):
        conn = _connect(db_path)
        _ensure_lease_table(conn)
        conn.execute("DELETE FROM render_leases WHERE blender_pid = ?", (os.getpid(),))
        conn.commit()
