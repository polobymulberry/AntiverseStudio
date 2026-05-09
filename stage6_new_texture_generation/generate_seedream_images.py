"""Stage 6: Save N PNGs per CSV row via Seedream (default N=4).

对每条 `full_prompt` 连续发起 N 次 API 请求，每次 `n=1`，得到 N 张图（不在 prompt 前拼接额外指令）。
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
from common.settings import SETTINGS
from common.utils import (
    PIPELINE_TEMPLATE_USER_SUBDIR,
    ensure_dir,
    file_to_data_url,
    output_template_user_dir,
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input-csv",
        default=None,
        help="阶段5 输出 CSV；若省略须指定 --template 以及 --user-requirement 或 --fashion-tag",
    )
    parser.add_argument(
        "--template",
        default=None,
        metavar="NAME",
        help="与阶段4/5 所用模板名一致（与 --user-requirement 或 --fashion-tag 联用以定位默认 stage5 CSV）",
    )
    parser.add_argument(
        "--user-requirement",
        default=None,
        help="与阶段4/5 所用需求全文一致；与 --fashion-tag 二选一或同传（同传时目录以 tag 为准）。",
    )
    parser.add_argument(
        "--fashion-tag",
        default=None,
        metavar="TAG",
        help="与阶段4 一致；仅定位 run 与 CSV，不写入 full_prompt。",
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

    req = (args.user_requirement or "").strip()
    ft = (args.fashion_tag or "").strip()

    if args.input_csv:
        input_csv = Path(args.input_csv)
    elif args.template and (req or ft):
        input_csv = (
            output_template_user_dir(
                SETTINGS.output_root,
                args.template.strip(),
                req,
                fashion_tag=ft or None,
            )
            / "stage5_new_texture_prompt.csv"
        )
    else:
        parser.error("请指定 --input-csv，或同时指定 --template 与（--user-requirement 或 --fashion-tag）")

    if not input_csv.is_file():
        print(f"[ERROR] 未找到阶段5 CSV: {input_csv}", file=sys.stderr)
        sys.exit(1)

    rows = read_csv(input_csv)
    total = len(rows)

    print(f"[RUN] 阶段5 CSV: {input_csv}", flush=True)
    print(
        f"[RUN] 共 {total} 条 prompt；图片写入 "
        f"output/{PIPELINE_TEMPLATE_USER_SUBDIR}/<template>/<需求截断>/stage6_new_texture_generation/",
        flush=True,
    )
    if rows:
        r0 = rows[0]
        rd = output_template_user_dir(
            SETTINGS.output_root,
            r0["template_name"],
            r0.get("user_requirement") or "",
            fashion_tag=(r0.get("fashion_tag") or "").strip() or None,
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
        # 强化文生图对「描述落实」的权重（与阶段5 全文配合）
        seedream_prompt = (
            "【必须遵守】成图中服装的配色、花纹、logo/文字标须与下文**逐项对应**，"
            "不得替换为未出现的常见装饰或泛化可爱风；参考图仅保留人台与服装版型，纹样与颜色以文字描述为准。\n\n"
            + base_prompt
        )
        run_dir = output_template_user_dir(
            SETTINGS.output_root,
            template,
            row.get("user_requirement") or "",
            fashion_tag=(row.get("fashion_tag") or "").strip() or None,
        )
        output_dir = ensure_dir(run_dir / "stage6_new_texture_generation")
        print(f"[Stage6] 落盘目录: {output_dir}", flush=True)
        saved = 0
        skipped = 0
        for shot in range(1, num_images + 1):
            out_file = output_dir / f"{label_zh}_{shot}.png"
            if args.resume and _png_exists_nonempty(out_file):
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
        if args.resume and skipped:
            print(
                f"[OK] {template}/{label_zh} -> 新生成 {saved} 张，跳过 {skipped} 张",
                flush=True,
            )
        else:
            print(f"[OK] {template}/{label_zh} -> {saved} 张", flush=True)

    print(f"[DONE] 处理完成，共遍历 {total} 条。", flush=True)


if __name__ == "__main__":
    main()

