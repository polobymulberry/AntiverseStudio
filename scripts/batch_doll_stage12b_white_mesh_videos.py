#!/usr/bin/env python3
"""按产品线批量跑 Stage12b（身体 + solid 头发 + 真人头白模合成视频）。

枚举 ``output/<产品线>/stage4_10/`` 下含 ``pipeline_render_prefs.yml`` 的主题目录；对每个主题的
``body_templates`` 逐项调用 ``blender_render_pool.py`` + ``render_around_white_mesh.blend`` +
``stage12b_body_head_hair_render_white_mesh_videos/blender_render_composite_white_mesh.py``。

**须**显式 ``--pipeline``；子进程设置 ``PIPELINE_LINE``，与单主题手动命令一致。

用法::

    python scripts/batch_doll_stage12b_white_mesh_videos.py --pipeline 卡通人偶定制

可选：``--fashion-tag``（只跑一个主题）、``--theme-workers``（未指定时默认 **6**，整批并行主题数）、
``--inner-workers``（传给 Stage12b 的 ``--workers``；单主题内多 Blender；未指定时默认 **1**）、
``--resume``、``--dry-run``。
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
from common.pipeline_render_prefs import (
    load_render_prefs_dict,
    parse_body_templates_from_prefs,
    pipeline_render_prefs_path,
)
from common.settings import SETTINGS
from common.utils import body_template_run_dir


def _build_pool_cmd(
    *,
    fashion_tag: str,
    template: str,
    inner_workers: int,
    resume: bool,
) -> list[str]:
    blend = _REPO_ROOT / "resource" / "blender" / "render_around_white_mesh.blend"
    script = (
        _REPO_ROOT
        / "stage12b_body_head_hair_render_white_mesh_videos"
        / "blender_render_composite_white_mesh.py"
    )
    pool = _REPO_ROOT / "scripts" / "blender_render_pool.py"
    inner: list[str] = [
        "--fashion-tag",
        fashion_tag,
        "--template",
        template,
        "--workers",
        str(inner_workers),
    ]
    if resume:
        inner.append("--resume")
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


def _run_one_template(
    *,
    fashion_tag: str,
    template: str,
    pipeline_line: str,
    inner_workers: int,
    resume: bool,
    dry_run: bool,
) -> int:
    cmd = _build_pool_cmd(
        fashion_tag=fashion_tag,
        template=template,
        inner_workers=inner_workers,
        resume=resume,
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
    theme_dir: Path,
    *,
    pipeline_line: str,
    inner_workers: int,
    resume: bool,
    dry_run: bool,
    out_root: Path,
    total: int,
    lock: threading.Lock,
    counter: list[int],
    failed: list[str],
) -> None:
    """单主题：按 YAML ``body_templates`` 顺序跑各模板的 Stage12b。"""
    fashion_tag = theme_dir.name
    detail = "异常"
    try:
        prefs_path = pipeline_render_prefs_path(theme_dir)
        prefs_data = load_render_prefs_dict(prefs_path)
        try:
            pairs = parse_body_templates_from_prefs(prefs_data)
        except (TypeError, ValueError) as e:
            detail = f"body_templates 解析失败: {e}"
            with lock:
                failed.append(f"{fashion_tag}:prefs")
            return
        if not pairs:
            detail = "无 body_templates"
            with lock:
                failed.append(f"{fashion_tag}:no_templates")
            return

        worst = 0
        for tmpl, _ in pairs:
            run_dir = body_template_run_dir(
                out_root, fashion_tag, tmpl, pipeline_line=pipeline_line
            )
            s8 = run_dir / "stage8_new_texture_model_generation"
            if not s8.is_dir():
                print(f"[SKIP] 无 stage8 目录: {run_dir}", flush=True)
                continue
            if not any(s8.glob("*.glb")):
                print(f"[SKIP] stage8 下无 GLB: {run_dir}", flush=True)
                continue
            rc = _run_one_template(
                fashion_tag=fashion_tag,
                template=tmpl,
                pipeline_line=pipeline_line,
                inner_workers=inner_workers,
                resume=resume,
                dry_run=dry_run,
            )
            worst = max(worst, rc)
        detail = f"exit={worst}"
        if worst != 0:
            with lock:
                failed.append(f"{fashion_tag}:stage12b")
    finally:
        with lock:
            counter[0] += 1
            cur = counter[0]
        print(
            f"[PROGRESS] {cur}/{total} tag={fashion_tag} {detail}",
            flush=True,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pipeline",
        required=True,
        metavar="LINE",
        help="output 下产品线子目录名（如 卡通人偶定制）。",
    )
    parser.add_argument(
        "--fashion-tag",
        "--only-tag",
        dest="fashion_tag",
        default=None,
        metavar="TAG",
        help="只处理该主题（目录 basename 或 YAML 内 fashion_tag 匹配规则与 filter_theme_dirs 一致）。",
    )
    parser.add_argument(
        "--theme-workers",
        type=int,
        default=None,
        metavar="N",
        help="整批并行主题数；未指定时默认 6。",
    )
    parser.add_argument(
        "--inner-workers",
        type=int,
        default=None,
        metavar="N",
        help="传给 Stage12b 的 --workers（单主题内、单模板下多 Blender）；未指定时默认 1。",
    )
    parser.add_argument("--resume", action="store_true", help="传给 Stage12b")
    parser.add_argument("--dry-run", action="store_true", help="只打印命令")
    args = parser.parse_args()

    line = (args.pipeline or "").strip()
    if not line:
        parser.error("--pipeline 不能为空。")

    inner_w = args.inner_workers
    if inner_w is None:
        inner_w = 1
    inner_w = max(1, int(inner_w))

    theme_w = args.theme_workers
    if theme_w is None:
        theme_w = 6
    theme_w = max(1, int(theme_w))

    out_root = Path(SETTINGS.output_root).resolve()
    stage4_10 = stage4_10_root(out_root, pipeline_line=line)
    fashion = (args.fashion_tag or "").strip() or None
    themes = filter_theme_dirs(stage4_10, fashion)
    total = len(themes)
    print(f"[INFO] stage4_10 根: {stage4_10}", flush=True)
    print(
        f"[INFO] 产品线={line!r} 主题数={total} "
        f"theme_workers={theme_w} inner_workers={inner_w}",
        flush=True,
    )
    if total == 0:
        print("[WARN] 无主题目录。", flush=True)
        return

    lock = threading.Lock()
    counter: list[int] = [0]
    failed: list[str] = []

    with ThreadPoolExecutor(max_workers=theme_w) as pool:
        futures = [
            pool.submit(
                _worker_theme,
                d,
                pipeline_line=line,
                inner_workers=inner_w,
                resume=bool(args.resume),
                dry_run=bool(args.dry_run),
                out_root=out_root,
                total=total,
                lock=lock,
                counter=counter,
                failed=failed,
            )
            for d in themes
        ]
        for fut in as_completed(futures):
            fut.result()

    print(f"[DONE] 已处理 {total} 个主题的 Stage12b 调度。", flush=True)
    if failed:
        print(f"[WARN] 失败: {' '.join(failed)}", flush=True)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
