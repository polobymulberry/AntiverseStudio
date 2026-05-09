"""Stage 2: Generate short clothing template descriptions via Qwen."""

from __future__ import annotations

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


def main() -> None:
    input_dir = SETTINGS.output_root / "stage1_body_template_preview"
    output_csv = SETTINGS.output_root / "stage2_body_template_description.csv"
    fieldnames = ["template_name", "image_path", "description"]

    ensure_dir(output_csv.parent)
    with output_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        f.flush()

        for image_path in sorted(input_dir.glob("*.png")):
            template_name = image_path.stem
            description = describe_image(image_path)
            row = {
                "template_name": template_name,
                "image_path": str(image_path),
                "description": description,
            }
            writer.writerow(row)
            f.flush()
            print(f"[OK] {template_name}: {description}")

    print(f"已写入（每图一条即时落盘）: {output_csv}")


if __name__ == "__main__":
    main()

