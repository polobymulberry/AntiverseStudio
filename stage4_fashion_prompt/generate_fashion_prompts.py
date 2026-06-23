"""Stage 4: 按 fashion-tag 与 pipeline_render_prefs.yml 中的 body_templates 生成纹理 prompt CSV。"""

from __future__ import annotations

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
    parse_body_templates_from_prefs,
    pipeline_render_prefs_path,
    resolve_body_theme_requirement,
)
from common.settings import SETTINGS
from common.utils import (
    body_template_run_dir,
    fashion_tag_run_dir,
    file_to_data_url,
    parse_json_block,
    read_csv,
    write_csv,
)


def build_instruction(user_requirement: str, prompt_count: int) -> str:
    n = prompt_count
    return f"""
你的角色是一位专业的、很懂年轻人的潮流服装与 IP / 艺术主题设计师。
给这张参考图片中的服装和配饰换颜色纹理；在合适位置还可增加与主题相关的图形纹样、色块叙事（须贴合下方「用户需求描述」、**强可辨识**，作为服装表面图案，不改变裁片与廓形）。目标不是「配色沾边」，而是**未事先解释也能让人一眼猜到**是哪路 IP、哪类作品气质或哪种文化母题。
**风格阶（与参考一致）**：参考图为人偶**卡通基础版型**白模/淡色预览，输出 prompt 须引导成图保持**同一卡通阶**——略扁平、色块利落，**略偏插画/Q 版一点**；**避免**照片级写实时装、过细织纹与过强立体衣褶描写，以免成图偏离版型、且细节过密不利 3D 打印识读。

【用户需求描述】（仅写**本主题的一句话锚点**即可，例如「融入梵高绘画风格与经典名作意象」「MCU 复仇者联盟群像气质」「财神抽奖欧气梗」等；**不必**重复下文共性规则——版面约束、融合叙事、第一眼吸睛等已全部列在本提示后半段）
用户需求描述：{user_requirement}

若上述字段为空或过短，请结合本次任务仍能推断的主题气质尽力生成；并在每条中写出可辨认的主题钩子。

请生成 {n} 个有明显差异的中文 prompt，用于更换服装和配饰的颜色纹理及图案装饰；
不能改变服装和配饰的几何款式与结构；不要写织纤维商品名（如棉麻丝毛羊绒等）；侧重写清**大色块分区、纹样轮廓、符号与徽标位置**；表面质感用**卡通可读**的表述即可（如干净哑光、柔和漫反射、轻微柔光、低对比暗纹），**少写**写实微褶皱、细密织纹、牛仔猫须水洗、高清纤维走向、毛孔级皮革纹理等易引模型过度细刻的内容，避免空洞形容词堆砌。
**随身配饰与小道具（重要）**：参考图中凡属造型一部分的**包袋、挂件、腰带扣饰、护具/手套表面、手中玩偶或玩具等**，其色彩、纹样与表面质感须与主服装及「用户需求描述」**同一套主题设计语言**强绑定；**禁止**因占比小就写成与母题无关的默认灰蓝、脏白、塑料玩具感等敷衍处理。
**肤色与裸露区域（重要）**：参考图中人偶的肤色、裸露肢体为基线。所有 prompt_zh **不得**引导成图时把皮肤画得更黑、更褐、更灰或整体压暗（如「美黑」「深肤色」「泥炭色」「低调压光」「欠曝」等令肤色明显暗于参考的写法）；若须提及颈/手/前臂等裸露处，应强调**与参考图一致或略偏干净透亮**，**禁止**比参考图更暗更脏。
所有 prompt_zh 与 prompt_abstract_zh 均不得出现透明/半透明材质或元素及其比喻，例如：玻璃、水晶、亚克力、透明塑料、薄冰或冰块质感、剔透、透光、透明质、果冻胶感、水感透明层等；不写「像玻璃/像水晶」类说法；服装与配饰表面按不透明色块、印花、哑光或轻微柔光处理，**避免强烈镜面高光与照片级超清面料**；图案装饰也不要设计成透明材质观感。
**一眼可辨的强主题绑定（核心，与下文融合式并列必达）**：大众对该 IP / 动漫 / 电影 / 文化对象的**第一记忆点**往往不只颜色——要想清楚是**① 标志性服装与纹样**（条纹节奏、护甲分缝、裙摆色块、徽章几何化、制服镶边），还是**② 整体造型与剪影符号**（发型轮廓线、耳/尾剪影、体态特征抽象成织带或水印暗纹），或是**③ 专属道具、图腾、文字符号的简化形**（轮廓可辨、宜抽象化与拆解到多裁片）。每条 prompt_zh **至少落实上述路径之一**，并写清在**哪一裁片、哪一部位**以何种**形状/纹样语义**出现，使旁人**不靠解说也能大致认出**是哪条线；**禁止**整条只有「同色系氛围」「关键词配色联想」却写不出**可指认的形与纹**（例如只写红蓝运动撞色却与蜘蛛侠/美队等无任何可点名关联，视为不合格）。禁止整胸拟真剧照脸或整胸单一巨型官方 Logo；人物脸以剪影、色块分区暗示即可。
**融合式设计（禁止主题简单堆砌）**：上文主题意象必须「织进」整套服装的表面系统（分区拼色、条纹节奏、**色块明暗**、镶边织带、渐变晕染、几何分区、低对比水印式暗纹等），形成**统一的图形与配色叙事**；禁止偷懒：**通体大面积单色 + 正中央一枚巨型** logo、剪影、插画或徽章独占画面，像贴片而非服装设计。**每条 prompt_zh 须写出至少两处以上、彼此呼应**的具体表面语言——例如躯干与袖口的条纹或几何分区节奏不同、裤腿与上衣侧缝的色块或纹样走向呼应、肩线/肘贴/下摆滚边/口袋盖印花联动；主题符号宜拆解为几何纹样、镶边、侧缝织唛，融入条纹与拼色系统。**反套路**：少用复读式「胸口巨大××图案」；各条须在拼接结构、条纹宽窄、**装饰疏密与色面节奏**、冷暖对比轴上拉开差异。
**主题契合与第一眼吸睛（最重要）**：在已满足「一眼可辨的强主题绑定」前提下，每条 prompt_zh 须让读者**一眼**感到与「用户需求描述」的母题、梗或情绪**强绑定**；**描写粒度以卡通贴图为上限**（色块、镶边、清晰符号形），忌逐根纱线、微距级面料与油画堆厚式笔触。须写**具体色相与搭配**，并给出**至少一处可说清的视觉锚点**：用**具体色名 + 部位 + 形状/纹样语义**绑定当前主题（示例仅供说明写法——**须按当前主题改写**，禁止照搬）：漫威线可用红白蓝星盾弧带、反应堆同心暗纹等；节庆线可用元宝轮廓、券票条纹、灯笼剪影等；艺术线可用梵高式钴蓝旋涡、向日葵铬黄区块、**概括成平面色块与笔触形**等。**禁止**万能空话（泛泛「几何图案」「时尚好看」「清新可爱」）。**反同质化（本批共 {n} 条）**：各条须在配色轴、图形语言、装饰疏密上彼此显著不同；**一次性输出 {n} 条**时，禁止任意两条只做微调（换一两个形容词、句式雷同、构图口令几乎相同）的敷衍变种；须在**色相主导倾向**、**纹样几何语法**（宽条/细格/满版晕染/小徽标镶边等）、**留白与装饰密度**、**气质副线**（活泼/克制/复古运动/街头涂鸦等）上刻意错位，使通读全列表时**每条都有独立记忆点**。本批内所有 `label_zh` 须两两不同，所有 `label_en` 须两两不同，且各自能概括该条独有视觉重心，勿多条共用近义双语标签。
对每条 detailed prompt 同时生成：
- prompt_abstract_zh：在「不引用具体服装品类与部位（如 T 恤、背带裤、裤腿等）」的前提下，用一句通顺中文概括主色/辅色、**与主题强绑定的纹样或符号气质**、整体风格，使读者仍能感到「是哪路 IP / 文化」，长度 20～30 个汉字（可略作伸缩，以通顺为优先）；
- label_zh：中文 3-5 字（最好 4 字）；
- label_en：英文 2-3 个单词（最好 2 词）。

你必须仅输出 JSON 数组，数组长度={n}，格式：
[
  {{"prompt_zh":"...", "prompt_abstract_zh":"...", "label_zh":"...", "label_en":"..."}}
]
""".strip()


