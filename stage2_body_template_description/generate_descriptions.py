"""Stage 2: Generate short clothing template descriptions via Qwen.

默认：对 ``<OUTPUT_ROOT>/stage1_body_template_preview/*.png`` 逐张调用模型，写入
``<OUTPUT_ROOT>/stage2_body_template_description.csv``（全量重写）。

仅更新若干套模板（与已有 CSV **合并**，其它 ``template_name`` 行保留）::

    python stage2_body_template_description/generate_descriptions.py --templates body_05
    python stage2_body_template_description/generate_descriptions.py --templates body_05 body_12
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from common.llm_clients import qwen_chat
from common.settings import SETTINGS
from common.utils import ensure_dir, file_to_data_url

PROMPT = (
    "你是服装设计助理。输入图片是一张「无头人偶」穿着一套「3D 卡通风格服装」的渲染图，"
    "人偶仅作展示体型与姿态，请把描述重心放在服装与配饰本身。"
    "请用中文输出一句简短描述（20-50字），重点写清服装款式与配饰结构（如领型、袖长、裤型、鞋型、帽子包袋等轮廓与部件），"
    "不要描述颜色、纹理、材质；"
    "更不要写衣料上的图案、印花、绣花、纹样、logo、装饰图形，也不要用「抽象/几何/波浪/条纹/格子」等词去概括衣身图案，"
    "不要分点，不要评价画质或背景。"
)


def describe_image(image_path: Path) -> str:
    data_url = file_to_data_url(image_path)
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": PROMPT},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        }
    ]
    return qwen_chat(messages=messages, temperature=0.4, top_p=0.9).strip()


def _load_existing_descriptions(path: Path) -> dict[str, dict[str, str]]:
    if not path.is_file():
        return {}
    out: dict[str, dict[str, str]] = {}
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            name = (row.get("template_name") or "").strip()
            if name:
                out[name] = {
                    "template_name": name,
                    "image_path": row.get("image_path") or "",
                    "description": row.get("description") or "",
                }
    return out


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--templates",
        nargs="+",
        default=None,
        metavar="NAME",
        help="只为这些模板生成描述（须存在 stage1 预览 <NAME>.png）；与已有 stage2 CSV 合并写入",
    )
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    input_dir = SETTINGS.output_root / "stage1_body_template_preview"
    output_csv = SETTINGS.output_root / "stage2_body_template_description.csv"
    fieldnames = ["template_name", "image_path", "description"]

    only = frozenset(x.strip() for x in (args.templates or []) if x.strip()) or None

    if only:
        image_paths: list[Path] = []
        for name in sorted(only):
            p = input_dir / f"{name}.png"
            if p.is_file():
                image_paths.append(p)
            else:
                print(f"[WARN] 无预览图，跳过: {p}", flush=True)
        if not image_paths:
            print("[ERROR] 没有可处理的预览图（检查 --templates 与 stage1 输出目录）", flush=True)
            raise SystemExit(1)
    else:
        image_paths = sorted(input_dir.glob("*.png"))
        if not image_paths:
            print(f"[ERROR] 目录下无 PNG: {input_dir}", flush=True)
            raise SystemExit(1)

    rows_by_name = _load_existing_descriptions(output_csv) if only else {}

    ensure_dir(output_csv.parent)
    for image_path in image_paths:
        template_name = image_path.stem
        description = describe_image(image_path)
        row = {
            "template_name": template_name,
            "image_path": str(image_path),
            "description": description,
        }
        rows_by_name[template_name] = row
        print(f"[OK] {template_name}: {description}", flush=True)

    with output_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for name in sorted(rows_by_name):
            writer.writerow(rows_by_name[name])

    if only:
        print(
            f"已写入: {output_csv}（合并：本次生成 {len(image_paths)} 套，CSV 共 {len(rows_by_name)} 行）",
            flush=True,
        )
    else:
        print(f"已写入: {output_csv}（全量 {len(rows_by_name)} 行）", flush=True)


if __name__ == "__main__":
    main()
