"""按主题批量调用 ``blender_render_pool.py``，跑 Stage9（``--pass covers``）或 Stage11（``--pass videos``）。

枚举 ``output/<产品线>/stage4_10/`` 下含 ``pipeline_render_prefs.yml`` 的主题目录，对每个主题执行与
``docs/script_template.md`` 中单主题示例等价的池化 Blender 命令；``--fashion-tag`` 为主题目录 basename。

**须**显式 ``--pipeline``，子进程环境会设置 ``PIPELINE_LINE``，与单主题手动命令一致。

用法::

    python scripts/batch_doll_blender_stage9_11.py --pass covers --pipeline 卡通人偶定制
    python scripts/batch_doll_blender_stage9_11.py --pass videos --pipeline 卡通人偶定制 --studio-tint-hex '#E3D9C6'

可选：``--fashion-tag``、``--theme-workers``（未指定时 covers=1、**videos=6**，表示整批并行主题数）、
``--inner-workers``（传给 blender 脚本 ``--workers``；单主题内多 Blender 子进程；未指定时默认 **1**）、
``--resume``、``--all-glbs``（仅 videos）、``--debug``（渲后导出 .blend 到 stage9/11 输出目录）、``--dry-run``。
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from common.doll_stage4_10_theme_dirs import filter_theme_dirs, stage4_10_root
from common.settings import SETTINGS


def _build_pool_cmd(
    *,
    fashion_tag: str,
    render_pass: str,
    inner_workers: int,
    resume: bool,
    studio_tint_hex: str | None,
    all_glbs: bool,
    debug: bool,
) -> list[str]:
    blend = _REPO_ROOT / "resource" / "blender" / "blender_render_videos.blend"
    script = _REPO_ROOT / "stage11_render_videos" / "blender_render_videos.py"
    pool = _REPO_ROOT / "scripts" / "blender_render_pool.py"
    inner: list[str] = [
        "--pass",
        render_pass,
        "--fashion-tag",
        fashion_tag,
        "--workers",
        str(inner_workers),
    ]
    if resume:
        inner.append("--resume")
    if studio_tint_hex:
        inner.extend(["--studio-tint-hex", studio_tint_hex.strip()])
    if all_glbs:
        inner.append("--all-glbs")
    if debug:
        inner.append("--debug")
    return [
        sys.executable,
        str(pool),
        "--",
        "blender",
        "-b",
        "--python-use-system-env",
        str(blend),
        "-P",
        str(script),
        "--",
        *inner,
    ]


def _run_blender_subprocess(
    *,
    fashion_tag: str,
    pipeline_line: str,
    render_pass: str,
    inner_workers: int,
    resume: bool,
    studio_tint_hex: str | None,
    all_glbs: bool,
    debug: bool,
    dry_run: bool,
) -> int:
    cmd = _build_pool_cmd(
        fashion_tag=fashion_tag,
        render_pass=render_pass,
        inner_workers=inner_workers,
        resume=resume,
        studio_tint_hex=studio_tint_hex,
        all_glbs=all_glbs,
        debug=debug,
    )
    print(f"[CMD] {' '.join(cmd)}", flush=True)
    if dry_run:
        return 0
    env = os.environ.copy()
    env["PIPELINE_LINE"] = pipeline_line
    env["BLENDER_WORKERS"] = str(inner_workers)
    return int(
        subprocess.call(
            cmd,
            cwd=str(_REPO_ROOT),
            env=env,
        )
    )


def _worker_theme(
    fashion_tag: str,
    *,
    pipeline_line: str,
    render_pass: str,
    inner_workers: int,
    resume: bool,
    studio_tint_hex: str | None,
    all_glbs: bool,
    debug: bool,
    dry_run: bool,
    total: int,
    lock: threading.Lock,
    counter: list[int],
    failed: list[str],
) -> None:
    detail = "异常"
    code = 1
    try:
        code = _run_blender_subprocess(
            fashion_tag=fashion_tag,
            pipeline_line=pipeline_line,
            render_pass=render_pass,
            inner_workers=inner_workers,
            resume=resume,
            studio_tint_hex=studio_tint_hex,
            all_glbs=all_glbs,
            debug=debug,
            dry_run=dry_run,
        )
        detail = f"exit={code}"
        if code != 0:
            with lock:
                failed.append(f"{fashion_tag}:{render_pass}")
    finally:
        with lock:
            counter[0] += 1
            cur = counter[0]
        print(
            f"[PROGRESS] {cur}/{total} tag={fashion_tag} --pass {render_pass} {detail}",
            flush=True,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pass",
        dest="render_pass",
        required=True,
        choices=("covers", "videos"),
        help="covers=Stage9 封面；videos=Stage11 环绕视频。",
    )
    parser.add_argument(
        "--pipeline",
        required=True,
        metavar="LINE",
        help="output 下产品线子目录名。",
    )
    parser.add_argument(
        "--fashion-tag",
        "--only-tag",
        dest="fashion_tag",
        default=None,
        metavar="TAG",
        help="只处理该主题。",
    )
    parser.add_argument(
        "--theme-workers",
        type=int,
        default=None,
        metavar="N",
        help="整批并行主题数；未指定时 covers=1、videos=6（每主题仍由 --inner-workers 控制单主题内并发）。",
    )
    parser.add_argument(
        "--inner-workers",
        type=int,
        default=None,
        metavar="N",
        help="传给 blender_render_videos 的 --workers（单主题内多 Blender）；未指定时默认 1。",
    )
    parser.add_argument("--resume", action="store_true", help="传给 Blender 脚本")
    parser.add_argument(
        "--studio-tint-hex",
        default=None,
        metavar="#RRGGBB",
        help="固定 Studio 背景色（常见与 videos 合用）。",
    )
    parser.add_argument(
        "--all-glbs",
        action="store_true",
        help="仅 videos：为本 run 下全部 stage8 GLB 渲视频。",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="传给 Blender：每个 GLB 渲后在输出目录写入 <stem>_render_debug.blend。",
    )
    parser.add_argument("--dry-run", action="store_true", help="只打印命令")
    args = parser.parse_args()

    line = (args.pipeline or "").strip()
    if not line:
        parser.error("--pipeline 不能为空。")

    rp = args.render_pass
    if args.all_glbs and rp != "videos":
        parser.error("--all-glbs 仅可与 --pass videos 合用。")

    inner_w = args.inner_workers
    if inner_w is None:
        inner_w = 1
    inner_w = max(1, int(inner_w))

    theme_w = args.theme_workers
    if theme_w is None:
        theme_w = 6 if rp == "videos" else 1
    theme_w = max(1, int(theme_w))

    out_root = Path(SETTINGS.output_root).resolve()
    stage4_10 = stage4_10_root(out_root, pipeline_line=line)
    fashion = (args.fashion_tag or "").strip() or None
    themes = filter_theme_dirs(stage4_10, fashion)
    total = len(themes)
    print(f"[INFO] stage4_10 根: {stage4_10}", flush=True)
    print(
        f"[INFO] --pass {rp!r} 产品线={line!r} 主题数={total} "
        f"theme_workers={theme_w} inner_workers={inner_w}",
        flush=True,
    )
    if total == 0:
        print("[WARN] 无主题目录。", flush=True)
        return

    n_workers = theme_w
    print(f"[INFO] 批量并行主题数 theme_workers={n_workers}", flush=True)

    lock = threading.Lock()
    counter: list[int] = [0]
    failed: list[str] = []

    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        futures = [
            pool.submit(
                _worker_theme,
                d.name,
                pipeline_line=line,
                render_pass=rp,
                inner_workers=inner_w,
                resume=bool(args.resume),
                studio_tint_hex=args.studio_tint_hex,
                all_glbs=bool(args.all_glbs),
                debug=bool(args.debug),
                dry_run=bool(args.dry_run),
                total=total,
                lock=lock,
                counter=counter,
                failed=failed,
            )
            for d in themes
        ]
        for fut in as_completed(futures):
            fut.result()

    print(f"[DONE] 已处理 {total} 个主题（--pass {rp}）。", flush=True)
    if failed:
        print(f"[WARN] 失败: {' '.join(failed)}", flush=True)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