def _abstract_len_ok(s: str) -> bool:
    t = s.strip()
    n = len(t)
    return 12 <= n <= 36


def validate_items(items: list[dict], prompt_count: int) -> bool:
    if len(items) != prompt_count:
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


def validate_items_report(items: list[dict], prompt_count: int) -> str:
    """与 :func:`validate_items` 相同规则；不通过时返回可读原因（通过则返回空串）。"""
    if len(items) != prompt_count:
        return f"条数不符：期望 {prompt_count} 条，实际 {len(items)} 条"
    zh_seen: set[str] = set()
    en_seen: set[str] = set()
    for idx, item in enumerate(items, start=1):
        if not all(k in item for k in ["prompt_zh", "prompt_abstract_zh", "label_zh", "label_en"]):
            return f"第 {idx} 条缺少字段（须含 prompt_zh / prompt_abstract_zh / label_zh / label_en）"
        abs_zh = str(item.get("prompt_abstract_zh", ""))
        if not _abstract_len_ok(abs_zh):
            n = len(abs_zh.strip())
            return f"第 {idx} 条 prompt_abstract_zh 长度为 {n}，须在 12～36 字（含）之间，当前摘要：{abs_zh[:48]!r}…"
        lz = item["label_zh"]
        le = item["label_en"]
        if lz in zh_seen:
            return f"label_zh 重复：{lz!r}"
        if le in en_seen:
            return f"label_en 重复：{le!r}"
        zh_seen.add(lz)
        en_seen.add(le)
    return ""


