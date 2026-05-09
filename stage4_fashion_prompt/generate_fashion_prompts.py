"""Stage 4: Generate fashion prompts (texture + optional theme logos) for one body template (--template)."""

from __future__ import annotations

# 每条流水线生成的 prompt 条数（与阶段5～6 行数一致）
PROMPT_COUNT = 20

import argparse
import json
import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from common.llm_clients import qwen_chat
from common.pipeline_render_prefs import (
    ensure_initial_render_prefs_yml,
    load_render_prefs_dict,
    pipeline_render_prefs_path,
)
from common.settings import SETTINGS
from common.utils import (
    file_to_data_url,
    output_template_user_dir,
    parse_json_block,
    read_csv,
    write_csv,
)


def build_instruction(user_requirement: str) -> str:
    n = PROMPT_COUNT
    return f"""
你的角色是一位专业的、很懂年轻人的潮流服装与 IP 角色设计师。
给这张参考图片中的服装和配饰换颜色纹理；在合适位置还可增加与用户需求主题相关的 logo、徽标、图形纹样等（须贴合主题、可辨识，作为服装表面的图案装饰，不改变裁片与廓形）。
用户需求描述：{user_requirement}

请生成 {n} 个有明显差异的中文 prompt，用于更换服装和配饰的颜色纹理，以及（可选）上述与主题相关的图案装饰；
不能改变服装和配饰的几何款式与结构，不要描述布料材质本身（如棉麻丝毛等）。
所有 prompt_zh 与 prompt_abstract_zh 均不得出现透明/半透明材质或元素及其比喻，例如：玻璃、水晶、亚克力、透明塑料、薄冰或冰块质感、剔透、透光、透明质、果冻胶感、水感透明层等；不写「像玻璃/像水晶」类说法；服装与配饰表面按不透明色块、印花、哑光或轻微织物光泽处理；图案装饰也不要设计成透明材质观感。
**融合式设计（禁止主题简单堆砌）**：用户需求里的文化、馆藏或 IP 意象必须「织进」整套服装的表面系统（分区拼色、条纹节奏、肌理明暗、镶边织带、渐变晕染、几何迷彩风分区、暗纹提花或水印式低对比纹理等），形成**统一的图形与配色叙事**；禁止偷懒写法：**通体大面积单色 + 正中央一枚巨型** logo、文物剪影、主题插画或徽章独占画面，看起来像主题贴片而非服装设计。**每条 prompt_zh 须写出至少两处以上、彼此呼应**的具体表面语言——例如躯干与袖口的条纹或几何分区节奏不同、裤腿与上衣侧缝的色块或纹样走向呼应、肩线/肘贴/下摆滚边/口袋盖印花联动；主题符号宜缩小占比或拆解为几何纹样、织带镶边、侧缝织唛，融入条纹与拼色系统，而非单独一块居中大图。**反套路**：少用复读式「胸口巨大××图案」；各条须在拼接结构、条纹宽窄、肌理层次、冷暖对比轴上拉开差异。
**主题契合（最重要）**：每条 prompt_zh 必须让读者明确看出**本条与上文「用户需求描述」在主题、情绪、时代、文化或叙事上的直接关联**，禁止写成可套在任意主题上的万能句（如泛泛的「时尚好看」「清新可爱」「简约运动」而看不出当前需求）。请写**具体色相与搭配**（如冷玫红配炭灰、锈橙撞墨绿）、**可辨识的纹样或 logo 语义**（忌仅用「几何图案」「小图标」等空话）；若需求含特定符号、文字气质或色票倾向，须在若干条中**显性化**落实。**反同质化**：各条须在配色轴、图形语言、装饰疏密上彼此显著不同；禁止多条共用同一套「安全牌」粉彩、雷同线描徽章或雷同排版，避免不同主题批次之间看起来风格雷同。
对每条 detailed prompt 同时生成：
- prompt_abstract_zh：在「不引用具体服装品类与部位（如 T 恤、背带裤、裤腿等）」的前提下，用一句通顺中文概括主色/辅色、纹样或徽标、整体气质风格，长度 20～30 个汉字（可略作伸缩，以通顺为优先）；
- label_zh：中文 3-5 字（最好 4 字）；
- label_en：英文 2-3 个单词（最好 2 词）。

你必须仅输出 JSON 数组，数组长度={PROMPT_COUNT}，格式：
[
  {{"prompt_zh":"...", "prompt_abstract_zh":"...", "label_zh":"...", "label_en":"..."}}
]
""".strip()


