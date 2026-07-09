"""Pet Stage2：按 Stage1 CSV 本地 Qwen-Image-2512 生成宠物摄影棚头部特写图。

输入：``output/pet_model_library/<run-subdir>/pet_model_prompts.csv``
输出：``…/images/<species_id>.png``

使用 ``common/qwen_image_local.py`` 加载本地 diffusers 权重（``QWEN_IMAGE_MODEL_PATH``），
不调用 DashScope Qwen-Image Web API。

``--resume`` 时跳过已存在的有效 PNG。
大批量（如千条 prompt）可加 ``--multi-gpu`` 启用多 GPU 队列。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from common.pet_pipeline_paths import pet_model_images_dir, pet_model_prompts_csv_path
from common.qwen_image_local import (
    LocalImageRunConfig,
    iter_pending_tasks_from_rows,
    parse_qwen_image_wh,
    run_local_image_tasks,
)
from common.settings import SETTINGS
from common.utils import ensure_dir, read_csv


def main() -> None:
    parser = argparse.ArgumentParser(description="Pet Stage2：本地 Qwen-Image-2512 生成宠物模特图。")
    parser.add_argument("--run-subdir", required=True, help="与 Stage1 相同的批次名。")
    parser.add_argument(
        "--input-csv",
        default=None,
        help="可选：覆盖默认 pet_model_prompts.csv 路径",
    )
    parser.add_argument("--resume", action="store_true", help="跳过已存在有效 PNG。")
    parser.add_argument(
        "--size",
        default=f"{SETTINGS.qwen_image_width}*{SETTINGS.qwen_image_height}",
        help="出图尺寸 宽*高（或 宽x高），默认 QWEN_IMAGE_WIDTH × QWEN_IMAGE_HEIGHT",
    )
    parser.add_argument(
        "--model-path",
        default=None,
        help=f"本地权重目录，默认 env QWEN_IMAGE_MODEL_PATH={SETTINGS.qwen_image_model_path}",
    )
    parser.add_argument(
        "--multi-gpu",
        action="store_true",
        help="多 GPU 队列批量出图（默认单进程顺序推理，适合少量 CSV 行）",
    )
    parser.add_argument(
        "--only-species",
        default=None,
        metavar="SPECIES_ID",
        help="仅生成指定 species_id 一行",
    )
    args = parser.parse_args()

    csv_path = (
        Path(args.input_csv).resolve()
        if args.input_csv
        else pet_model_prompts_csv_path(SETTINGS.output_root, args.run_subdir)
    )
    if not csv_path.is_file():
        print(f"[ERROR] 未找到 Stage1 CSV: {csv_path}", file=sys.stderr)
        sys.exit(1)

    rows = read_csv(csv_path)
    if not rows:
        print("[ERROR] CSV 为空。", file=sys.stderr)
        sys.exit(1)

    width, height = parse_qwen_image_wh(args.size)
    model_path = (args.model_path or str(SETTINGS.qwen_image_model_path)).strip()
    if not Path(model_path).is_dir():
        print(
            f"[ERROR] Qwen-Image 本地模型目录不存在: {model_path}\n"
            "请设置 QWEN_IMAGE_MODEL_PATH 或 --model-path。",
            file=sys.stderr,
        )
        sys.exit(1)

    run_config = LocalImageRunConfig.from_settings(
        model_path=model_path,
        width=width,
        height=height,
    )

    out_dir = ensure_dir(pet_model_images_dir(SETTINGS.output_root, args.run_subdir))
    only = (args.only_species or "").strip()

    tasks = list(
        iter_pending_tasks_from_rows(
            rows,
            out_dir,
            only_species=only,
            resume=args.resume,
        )
    )
    print(f"[RUN] CSV: {csv_path}", flush=True)
    print(f"[RUN] 输出: {out_dir}", flush=True)
    print(
        f"[RUN] 本地 Qwen-Image: {model_path} {width}×{height} "
        f"multi_gpu={args.multi_gpu} 待生成={len(tasks)}",
        flush=True,
    )
    if not tasks:
        print("[DONE] 无待生成任务（均已存在或 CSV 无有效行）。", flush=True)
        return

    ok, failed = run_local_image_tasks(
        tasks,
        run_config=run_config,
        multi_gpu=args.multi_gpu,
    )
    print(f"[DONE] 成功 {ok}，失败 {failed}", flush=True)
    if failed:
        sys.exit(1)
    print(
        f"[DONE] 审阅通过后，可将精选图复制到 {SETTINGS.pet_model_reference_root}/",
        flush=True,
    )


if __name__ == "__main__":
    main()
