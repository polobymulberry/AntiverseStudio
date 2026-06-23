"""批量对 ``output/<产品线>/stage4_10/`` 下各主题跑 Stage8（混元 API 贴图）。

与单主题命令一致，但自动枚举含 ``pipeline_render_prefs.yml`` 的主题目录，对每个主题执行::

    python stage8_new_texture_model_generation/generate_textured_models.py \\
      --fashion-tag <主题目录名> --pipeline-line <产品线>

**须**显式 ``--pipeline``，与 ``batch_doll_texture_stages.py`` 相同，避免 ``PIPELINE_LINE`` 漏设。

用法（仓库根、已 ``conda activate figshion3d``）::

    python scripts/batch_doll_stage8_textured_models.py --pipeline 卡通人偶定制

可选：``--fashion-tag``（只跑一个主题）、``--theme-workers``（多主题并行数，默认 1）、``--dry-run``。
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


def _run_stage8_subprocess(
    *,
    fashion_tag: str,
    pipeline_line: str,
    dry_run: bool,
) -> int:
    cmd = [
        sys.executable,
        str(_REPO_ROOT / "stage8_new_texture_model_generation" / "generate_textured_models.py"),
        "--fashion-tag",
        fashion_tag,
        "--pipeline-line",
        pipeline_line,
    ]
    print(f"[CMD] {' '.join(cmd)}", flush=True)
    if dry_run:
        return 0
    env = os.environ.copy()
    env["PIPELINE_LINE"] = pipeline_line
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
    dry_run: bool,
    total: int,
    lock: threading.Lock,
    counter: list[int],
    failed: list[str],
) -> None:
    detail = "异常"
    code = 1
    try:
        code = _run_stage8_subprocess(
            fashion_tag=fashion_tag,
            pipeline_line=pipeline_line,
            dry_run=dry_run,
        )
        detail = f"exit={code}"
        if code != 0:
            with lock:
                failed.append(f"{fashion_tag}:stage8")
    finally:
        with lock:
            counter[0] += 1
            cur = counter[0]
        print(f"[PROGRESS] {cur}/{total} tag={fashion_tag} Stage8 {detail}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pipeline",
        required=True,
        metavar="LINE",
        help="output 下产品线子目录名（须与磁盘路径一致）。",
    )
    parser.add_argument(
        "--fashion-tag",
        "--only-tag",
        dest="fashion_tag",
        default=None,
        metavar="TAG",
        help="只处理该主题（目录 basename 或 YAML 内 fashion_tag / 截断名）。",
    )
    parser.add_argument(
        "--theme-workers",
        type=int,
        default=1,
        metavar="N",
        help="并行主题数上限（默认 1，避免 API 并发过高）。",
    )
    parser.add_argument("--dry-run", action="store_true", help="只打印将执行的命令，不调用子进程")
    args = parser.parse_args()

    line = (args.pipeline or "").strip()
    if not line:
        parser.error("--pipeline 不能为空。")

    out_root = Path(SETTINGS.output_root).resolve()
    stage4_10 = stage4_10_root(out_root, pipeline_line=line)
    fashion = (args.fashion_tag or "").strip() or None
    themes = filter_theme_dirs(stage4_10, fashion)
    total = len(themes)
    print(f"[INFO] stage4_10 根: {stage4_10}", flush=True)
    print(f"[INFO] 产品线: {line!r} 待处理主题数={total}", flush=True)
    if total == 0:
        print("[WARN] 无主题目录（须含 pipeline_render_prefs.yml）", flush=True)
        return

    n_workers = max(1, int(args.theme_workers))
    print(f"[INFO] theme_workers={n_workers}", flush=True)

    lock = threading.Lock()
    counter: list[int] = [0]
    failed: list[str] = []

    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        futures = [
            pool.submit(
                _worker_theme,
                d.name,
                pipeline_line=line,
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

    print(f"[DONE] 已处理 {total} 个主题。", flush=True)
    if failed:
        print(f"[WARN] 失败: {' '.join(failed)}", flush=True)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
