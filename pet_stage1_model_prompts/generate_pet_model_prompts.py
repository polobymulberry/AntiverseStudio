"""Pet Stage1：生成内置宠物高清模特 Prompt CSV（默认 10 个品种）。

输出：``output/pet_model_library/<run-subdir>/pet_model_prompts.csv``

确认 CSV 内容无误后，再运行 ``pet_stage2_model_images/generate_pet_model_images.py`` 出图。
可手工编辑 CSV 的 ``full_prompt`` / ``subject_desc`` 后再跑 Stage2。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from common.pet_model_prompts import PET_MODEL_PROMPTS_CSV_FIELDS, default_pet_model_prompt_rows
from common.pet_pipeline_paths import pet_model_prompts_csv_path
from common.settings import SETTINGS
from common.utils import ensure_dir, read_csv, write_csv


def main() -> None:
    parser = argparse.ArgumentParser(description="生成宠物内置模特 Prompt CSV（默认 10 品种）。")
    parser.add_argument(
        "--run-subdir",
        required=True,
        help="批次名，输出到 output/pet_model_library/<run-subdir>/",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="覆盖已存在的 pet_model_prompts.csv",
    )
    parser.add_argument(
        "--output-csv",
        default=None,
        help="可选：指定完整 CSV 路径（覆盖默认 run 目录）",
    )
    args = parser.parse_args()

    csv_path = (
        Path(args.output_csv).resolve()
        if args.output_csv
        else pet_model_prompts_csv_path(SETTINGS.output_root, args.run_subdir)
    )
    if csv_path.is_file() and not args.overwrite:
        print(
            f"[ERROR] CSV 已存在: {csv_path}\n"
            "请 --overwrite 覆盖，或手工编辑后运行 pet_stage2_model_images。",
            file=sys.stderr,
        )
        sys.exit(1)

    ensure_dir(csv_path.parent)
    rows = default_pet_model_prompt_rows()
    write_csv(csv_path, rows, fieldnames=list(PET_MODEL_PROMPTS_CSV_FIELDS))
    print(f"[OK] 已写入 {len(rows)} 条 prompt -> {csv_path}", flush=True)
    print("[NEXT] 请人工审阅 CSV，确认后执行:", flush=True)
    print(
        f"  python pet_stage2_model_images/generate_pet_model_images.py "
        f"--run-subdir {args.run_subdir}",
        flush=True,
    )

    # 校验可读
    loaded = read_csv(csv_path)
    if len(loaded) != len(rows):
        print("[WARN] 读回 CSV 行数与写入不一致。", file=sys.stderr)


if __name__ == "__main__":
    main()
