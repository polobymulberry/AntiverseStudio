"""Stage 5: Combine template description and texture prompts.

``full_prompt`` 约定贴图呈 **略偏卡通的 Q 版气质**（与参考人台一致），主题符号清晰、**少写实微肌理**，兼顾 3D 打印识读；并约束裸露肤色与参考图一致或略提亮、勿压暗。
``fashion_tag`` 仅写入 CSV 供索引，不参与 ``full_prompt`` 拼接。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from common.pipeline_render_prefs import list_body_template_names_for_fashion_tag
from common.settings import SETTINGS
from common.utils import body_template_run_dir, read_csv, write_csv


def _process_one_template(
    ft: str,
    template: str,
    stage2_csv: Path,
    *,
    abort_if_missing_stage4: bool,
    pipeline_line: str | None = None,
) -> None:
    run_dir = body_template_run_dir(
        SETTINGS.output_root, ft, template, pipeline_line=pipeline_line
    )
    stage4_csv = run_dir / "stage4_fashion_prompt.csv"
    output_csv = run_dir / "stage5_new_texture_prompt.csv"

    if not stage4_csv.is_file():
        msg = f"未找到阶段4 输出: {stage4_csv}"
        if abort_if_missing_stage4:
            print(f"[ERROR] {msg}", file=sys.stderr)
            sys.exit(1)
        print(f"[SKIP] {template} — {msg}", file=sys.stderr)
        return

    desc_map = {row["template_name"]: row["description"] for row in read_csv(stage2_csv)}
    stage4_rows = read_csv(stage4_csv)

    out_rows: list[dict] = []
    for row in stage4_rows:
        template_name = row["template_name"]
        body_description = desc_map.get(template_name, "")
        texture_prompt = row["prompt_zh"]
        tag_out = (row.get("fashion_tag") or "").strip() or ft
        user_req = (row.get("user_requirement") or "").strip()
        theme_line = f"用户主题与气质总述：{user_req}。" if user_req else ""
        full_prompt = (
            "参考图是3D无头人偶穿着卡通服装渲染图，"
            f"服装具体内容为{body_description}，"
            "一定要确保图片中人偶形态不变，确保服装几何款式不变，不要改变参考图内容轮廓；"
            "**不要凭空增加**参考图上没有的复杂立体衣褶或写实面料微纹理，整体与参考保持**同一卡通阶**。"
            "**裸露可见的皮肤（颈、手、前臂等）须与参考图肤色与明度一致**；"
            "**严禁**整体调色或单独压暗皮肤导致变黑、变褐、变灰、欠曝、脏灰去饱和——若与参考有偏差则宁可**略偏干净透亮或略提亮**，"
            "**绝不要**比参考图更黑更暗，否则观感很差。"
            f"{theme_line}"
            "生成时须在配色分区、花纹、logo 或文字标的形状与位置上**严格贴合**下列纹理描述，"
            "禁止擅自改成与描述无关的泛化「网红甜美」「万能运动」「小清新模板」等安全牌风格；"
            "**主题与描述契合度优先于**画面是否「通用好看」。"
            f"基于如下描述{texture_prompt}，生成一款不同服装纹理风格的图片。"
            "画面与服装贴图**偏 Q 版卡通插画**（色块利落、边缘略圆润、适度扁平），"
            "在**不增加**写实级织纹/褶皱/高光细节的前提下，保留描述中的**可辨识符号、色区边界、徽标与道具轮廓**；"
            "避免照片级超清面料与过密细节（不利实物打印），禁止弱化成仅「柔和马卡龙配色」或模糊一团的无主题卡通风。"
            "最终纹理须美观，且卡通气质与上述主题及纹理描述一致。"
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
    print(f"[OK] {template} -> {output_csv}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--template",
        default=None,
        metavar="NAME",
        help=(
            "单套服装模板名（与阶段4 一致）。若省略则读取主题 "
            "pipeline_render_prefs.yml 的 body_templates，按顺序逐套处理。"
        ),
    )
    parser.add_argument(
        "--fashion-tag",
        required=True,
        metavar="TAG",
        help="与阶段4 一致；定位 output/<产品线>/stage4_10/<标签>/<模板>/；仅索引，不进入 full_prompt。",
    )
    parser.add_argument(
        "--pipeline-line",
        default=None,
        metavar="NAME",
        help="output 下产品线子目录名；缺省使用 SETTINGS.pipeline_line（PIPELINE_LINE）。",
    )
    parser.add_argument(
        "--stage2-csv",
        default=str(SETTINGS.output_root / "stage2_body_template_description.csv"),
        help="阶段2 描述 CSV",
    )
    args = parser.parse_args()

    ft = (args.fashion_tag or "").strip()
    if not ft:
        print("[ERROR] 须指定 --fashion-tag。", file=sys.stderr)
        sys.exit(1)

    stage2_csv = Path(args.stage2_csv)
    single = (args.template or "").strip()
    pline = (args.pipeline_line or "").strip() or None
    if single:
        templates = [single]
    else:
        try:
            templates = list_body_template_names_for_fashion_tag(
                SETTINGS.output_root, ft, pipeline_line=pline
            )
        except (FileNotFoundError, ValueError) as e:
            print(f"[ERROR] {e}", file=sys.stderr)
            sys.exit(1)

    print(f"[RUN] Stage5 将处理 {len(templates)} 套模板: {', '.join(templates)}", flush=True)
    single = len(templates) == 1
    for t in templates:
        _process_one_template(ft, t, stage2_csv, abort_if_missing_stage4=single, pipeline_line=pline)


if __name__ == "__main__":
    main()