def generate_for_template(
    image_path: str,
    user_requirement: str,
    prompt_count: int,
    *,
    retry: int = 3,
    enable_search: bool = True,
) -> list[dict]:
    print("[Stage4] 组装请求：读取并 Base64 编码参考图（大图可能需数秒）...", flush=True)
    prompt = build_instruction(user_requirement, prompt_count)
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
                f"[Stage4] 调用 Qwen 多模态生成 {prompt_count} 条（第 {attempt}/{retry} 次，网络较慢时可能等待较久）...",
                flush=True,
            )
            raw = qwen_chat(
                messages=messages,
                temperature=0.7,
                top_p=0.85,
                enable_search=enable_search,
            )
            print("[Stage4] 已收到模型输出，解析 JSON 并校验条数与标签唯一性...", flush=True)
            items = parse_json_block(raw)
            if validate_items(items, prompt_count):
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
以下共 {n} 条「换服装配饰颜色/纹理/图案」的详细中文描述（可能含 T 恤、短裤等具体部位）。请为每条各写一句「与具体服装款式、品类、部位无关」的概括：须**抓住该条独有的主色/辅色与纹样或徽标气质**，避免与相邻编号写成同一种笼统气质；不要引入玻璃、水晶、透明/剔透等透明材质用语；概括语气与该条质感一致即可，勿强行套成「只有平面胶印」式单薄描述；避免「T 恤、裤子、鞋」等词；通顺；每条 20～30 个汉字（可略作伸缩以通顺为优先）。

仅输出一个 JSON 数组，长度必须={n}，元素为 {n} 个字符串，顺序与下列编号 1..{n} 一一对应。不得输出其它说明文字。