def _abstract_len_ok(s: str) -> bool:
    t = s.strip()
    n = len(t)
    return 12 <= n <= 36


def validate_items(items: list[dict]) -> bool:
    if len(items) != PROMPT_COUNT:
        return False
    zh_seen: set[str] = set()
    en_seen: set[str] = set()
    for item in items:
        if not all(k in item for k in ["prompt_zh", "prompt_abstract_zh", "label_zh", "label_en"]):
            return False
        if not _abstract_len_ok(str(item.get("prompt_abstract_zh", ""))):
            return False
        if item["label_zh"] in zh_seen or item["label_en"] in en_seen:
            return False
        zh_seen.add(item["label_zh"])
        en_seen.add(item["label_en"])
    return True


def generate_for_template(image_path: str, user_requirement: str, retry: int = 3) -> list[dict]:
    print("[Stage4] 组装请求：读取并 Base64 编码参考图（大图可能需数秒）...", flush=True)
    prompt = build_instruction(user_requirement)
    image_data_url = file_to_data_url(Path(image_path))
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": image_data_url}},
            ],
        }
    ]
    last_error = ""
    for attempt in range(1, retry + 1):
        try:
            print(
                f"[Stage4] 调用 Qwen 多模态生成 {PROMPT_COUNT} 条（第 {attempt}/{retry} 次，网络较慢时可能等待较久）...",
                flush=True,
            )
            raw = qwen_chat(messages=messages, temperature=0.7, top_p=0.85)
            print("[Stage4] 已收到模型输出，解析 JSON 并校验条数与标签唯一性...", flush=True)
            items = parse_json_block(raw)
            if validate_items(items):
                print("[Stage4] 校验通过。", flush=True)
                return items
            last_error = "输出条数或标签唯一性校验不通过。"
            print(f"[WARN] {last_error} 将重试。", flush=True)
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
            print(f"[WARN] 第 {attempt} 次异常: {type(exc).__name__}: {exc}", flush=True)
    raise RuntimeError(f"生成失败，已重试 {retry} 次: {last_error}")


def _parse_json_string_array(text: str) -> list[str]:
    t = text.strip()
    if t.startswith("```"):
        m = re.search(r"```(?:json)?\s*(.*?)```", t, flags=re.DOTALL)
        if m:
            t = m.group(1).strip()
    data = json.loads(t)
    if not isinstance(data, list):
        raise ValueError("模型输出不是 JSON 数组。")
    return [str(x) for x in data]


def build_abstract_backfill_prompt(prompts: list[str]) -> str:
    n = len(prompts)
    body = "\n".join(f"{i + 1}. {p}" for i, p in enumerate(prompts))
    return f"""
以下共 {n} 条「换服装配饰颜色/纹理/图案」的详细中文描述（可能含 T 恤、短裤等具体部位）。请为每条各写一句「与具体服装款式、品类、部位无关」的概括：须**抓住该条独有的主色/辅色与纹样或徽标气质**，避免与相邻编号写成同一种笼统气质；不要引入玻璃、水晶、透明/剔透等透明材质用语；避免「T 恤、裤子、鞋」等词；通顺；每条 20～30 个汉字（可略作伸缩以通顺为优先）。

仅输出一个 JSON 数组，长度必须={n}，元素为 {n} 个字符串，顺序与下列编号 1..{n} 一一对应。不得输出其它说明文字。

输入：
{body}
""".strip()


def backfill_abstracts_from_prompts(prompts: list[str], retry: int = 3) -> list[str]:
    if not prompts:
        return []
    ptext = build_abstract_backfill_prompt(prompts)
    messages = [{"role": "user", "content": ptext}]
    last_error = ""
    for attempt in range(1, retry + 1):
        try:
            print(
                f"[Stage4] 根据已有 prompt_zh 生成精简「与款式无关」描述（{len(prompts)} 条，第 {attempt}/{retry} 次）...",
                flush=True,
            )
            raw = qwen_chat(messages=messages, temperature=0.4, top_p=0.85)
            out = _parse_json_string_array(raw)
            if len(out) != len(prompts):
                last_error = f"返回条数 {len(out)} 与输入 {len(prompts)} 不一致。"
                print(f"[WARN] {last_error} 重试。", flush=True)
                continue
            for s in out:
                if not _abstract_len_ok(s):
                    last_error = f"某条 abstract 长度异常: {s!r}"
                    print(f"[WARN] {last_error} 重试。", flush=True)
                    break
            else:
                return out
        except Exception as exc:  # noqa: BLE001
            last_error = f"{type(exc).__name__}: {exc}"
            print(f"[WARN] 第 {attempt} 次异常: {last_error}", flush=True)
    raise RuntimeError(f"精简描述生成失败，已重试 {retry} 次: {last_error}")


