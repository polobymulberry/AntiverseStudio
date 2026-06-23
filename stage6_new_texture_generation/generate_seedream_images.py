"""Stage 6: Save N PNGs per CSV row via Seedream (default N=4).

对每条 `full_prompt` 连续发起 N 次 API 请求，每次 `n=1`，得到 N 张图；在每条前拼接简短「风格阶」约束（略卡通、少写实微肌理、贴近参考版型）。
`--resume` 时按序号跳过已存在的非空 PNG，仅补缺失张。
"""

from __future__ import annotations

import argparse
import base64
import sys
from pathlib import Path

import requests

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from common.llm_clients import seedream_generate
from common.pipeline_render_prefs import list_body_template_names_for_fashion_tag
from common.settings import SETTINGS
from common.utils import (
    PIPELINE_TEMPLATE_USER_SUBDIR,
    body_template_run_dir,
    ensure_dir,
    file_to_data_url,
    read_csv,
    truncate_for_path,
)


def save_image_from_item(item: dict, output_path: Path) -> None:
    if "url" in item and item["url"]:
        resp = requests.get(item["url"], timeout=120)
        resp.raise_for_status()
        output_path.write_bytes(resp.content)
        return
    if "b64_json" in item and item["b64_json"]:
        output_path.write_bytes(base64.b64decode(item["b64_json"]))
        return
    raise RuntimeError(f"无法解析图片响应字段: {item}")


def _png_exists_nonempty(path: Path) -> bool:
    return path.is_file() and path.stat().st_size > 0


