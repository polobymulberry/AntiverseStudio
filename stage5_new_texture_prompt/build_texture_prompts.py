"""Stage 5: Combine template description and texture prompts.

``fashion_tag`` 仅写入 CSV 供索引，不参与 ``full_prompt`` 拼接。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from common.settings import SETTINGS
from common.utils import output_template_user_dir, read_csv, write_csv


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--template",
        required=True,
        metavar="NAME",
        help="服装模板名（与阶段4 所用 template_name 一致）",
    )
    parser.add_argument(
        "--user-requirement",
        default=None,
        help="与阶段4 一致的需求全文；与 --fashion-tag 二选一或同传（同传时目录以 tag 为准）。",
    )
    parser.add_argument(
        "--fashion-tag",
        default=None,
        metavar="TAG",
        help="与阶段4 一致时单独定位 run 目录；仅索引，不进入 full_prompt。",
    )
    parser.add_argument(
        "--stage2-csv",
        default=str(SETTINGS.output_root / "stage2_body_template_description.csv"),
        help="阶段2 描述 CSV",
    )
    args = parser.parse_args()

    req = (args.user_requirement or "").strip()
    ft = (args.fashion_tag or "").strip()
    if not req and not ft:
        print(
            "[ERROR] 须指定 --user-requirement 或 --fashion-tag（与阶段4 定位该次 run 一致）。",
            file=sys.stderr,
        )
        sys.exit(1)

    stage2_csv = Path(args.stage2_csv)
    run_dir = output_template_user_dir(
        SETTINGS.output_root,
        args.template.strip(),
        req,
        fashion_tag=ft or None,
    )
    stage4_csv = run_dir / "stage4_fashion_prompt.csv"
    output_csv = run_dir / "stage5_new_texture_prompt.csv"

    if not stage4_csv.is_file():
        print(f"[ERROR] 未找到阶段4 输出: {stage4_csv}", file=sys.stderr)
        sys.exit(1)

    desc_map = {row["template_name"]: row["description"] for row in read_csv(stage2_csv)}
    stage4_rows = read_csv(stage4_csv)

    out_rows: list[dict] = []
    for row in stage4_rows:
        template_name = row["template_name"]
        body_description = desc_map.get(template_name, "")
        texture_prompt = row["prompt_zh"]
        # fashion_tag 只落 CSV，禁止拼进 full_prompt
        tag_out = (row.get("fashion_tag") or "").strip() or ft
        user_req = (row.get("user_requirement") or "").strip()
        theme_line = f"用户主题与气质总述：{user_req}。" if user_req else ""
        # 描述与 prompt 直接拼入正文，不再外加《》；若原文中已有《》则保留不动
        full_prompt = (
            "参考图是3D无头人偶穿着卡通服装渲染图，"
            f"服装具体内容为{body_description}，"
            "一定要确保图片中人偶形态、肤色不变，确保服装几何款式不变，不要改变参考图内容轮廓。"
            f"{theme_line}"
            "生成时须在配色分区、花纹、logo 或文字标的形状与位置上**严格贴合**下列纹理描述，"
            "禁止擅自改成与描述无关的泛化「网红甜美」「万能运动」「小清新模板」等安全牌风格；"
            "**主题与描述契合度优先于**画面是否「通用好看」。"
            f"基于如下描述{texture_prompt}，生成一款不同服装纹理风格的图片，"
            "最终生成的服装纹理要美观，同时纹理风格偏向于Q版卡通，且须与上述主题及纹理描述一致。"
        )
        out_rows.append(
            {
                "template_name": template_name,
                "user_requirement": row["user_requirement"],
                "fashion_tag": tag_out,
                "label_zh": row["label_zh"],
                "label_en": row["label_en"],
                "texture_prompt": texture_prompt,
                "full_prompt": full_prompt,
            }
        )

    write_csv(
        output_csv,
        out_rows,
        [
            "template_name",
            "user_requirement",
            "fashion_tag",
            "label_zh",
            "label_en",
            "texture_prompt",
            "full_prompt",
        ],
    )
    print(f"已写入: {output_csv}")


if __name__ == "__main__":
    main()