def _row_abstract_filled(r: dict) -> bool:
    return bool((r.get("prompt_abstract_zh") or "").strip())


def _row_prompt_filled(r: dict) -> bool:
    return bool((r.get("prompt_zh") or "").strip())


def resolve_user_requirement(
    *,
    cli_user_requirement: str | None,
    output_root: Path,
    template_name: str,
    fashion_tag: str | None,
) -> str:
    """CLI 传入则用之；否则从该 run 的 ``pipeline_render_prefs.yml`` 读取 ``user_requirement``。"""
    cli = (cli_user_requirement or "").strip()
    if cli:
        return cli
    ft = (fashion_tag or "").strip()
    if not ft:
        print(
            "[ERROR] 未传入 --user-requirement 时必须指定 --fashion-tag，"
            "以便定位 output/stage4_10/<template>/<标签截断>/pipeline_render_prefs.yml "
            "并读取其中的 user_requirement。",
            file=sys.stderr,
        )
        sys.exit(1)
    run_dir = output_template_user_dir(
        output_root,
        template_name,
        "",
        fashion_tag=ft,
    )
    prefs = pipeline_render_prefs_path(run_dir)
    if not prefs.is_file():
        print(
            f"[ERROR] 未传入 --user-requirement 时要求已存在偏好文件（含 user_requirement）: {prefs}",
            file=sys.stderr,
        )
        sys.exit(1)
    data = load_render_prefs_dict(prefs)
    ur = (data.get("user_requirement") or "").strip()
    if not ur:
        print(
            f"[ERROR] 偏好文件中 user_requirement 为空或缺失: {prefs}\n"
            "请编辑该 yml 填写 user_requirement，或通过 --user-requirement 传入。",
            file=sys.stderr,
        )
        sys.exit(1)
    print(f"[Stage4] 未传 --user-requirement，已从 YAML 读取需求（{len(ur)} 字）: {prefs}", flush=True)
    return ur


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--user-requirement",
        default=None,
        metavar="TEXT",
        help=(
            "用户需求全文，送入多模态 prompt。可省略：此时须指定 --fashion-tag，"
            "并从 output/stage4_10/<template>/<标签截断>/pipeline_render_prefs.yml 的 "
            "user_requirement 键读取；文件不存在或该键为空则报错退出。"
        ),
    )
    parser.add_argument(
        "--fashion-tag",
        default=None,
        metavar="TAG",
        help=(
            "可选（但若省略 --user-requirement 则**必填**）。仅作索引：run 目录名 "
            "output/stage4_10/<模板>/<标签截断>/ 及 CSV 列；不送入多模态模型。"
            "省略 --user-requirement 时须靠本参数定位 pipeline_render_prefs.yml 并读取其中 user_requirement。"
            "不指定且已传 --user-requirement 时，目录名由需求截断决定。后续阶段可用本参数定位同一 run。"
        ),
    )
    parser.add_argument(
        "--template",
        required=True,
        metavar="NAME",
        help="服装模板名，须与阶段2 CSV 中 template_name 一致（即 BODY_TEMPLATE_ROOT 下子目录名）",
    )
    parser.add_argument(
        "--input-csv",
        default=str(SETTINGS.output_root / "stage2_body_template_description.csv"),
        help="阶段2输出 CSV",
    )
    args = parser.parse_args()

    want = args.template.strip()
    desc_rows = read_csv(Path(args.input_csv))
    allowed = sorted(
        {(r.get("template_name") or "").strip() for r in desc_rows if (r.get("template_name") or "").strip()}
    )
    matches = [r for r in desc_rows if (r.get("template_name") or "").strip() == want]
    if not matches:
        print(
            f"[ERROR] 服装模板「{want}」不在阶段2 CSV 已有记录中，请核对名称后重新指定 --template。\n"
            f"已有 template_name（共 {len(allowed)} 个）: {', '.join(allowed)}",
            file=sys.stderr,
        )
        sys.exit(1)

    if len(matches) > 1:
        print(f"[WARN] 阶段2 CSV 中 {want!r} 出现 {len(matches)} 行，使用首行。")
    row = matches[0]
    template_name = (row.get("template_name") or "").strip()
    image_path = row.get("image_path") or ""
    if not image_path:
        print(f"[ERROR] 阶段2 CSV 中 {template_name} 缺少 image_path。", file=sys.stderr)
        sys.exit(1)

    fashion_tag = (args.fashion_tag or "").strip() or None
    user_requirement = resolve_user_requirement(
        cli_user_requirement=args.user_requirement,
        output_root=SETTINGS.output_root,
        template_name=template_name,
        fashion_tag=fashion_tag,
    )
    run_dir = output_template_user_dir(
        SETTINGS.output_root,
        template_name,
        user_requirement,
        fashion_tag=fashion_tag,
    )
    created_prefs = ensure_initial_render_prefs_yml(
        run_dir,
        user_requirement=user_requirement,
        fashion_tag=(args.fashion_tag or "").strip(),
    )
    if created_prefs is not None:
        print(
            f"[OK] 已创建默认渲染偏好 YAML（含 user_requirement 记录；可手改 studio_tint_hex / head_object / hair_object）: "
            f"{created_prefs}",
            flush=True,
        )

    output_csv = run_dir / "stage4_fashion_prompt.csv"
    print(f"[RUN] 模板: {template_name}", flush=True)
    print(f"[RUN] 需求: {user_requirement}", flush=True)
    if fashion_tag:
        print(f"[RUN] fashion-tag: {fashion_tag}", flush=True)
    print(f"[RUN] 参考图: {image_path}", flush=True)
    print(f"[RUN] 输出 CSV: {output_csv}", flush=True)

    fieldnames = [
        "template_name",
        "user_requirement",
        "fashion_tag",
        "prompt_zh",
        "prompt_abstract_zh",
        "label_zh",
        "label_en",
        "reference_image",
    ]

    existing: list[dict] = []
    if output_csv.is_file():
        existing = read_csv(output_csv)

    need_full = (
        not existing
        or len(existing) != PROMPT_COUNT
        or not all(_row_prompt_filled(r) for r in existing)
    )

    if not need_full:
        first = existing[0]
        ft_row = (first.get("fashion_tag") or "").strip()
        mismatch = (first.get("template_name") or "").strip() != template_name
        mismatch = mismatch or (first.get("user_requirement") or "").strip() != user_requirement.strip()
        if fashion_tag and ft_row and ft_row != fashion_tag:
            mismatch = True
        if mismatch:
            print(
                "[WARN] 已有 CSV 首行与本次 --template / --user-requirement / --fashion-tag 不一致，"
                "仍按本次参数做精简补全；建议核对是否跑错目录。",
                flush=True,
            )

    if need_full:
        items = generate_for_template(image_path, user_requirement)
        new_rows: list[dict] = []
        for item in items:
            new_rows.append(
                {
                    "template_name": template_name,
                    "user_requirement": user_requirement,
                    "fashion_tag": fashion_tag or "",
                    "prompt_zh": item["prompt_zh"],
                    "prompt_abstract_zh": item["prompt_abstract_zh"],
                    "label_zh": item["label_zh"],
                    "label_en": item["label_en"],
                    "reference_image": image_path,
                }
            )
        print(f"[OK] {template_name} 多模态生成 {PROMPT_COUNT} 条（含 prompt_zh 与 prompt_abstract_zh）")
        write_csv(output_csv, new_rows, fieldnames)
        print(f"已写入: {output_csv}")
        return

    missing_idx = [i for i, r in enumerate(existing) if not _row_abstract_filled(r)]
    if not missing_idx:
        print(f"[SKIP] 已有 {PROMPT_COUNT} 条 prompt_zh 且 prompt_abstract_zh 已齐，无需调用模型。")
        return

    batch_prompts = [existing[i]["prompt_zh"] for i in missing_idx]
    filled = backfill_abstracts_from_prompts(batch_prompts)
    for j, s in zip(missing_idx, filled):
        existing[j]["prompt_abstract_zh"] = s.strip()
    for r in existing:
        r.setdefault("template_name", template_name)
        r.setdefault("user_requirement", user_requirement)
        r.setdefault("fashion_tag", fashion_tag or "")
        r.setdefault("reference_image", image_path)
    print(f"[OK] 为 {len(missing_idx)} 行补全 prompt_abstract_zh")
    write_csv(output_csv, existing, fieldnames)
    print(f"已写入: {output_csv}")


if __name__ == "__main__":
    main()