def _run_stage6_on_csv(
    input_csv: Path,
    num_images: int,
    resume: bool,
    *,
    pipeline_line: str | None = None,
) -> None:
    if not input_csv.is_file():
        print(f"[ERROR] 未找到阶段5 CSV: {input_csv}", file=sys.stderr)
        sys.exit(1)

    rows = read_csv(input_csv)
    total = len(rows)

    print(f"[RUN] 阶段5 CSV: {input_csv}", flush=True)
    print(
        f"[RUN] 共 {total} 条 prompt；图片写入 "
        f"output/<产品线>/{PIPELINE_TEMPLATE_USER_SUBDIR}/<fashion-tag>/<template>/stage6_new_texture_generation/",
        flush=True,
    )
    if rows:
        r0 = rows[0]
        ft0 = (r0.get("fashion_tag") or "").strip()
        rd = body_template_run_dir(
            SETTINGS.output_root, ft0, r0["template_name"], pipeline_line=pipeline_line
        )
        print(f"[RUN] 示例输出目录: {rd / 'stage6_new_texture_generation'}", flush=True)

    for i, row in enumerate(rows, start=1):
        template = row["template_name"]
        label_zh = truncate_for_path(row["label_zh"])
        reference_image = SETTINGS.output_root / "stage1_body_template_preview" / f"{template}.png"
        print(
            f"[Stage6] ({i}/{total}) {template} / {label_zh} …",
            flush=True,
        )
        if not reference_image.exists():
            print(f"[SKIP] {template} 缺少参考图: {reference_image}", flush=True)
            continue

        print(f"[Stage6] 读取并编码参考图: {reference_image}", flush=True)
        ref_url = file_to_data_url(reference_image)
        base_prompt = (row.get("full_prompt") or "").strip()
        seedream_prompt = (
            "【必须遵守】成图中服装的配色、花纹、logo/文字标须与下文**逐项对应**，"
            "不得替换为未出现的常见装饰或泛化可爱风；参考图仅保留人台与服装版型，纹样与颜色以文字描述为准。"
            "**风格阶**：整体略偏**可爱卡通、扁平插画感**，大块面色面清晰，**少**照片级写实面料与过密微褶皱，利于实物打印识读；"
            "在严守上文前提下**尽量贴近**参考人台的卡通比例与衣褶体量，勿为「真实感」擅自改版型轮廓。\n\n"
            + base_prompt
        )
        ft_row = (row.get("fashion_tag") or "").strip()
        if not ft_row:
            print(f"[SKIP] 第 {i} 行缺少 fashion_tag，无法定位输出目录。", flush=True)
            continue
        run_dir = body_template_run_dir(
            SETTINGS.output_root, ft_row, template, pipeline_line=pipeline_line
        )
        output_dir = ensure_dir(run_dir / "stage6_new_texture_generation")
        print(f"[Stage6] 落盘目录: {output_dir}", flush=True)
        saved = 0
        skipped = 0
        for shot in range(1, num_images + 1):
            out_file = output_dir / f"{label_zh}_{shot}.png"
            if resume and _png_exists_nonempty(out_file):
                print(
                    f"[Stage6] 第 {shot}/{num_images} 张已存在，跳过 -> {out_file.name}",
                    flush=True,
                )
                skipped += 1
                continue
            print(
                f"[Stage6] Seedream 第 {shot}/{num_images} 次请求（n=1）…",
                flush=True,
            )
            result = seedream_generate(
                prompt=seedream_prompt,
                image_url=ref_url,
                n=1,
                size="2048x2048",
                response_format="url",
            )
            batch = result.get("data", [])
            if len(batch) != 1:
                print(
                    f"[WARN] 第 {shot} 次期望 1 张，实际 {len(batch)} 张",
                    flush=True,
                )
            if not batch:
                print(f"[WARN] 第 {shot} 次无数据，跳过落盘", flush=True)
                continue
            print(f"[Stage6]   保存 -> {out_file.name}", flush=True)
            save_image_from_item(batch[0], out_file)
            saved += 1
        done = saved + skipped
        if done != num_images:
            print(
                f"[WARN] 本行期望 {num_images} 张，实际完成 {done} 张（新生成 {saved}，resume 跳过 {skipped}）",
                flush=True,
            )
        if resume and skipped:
            print(
                f"[OK] {template}/{label_zh} -> 新生成 {saved} 张，跳过 {skipped} 张",
                flush=True,
            )
        else:
            print(f"[OK] {template}/{label_zh} -> {saved} 张", flush=True)

    print(f"[DONE] {input_csv.name} 共遍历 {total} 条。", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input-csv",
        default=None,
        help="阶段5 输出 CSV；若省略可用 --fashion-tag（及可选 --template）或仅 --fashion-tag 遍历 prefs",
    )
    parser.add_argument(
        "--template",
        default=None,
        metavar="NAME",
        help=(
            "与阶段4/5 一致；与 --fashion-tag 联用定位该套模板的 stage5 CSV。"
            "若省略且提供 --fashion-tag，则按 pipeline_render_prefs.yml 的 body_templates 逐套处理。"
        ),
    )
    parser.add_argument(
        "--fashion-tag",
        required=False,
        default=None,
        metavar="TAG",
        help="与阶段4 一致；定位 output/<产品线>/stage4_10/<标签>/<模板>/；不写入 full_prompt。",
    )
    parser.add_argument(
        "--pipeline-line",
        default=None,
        metavar="NAME",
        help="output 下产品线子目录名；缺省使用 SETTINGS.pipeline_line（PIPELINE_LINE）。",
    )
    parser.add_argument(
        "--num-images",
        type=int,
        default=4,
        metavar="N",
        help="每条 CSV 连续请求次数，每次 Seedream n=1，共得到 N 张图（默认 4）",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="按张补全：若目标 PNG 已存在且非空则跳过该张，仅请求缺失序号",
    )
    args = parser.parse_args()
    num_images = max(1, args.num_images)

    ft = (args.fashion_tag or "").strip()
    tpl = (args.template or "").strip()
    pline = (args.pipeline_line or "").strip() or None

    if args.input_csv:
        csv_paths = [Path(args.input_csv)]
    elif tpl and ft:
        csv_paths = [
            body_template_run_dir(
                SETTINGS.output_root, ft, tpl, pipeline_line=pline
            )
            / "stage5_new_texture_prompt.csv"
        ]
    elif ft and not tpl:
        try:
            names = list_body_template_names_for_fashion_tag(
                SETTINGS.output_root, ft, pipeline_line=pline
            )
        except (FileNotFoundError, ValueError) as e:
            print(f"[ERROR] {e}", file=sys.stderr)
            sys.exit(1)
        csv_paths = []
        for name in names:
            p = (
                body_template_run_dir(
                    SETTINGS.output_root, ft, name, pipeline_line=pline
                )
                / "stage5_new_texture_prompt.csv"
            )
            if p.is_file():
                csv_paths.append(p)
            else:
                print(f"[WARN] 跳过（尚无 stage5 CSV）: {p}", flush=True)
        if not csv_paths:
            print("[ERROR] 未找到任何 stage5_new_texture_prompt.csv，请先跑 Stage5。", file=sys.stderr)
            sys.exit(1)
    else:
        parser.error("请指定 --input-csv，或同时指定 --template 与 --fashion-tag，或仅 --fashion-tag（遍历 prefs）")

    if len(csv_paths) > 1:
        print(f"[RUN] Stage6 将依次处理 {len(csv_paths)} 个 stage5 CSV。", flush=True)
    for idx, input_csv in enumerate(csv_paths, start=1):
        if len(csv_paths) > 1:
            print(f"[RUN] --- ({idx}/{len(csv_paths)}) {input_csv} ---", flush=True)
        _run_stage6_on_csv(input_csv, num_images, args.resume, pipeline_line=pline)


if __name__ == "__main__":
    main()