输入：
{body}
""".strip()


def backfill_abstracts_from_prompts(
    prompts: list[str],
    retry: int = 3,
    *,
    enable_search: bool = True,
) -> list[str]:
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
            raw = qwen_chat(
                messages=messages,
                temperature=0.4,
                top_p=0.85,
                enable_search=enable_search,
            )
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
    fashion_tag: str,
    pipeline_line: str | None = None,
) -> str:
    """CLI 传入则用之；否则从 ``…/<产品线>/stage4_10/<标签>/pipeline_render_prefs.yml`` 读取。

    读取顺序：``user_requirement`` 优先；旧 YAML 仅含 ``body_requirement`` 时回退（与手办 IP / 人偶线统一）。
    ``pipeline_line`` 须与主题目录所在产品线一致；缺省则走 ``SETTINGS.pipeline_line``。
    """
    cli = (cli_user_requirement or "").strip()
    if cli:
        return cli
    ft = (fashion_tag or "").strip()
    if not ft:
        print("[ERROR] 须指定 --fashion-tag。", file=sys.stderr)
        sys.exit(1)
    prefs = pipeline_render_prefs_path(
        fashion_tag_run_dir(output_root, ft, pipeline_line=pipeline_line)
    )
    if not prefs.is_file():
        print(
            f"[ERROR] 未传入 --user-requirement 时要求已存在偏好文件（须含 user_requirement，或旧字段 body_requirement）: {prefs}",
            file=sys.stderr,
        )
        sys.exit(1)
    data = load_render_prefs_dict(prefs)
    ur = resolve_body_theme_requirement(data)
    if not ur:
        print(
            f"[ERROR] 偏好文件中 user_requirement 为空（且无旧字段 body_requirement 可回退）: {prefs}\n"
            "请填写 user_requirement，或通过 --user-requirement 传入。",
            file=sys.stderr,
        )
        sys.exit(1)
    print(f"[Stage4] 未传 --user-requirement，已从 YAML 读取服装主题需求（{len(ur)} 字）: {prefs}", flush=True)
    return ur


def _process_one_template(
    *,
    template_name: str,
    prompt_count: int,
    user_requirement: str,
    fashion_tag: str,
    image_path: str,
    desc_rows: list[dict],
    enable_search: bool = True,
    pipeline_line: str | None = None,
) -> None:
    matches = [r for r in desc_rows if (r.get("template_name") or "").strip() == template_name]
    if not matches:
        print(f"[ERROR] 模板「{template_name}」不在阶段2 CSV。", file=sys.stderr)
        sys.exit(1)
    if len(matches) > 1:
        print(f"[WARN] 阶段2 CSV 中 {template_name!r} 出现 {len(matches)} 行，使用首行。")
    row = matches[0]
    if not image_path:
        image_path = row.get("image_path") or ""
    if not image_path:
        print(f"[ERROR] 阶段2 CSV 中 {template_name} 缺少 image_path。", file=sys.stderr)
        sys.exit(1)

    run_dir = body_template_run_dir(
        SETTINGS.output_root, fashion_tag, template_name, pipeline_line=pipeline_line
    )
    output_csv = run_dir / "stage4_fashion_prompt.csv"

    print(f"[RUN] 模板: {template_name}", flush=True)
    print(f"[RUN] prompt 条数: {prompt_count}", flush=True)
    print(f"[RUN] 需求: {user_requirement}", flush=True)
    print(f"[RUN] fashion-tag: {fashion_tag}", flush=True)
    print(f"[RUN] 参考图: {image_path}", flush=True)
    print(f"[RUN] 输出 CSV: {output_csv}", flush=True)
    print(f"[RUN] DashScope enable_search: {enable_search}", flush=True)

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
        or len(existing) != prompt_count
        or not all(_row_prompt_filled(r) for r in existing)
    )

    if not need_full:
        first = existing[0]
        ft_row = (first.get("fashion_tag") or "").strip()
        mismatch = (first.get("template_name") or "").strip() != template_name
        mismatch = mismatch or (first.get("user_requirement") or "").strip() != user_requirement.strip()
        if ft_row and ft_row != fashion_tag:
            mismatch = True
        if mismatch:
            print(
                "[WARN] 已有 CSV 首行与本次参数不一致，仍按本次参数做精简补全；建议核对是否跑错目录。",
                flush=True,
            )

    if need_full:
        items = generate_for_template(
            str(image_path),
            user_requirement,
            prompt_count,
            enable_search=enable_search,
        )
        new_rows: list[dict] = []
        for item in items:
            new_rows.append(
                {
                    "template_name": template_name,
                    "user_requirement": user_requirement,
                    "fashion_tag": fashion_tag,
                    "prompt_zh": item["prompt_zh"],
                    "prompt_abstract_zh": item["prompt_abstract_zh"],
                    "label_zh": item["label_zh"],
                    "label_en": item["label_en"],
                    "reference_image": image_path,
                }
            )
        print(f"[OK] {template_name} 多模态生成 {prompt_count} 条（含 prompt_zh 与 prompt_abstract_zh）")
        write_csv(output_csv, new_rows, fieldnames)
        print(f"已写入: {output_csv}")
        return

    missing_idx = [i for i, r in enumerate(existing) if not _row_abstract_filled(r)]
    if not missing_idx:
        print(f"[SKIP] 已有 {prompt_count} 条 prompt_zh 且 prompt_abstract_zh 已齐，无需调用模型。")
        return

    batch_prompts = [existing[i]["prompt_zh"] for i in missing_idx]
    filled = backfill_abstracts_from_prompts(batch_prompts, enable_search=enable_search)
    for j, s in zip(missing_idx, filled):
        existing[j]["prompt_abstract_zh"] = s.strip()
    for r in existing:
        r.setdefault("template_name", template_name)
        r.setdefault("user_requirement", user_requirement)
        r.setdefault("fashion_tag", fashion_tag)
        r.setdefault("reference_image", image_path)
    print(f"[OK] 为 {len(missing_idx)} 行补全 prompt_abstract_zh")
    write_csv(output_csv, existing, fieldnames)
    print(f"已写入: {output_csv}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "按 output/<产品线>/stage4_10/<fashion-tag>/pipeline_render_prefs.yml 中的 body_templates "
            "对每个服装模板生成 stage4_fashion_prompt.csv。"
        ),
    )
    parser.add_argument(
        "--user-requirement",
        default=None,
        metavar="TEXT",
        help="用户需求全文；可省略并从主题根目录 pipeline_render_prefs.yml 读取 user_requirement。",
    )
    parser.add_argument(
        "--fashion-tag",
        required=True,
        metavar="TAG",
        help="必填。目录索引：output/<产品线>/stage4_10/<截断>/ ；写入 CSV；与 YAML 中 fashion_tag 一致。",
    )
    parser.add_argument(
        "--pipeline-line",
        default=None,
        metavar="NAME",
        help=(
            "output 下产品线子目录名，须与主题 YAML 所在路径一致；"
            "缺省使用 SETTINGS.pipeline_line（环境 PIPELINE_LINE）。"
            "批量脚本 batch_doll_texture_stages 会显式传入，避免与 CLI --pipeline 不一致。"
        ),
    )
    parser.add_argument(
        "--template",
        default=None,
        metavar="NAME",
        help=(
            "可选。若指定则仅处理该服装模板（须在 YAML body_templates 中）；"
            "省略则处理 YAML 中列出的全部模板。"
        ),
    )
    parser.add_argument(
        "--input-csv",
        default=str(SETTINGS.output_root / "stage2_body_template_description.csv"),
        help="阶段2输出 CSV",
    )
    parser.add_argument(
        "--disable-search",
        action="store_true",
        help=(
            "关闭 DashScope 联网搜索（默认开启 extra_body.enable_search，可能增加 Token）。"
            "若需强制触发搜索见平台文档 search_options / forced_search。"
        ),
    )
    args = parser.parse_args()

    fashion_tag = args.fashion_tag.strip()
    pline = (args.pipeline_line or "").strip() or None
    prefs_root = fashion_tag_run_dir(
        SETTINGS.output_root, fashion_tag, pipeline_line=pline
    )

    user_requirement = resolve_user_requirement(
        cli_user_requirement=args.user_requirement,
        output_root=SETTINGS.output_root,
        fashion_tag=fashion_tag,
        pipeline_line=pline,
    )

    created_prefs = ensure_initial_render_prefs_yml(
        prefs_root,
        user_requirement=user_requirement,
        fashion_tag=fashion_tag,
    )
    if created_prefs is not None:
        print(
            "[OK] 已创建默认渲染偏好 YAML（请编辑 body_templates：每项 template_name + prompt_count）: "
            f"{created_prefs}",
            flush=True,
        )

    prefs_data = load_render_prefs_dict(pipeline_render_prefs_path(prefs_root))
    pairs = parse_body_templates_from_prefs(prefs_data)
    filter_tpl = (args.template or "").strip()
    if filter_tpl:
        pairs = [(t, n) for t, n in pairs if t == filter_tpl]
        if not pairs:
            print(
                f"[ERROR] --template {filter_tpl!r} 不在 YAML body_templates 中。",
                file=sys.stderr,
            )
            sys.exit(1)
    if not pairs:
        print(
            f"[ERROR] {pipeline_render_prefs_path(prefs_root)} 中 body_templates 为空或缺失。\n"
            "请添加例如:\n"
            "  body_templates:\n"
            "    - template_name: body_65\n"
            "      prompt_count: 20\n",
            file=sys.stderr,
        )
        sys.exit(1)

    desc_rows = read_csv(Path(args.input_csv))
    allowed = sorted(
        {(r.get("template_name") or "").strip() for r in desc_rows if (r.get("template_name") or "").strip()}
    )

    for template_name, prompt_count in pairs:
        if template_name not in allowed:
            print(
                f"[ERROR] body_templates 中的「{template_name}」不在阶段2 CSV。\n"
                f"合法 template_name: {', '.join(allowed)}",
                file=sys.stderr,
            )
            sys.exit(1)
        pc = max(1, int(prompt_count))
        row0 = next(r for r in desc_rows if (r.get("template_name") or "").strip() == template_name)
        image_path = row0.get("image_path") or ""
        _process_one_template(
            template_name=template_name,
            prompt_count=pc,
            user_requirement=user_requirement,
            fashion_tag=fashion_tag,
            image_path=str(image_path),
            desc_rows=desc_rows,
            enable_search=not args.disable_search,
            pipeline_line=pline,
        )


if __name__ == "__main__":
    main()
