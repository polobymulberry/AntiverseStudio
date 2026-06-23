"""Stage 3a: 根据 Stage1 body template 预览图，生成 ``user_requirement`` 候选，并附**小红书用 7～9 字视频标题**（``video_title_zh``）。

每行含可粘贴的主题母题 + 发片用短标题。输出由 ``--run-subdir`` / ``--output-csv`` 指定；默认联网。
若提供 ``--theme-hint`` 且未显式传 ``--candidate-count``：默认**只生成 1 条**候选（一条「定名式」产品线主题 + 可延展描述，如品牌化口语「狂野NBA××」），**不会**再拆成 10 条并列子题。若仍要多条同轴变体，可显式 ``--candidate-count N``。

只跑指定模板 + 主题发散（``--theme-hint``）::

    python stage3a_body_template_theme_fit/analyze_theme_fit.py \\
      --templates body_05 --theme-hint NBA主题 --run-subdir 260513_body_05_NBA

从已有 Stage3a CSV 生成手办线主题根 YAML（不调用模型；默认写入 ``output/手办服装IP/stage4_10/``）::

    python stage3a_body_template_theme_fit/analyze_theme_fit.py \\
      --run-subdir 选题_示例命名 --auto-gen-yml
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from collections import defaultdict
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from common.llm_clients import qwen_chat
from common.pipeline_render_prefs import (
    DEFAULT_HAIR_OBJECT,
    DEFAULT_HEAD_OBJECT,
    DEFAULT_PROMPT_COUNT,
    write_render_prefs_yml,
)
from common.settings import SETTINGS
from common.studio_render_constants import STUDIO_TINT_HEX_PRESETS
from common.utils import ensure_dir, file_to_data_url, read_csv, truncate_for_path, write_csv

SUMMARY_KEY = "summary_zh"
CANDIDATES_KEY = "candidates"
DEFAULT_CANDIDATE_COUNT = 10

FIT_LABELS = ("很合适", "较合适", "一般", "勉强")

USER_REQUIREMENT_MIN_LEN = 18
USER_REQUIREMENT_MAX_LEN = 420

VIDEO_TITLE_MIN_CHARS = 7
VIDEO_TITLE_MAX_CHARS = 9

FIELDNAMES = [
    "template_name",
    "image_path",
    "variation_seed",
    "template_summary_zh",
    "candidate_index",
    "video_title_zh",
    "fit_score",
    "fit_label",
    "category",
    "user_requirement_zh",
]

STAGE3A_RUN_ROOT_NAME = "stage3a_body_template_theme_fit"
STAGE3A_CSV_BASENAME = "stage3a_body_template_theme_fit.csv"

FIT_LABEL_BEST = "很合适"
STAGE4_THEME_SUBDIR = "stage4_10"
DEFAULT_IP_PIPELINE_LINE = "手办服装IP"


def coerce_stage3a_row(r: dict[str, str]) -> dict[str, str]:
    """合并旧版列名（theme_zh / theme_fit_summary_zh 等）到当前 FIELDNAMES。"""
    ur = (r.get("user_requirement_zh") or "").strip()
    if not ur:
        tz = (r.get("theme_zh") or "").strip()
        ig = (r.get("image_ground_zh") or "").strip()
        if tz and ig:
            ur = f"{tz}。{ig}"
        elif tz:
            ur = tz
    ts = (r.get("template_summary_zh") or r.get("theme_fit_summary_zh") or "").strip()
    return {
        "template_name": (r.get("template_name") or "").strip(),
        "image_path": (r.get("image_path") or "").strip(),
        "variation_seed": (r.get("variation_seed") or "").strip(),
        "template_summary_zh": ts,
        "candidate_index": (r.get("candidate_index") or "").strip(),
        "video_title_zh": (r.get("video_title_zh") or "").strip(),
        "fit_score": (r.get("fit_score") or "").strip(),
        "fit_label": (r.get("fit_label") or "").strip(),
        "category": (r.get("category") or "").strip().lower(),
        "user_requirement_zh": ur,
    }


def resolve_output_csv(output_root: Path, *, run_subdir: str | None, output_csv: Path | None) -> Path:
    if output_csv is not None:
        return Path(output_csv).expanduser().resolve()
    if not (run_subdir or "").strip():
        print(
            "[ERROR] 须指定 --run-subdir <名称>（将写入 "
            f"output/{STAGE3A_RUN_ROOT_NAME}/<名称>/{STAGE3A_CSV_BASENAME}），"
            "或显式传入 --output-csv 完整路径。",
            file=sys.stderr,
        )
        sys.exit(2)
    sub = re.sub(r"[^\w\u4e00-\u9fff\-_.]+", "_", run_subdir.strip()).strip("._")
    if not sub:
        print("[ERROR] --run-subdir 清理后为空，请换名称。", file=sys.stderr)
        sys.exit(2)
    run_dir = (output_root / STAGE3A_RUN_ROOT_NAME / sub).resolve()
    return run_dir / STAGE3A_CSV_BASENAME


def run_auto_gen_yml_from_stage3a(
    *,
    csv_path: Path,
    output_root: Path,
    pipeline_line: str,
    overwrite_yml: bool,
    pref_prompt_count: int,
) -> None:
    """从 Stage3a CSV 筛选 ``fit_label=很合适``，写入 ``output/<产品线>/stage4_10/<截断>/pipeline_render_prefs.yml``。

    手办服装 IP 线：``user_requirement`` 取自 ``user_requirement_zh``；``body_templates`` 为当前行 ``template_name``；
    ``head_object`` / ``hair_object`` 使用仓库默认内置头/发（与空主题 YAML 一致），可用生成后手改 YAML 替换。
    ``fashion_tag`` 与目录 basename 一致，便于 ``--fashion-tag``。
    """
    csv_path = csv_path.resolve()
    if not csv_path.is_file():
        print(f"[ERROR] 未找到 Stage3a CSV: {csv_path}", file=sys.stderr)
        sys.exit(1)
    raw_rows = read_csv(csv_path)
    rows = [coerce_stage3a_row(dict(r)) for r in raw_rows]
    picked = [r for r in rows if (r.get("fit_label") or "").strip() == FIT_LABEL_BEST]
    if not picked:
        print(f"[WARN] 无 fit_label={FIT_LABEL_BEST!r} 的行，未生成任何 YAML。", flush=True)
        return

    line = (pipeline_line or "").strip() or DEFAULT_IP_PIPELINE_LINE
    base = output_root.resolve() / line / STAGE4_THEME_SUBDIR
    used_stems: set[str] = set()
    n_ok = 0
    n_prompts = max(1, int(pref_prompt_count))

    for r in picked:
        title = (r.get("video_title_zh") or "").strip()
        tmpl = (r.get("template_name") or "").strip()
        ci = (r.get("candidate_index") or "1").strip()
        ur = (r.get("user_requirement_zh") or "").strip()
        if not title or not tmpl or not ur:
            print(
                f"[SKIP] 行字段不全: video_title={title!r} template={tmpl!r} user_requirement_zh 空={not ur}",
                flush=True,
            )
            continue
        stem = truncate_for_path(f"{title}_{tmpl}_{ci}")
        if stem in used_stems:
            suf = (r.get("variation_seed") or "0").strip()[:8] or "dup"
            stem = truncate_for_path(f"{title}_{tmpl}_{ci}_{suf}")[:48]
        used_stems.add(stem)

        run_dir = ensure_dir(base / stem)
        yml_path = run_dir / "pipeline_render_prefs.yml"
        if yml_path.is_file() and not overwrite_yml:
            print(f"[SKIP] 已存在（加 --overwrite-yml 覆盖）: {yml_path}", flush=True)
            continue

        write_render_prefs_yml(
            run_dir,
            studio_tint_hex=random.choice(STUDIO_TINT_HEX_PRESETS),
            head_object=DEFAULT_HEAD_OBJECT,
            hair_object=DEFAULT_HAIR_OBJECT,
            hair_color="black",
            user_requirement=ur,
            body_requirement="",
            hair_requirement="",
            fashion_tag=stem,
            prompt_count=n_prompts,
            body_templates=[{"template_name": tmpl, "prompt_count": n_prompts}],
            preserve_keys={"video_title_zh": title},
        )
        n_ok += 1
        print(f"[OK] {yml_path}（fashion_tag={stem!r} video_title_zh={title!r} template={tmpl!r}）", flush=True)

    print(f"[DONE] 共生成 {n_ok} 个 pipeline_render_prefs.yml，根目录: {base}", flush=True)


def build_user_prompt(
    *,
    candidate_count: int,
    variation_seed: str,
    theme_hint: str,
    preamble: str = "",
    insert_before_output_format: str = "",
    summary_json_key: str | None = None,
    candidate_extra_field_names: str = "",
    core_section_override: str | None = None,
) -> str:
    """构造 Stage3a 主提示词；Stage3b 通过 ``preamble`` / ``insert_before_output_format`` / ``summary_json_key`` 等扩展复用。"""
    th = theme_hint.strip()
    sk = summary_json_key or SUMMARY_KEY
    axis_lock = ""
    if th and candidate_count == 1:
        axis_lock = f"""
【主题锁定（用户 --theme-hint：「{th}」）】
- 本轮**仅 1 条**候选：`{CANDIDATES_KEY}` 长度**恰好为 1**。把「{th}」收敛成**一条**完整的产品线/系列主题（可用有记忆点的品牌化口语式命名感，例如「狂野NBA××」一类），**禁止**在一条里假装「并列多个互不相关子选题」；延展与发散口**全部写在这唯一一条** ``user_requirement_zh`` 内。
- 允许的滑动仅限**「{th}」语义场内部**的视觉语汇、气质与符号池；**不得**跳到别的圈层/IP 宇宙；**禁止**泛化安全牌凑数。
- ``{sk}``：须**直接点题**「{th}」并点出本条定名/气质方向，**不要**像在概括多条候选那样分条列举。

"""
    elif th:
        axis_lock = f"""
【主题轴向锁定（用户 --theme-hint：「{th}」）】
- 本批 **{candidate_count}** 条候选是**同一专题下的并列方案**，不是「从提示里拆出多个互不相关的子赛道」：每一条 ``user_requirement_zh`` 与 ``video_title_zh`` 都必须让读者感到仍停留在「{th}」这一**统一母题/文化轴**上，是**同一盘棋里的不同落子**（不同切口、语气、符号侧重、时代/场景切片），供下游在同一主题下批量扩展纹理；**严禁**各条之间像「多选题拼盘」、彼此几乎无共同锚点。
- 允许的「发散」仅限：**该语义场内部**的合理滑动（例如同属「{th}」下的不同视觉钩子、不同符号实例、色温与对比、叙事配角感等），**不得**跳到与「{th}」违和或观众一眼联想到**别的圈层/别的 IP 宇宙**的题目；也**禁止**用泛化安全牌（泛泛通勤、小清新、无文化锚的「ins 风」等）凑数。
- ``{sk}``：须**直接点题**「{th}」，并概括这 {candidate_count} 条如何在该轴上各有侧重却仍**同属一条产品线级主题**，而非多个独立子主题。

"""

    diversity_tail = f"""本轮随机种子（可写入 `{sk}` 末尾）：`{variation_seed}`。
"""
    if th and candidate_count == 1:
        diversity_tail += f"""须与常见「{th}」套话拉开差距，但仍一眼落在「{th}」语义场内；**禁止**与上一轮输出复读式雷同。
"""
    elif th:
        diversity_tail += f"""请**主动错位**：仅在「{th}」这一主轴内换切口、换符号实例与措辞，避免 {candidate_count} 条同质化；**禁止**仅微调同一句；**禁止**把「错位」理解成整批改跑「{th}」之外的文化圈；**禁止**与上一轮输出复读式雷同。
"""
    else:
        diversity_tail += f"""请**主动错位**：换联想轴与措辞，避免 {candidate_count} 条同质化安全牌；**禁止**仅微调同一句。**禁止**与上一轮输出复读式雷同。
"""
    if th and candidate_count > 1:
        diversity_tail += (
            "\n（若本轮无 --theme-hint，才可把「多条支线」理解为跨多个文化圈的联想；**本轮有 theme-hint 时，"
            "「多条支线」仅指上锁语义场内的支线，不得外溢。）\n"
        )

    default_core = """【核心：一切仍须从预览图出发】
你是**非常有品位的服装与 IP 联名视觉总监**。输入图是「无头 3D 人偶」穿着一套**卡通基础版型**的渲染预览（多为白模或极淡色）。
若某题材与版型弱关联，须给较低 `fit_score`、`勉强`/`一般`，并在 **user_requirement_zh** 里诚实收窄表述（例如「谨慎尝试」「更适合轻量点缀」）。
"""
    core_block = default_core if core_section_override is None else core_section_override

    head = f"{preamble.strip()}\n\n" if preamble.strip() else ""
    mid = f"{insert_before_output_format.strip()}\n\n" if insert_before_output_format.strip() else ""

    return f"""{head}【硬性数量】`{CANDIDATES_KEY}` 数组长度**必须恰好为 {candidate_count}**，少一条或多一条均视为无效输出。

【产出形态：可直接用作 Stage4 的 user_requirement（须能撑起「一批」纹理，而非单款成稿）】
同一条 ``user_requirement`` 会用于**批量生成许多条**彼此差异大的服装纹理 prompt（如十余～数十条），共性约束在 ``generate_fashion_prompts.py`` 里已写全；这里只提供**可延展的母题/题材带**。
因此 **`user_requirement_zh` 必须写成「一片可做多套变体」的选题**，而不是只能做 1～2 张图的具体设计说明。
{axis_lock}
- **要写清**：文化圈或 IP/艺术/情绪**母题**、可沿伸的**视觉语汇**（色系轴、符号类型、风格气质），以及**与当前版型的整体气质是否合拍**（领型/裤型/礼服感等**一笔带过**即可，勿展开裁片工程细节）。若预览中可见**随身小配饰、手中玩偶/玩具、包饰挂件等**，须在 ``user_requirement_zh`` 中写明其与母题**同色同气质**的约束，**禁止**因占比小就忽略或与主服装脱节。
- **母题须具体可指认**：尽量落到**大众熟知**的影视/动画/游戏/文学/绘画或明确潮流 IP（读者能联想到**具体作品或系列名**）；**禁止**只用「某某感」「泛运动」「轻暗黑」等**说不出具体作品**的泛 IP 式套话充当整条母题（与版型弱相关时须配合低分并诚实收窄，不得用泛化描述硬凑）。
- **禁止写死单款成稿**，包括但不限于：唯一指定「胸口/左胸/袖管某处」的**具体摆位**；**唯一**主图构图；**单角色单造型**且封死不能换英雄/换名画/换子风格；把纹样**尺寸、数量、排布**写到只能按图施工的程度；「只做这一款」式口径。
- **要留发散口**（在**不违反**上文「主题轴向锁定」的前提下）：可暗示**多条仍在同一母题内的**支线或可轮换符号，让下游能自然拆成许多条不雷同的 prompt；**若本轮已给 --theme-hint，则所有支线必须落在该提示的语义场内**，不得借「支线」之名拆成多个无关子主题。
- **1～4 句**，口吻像**定一条产品线的主题方向**；**禁止** JSON 元语言、「如下图」；字数 **{USER_REQUIREMENT_MIN_LEN}～{USER_REQUIREMENT_MAX_LEN} 字**。

{core_block}
【小红书视频标题 `video_title_zh`】同一条候选还须给出发竖屏短视频用的**标题**（可作文件名/成片标题参考）：
- **长度须为 {VIDEO_TITLE_MIN_CHARS}～{VIDEO_TITLE_MAX_CHARS} 个字符（含边界）**（按 Unicode 计；以汉字为主，勿用英文单词凑长度）。
- 结合**本条母题**与同预览版型下的**服装气质**（如卫衣休闲、礼服仪式感等可从版型推断一词），让人一眼有点击欲；忌浮夸辱骂式标题党、忌违规导流话术。
- **一句内完结**，无句号书名号，无换行与空格。

【辅助字段】每条候选还须包含：
- `fit_score`：整数 **1～10**（10 表示与当前裁片+配饰气质**最合拍**）。
- `fit_label`：**很合适** / **较合适** / **一般** / **勉强**（与分数大致一致：9-10 很合适；7-8 较合适；5-6 一般；1-4 勉强）。
- `category`：英文小写标签选一：`movies` `animation` `anime` `games` `heritage` `ip` `tourism` `art` `music` `literature` `mythology` `mood` `food` `trend` `other`。

【每次执行要有明显变化】
{diversity_tail}
【热点（若已开联网）】可检索近月至当季影视、番剧、游戏、展览、时装周与社媒服饰风向；**仅保留与版型相称者**融入 user_requirement_zh；禁止编造档期票房、禁止无关八卦。
{f"\n**若已给 --theme-hint**：联网素材也须能收束进「{th}」主轴，不得借机引入与「{th}」无关的热点拼盘。" if th else ""}

{mid}【输出格式】仅输出**一个 JSON 对象**，键必须为：
`"{sk}"`（2～4 句：本轮版型侧「适合承载哪些母题」的总述，强调**可批量延展**而非单款；**不要**与某一条 user_requirement_zh 逐字重复）、
`"{CANDIDATES_KEY}"`（{candidate_count} 个对象，每个含 `user_requirement_zh`、`video_title_zh`、`fit_score`、`fit_label`、`category`{candidate_extra_field_names}）。
不要 Markdown、不要代码围栏外任何说明文字。
""".strip()


def parse_json_object(text: str) -> dict[str, object]:
    t = text.strip()
    if t.startswith("```"):
        m = re.search(r"```(?:json)?\s*(.*?)```", t, flags=re.DOTALL)
        if m:
            t = m.group(1).strip()
    data = json.loads(t)
    if not isinstance(data, dict):
        raise ValueError("模型输出不是 JSON 对象。")
    return data


def _candidate_ok(c: object) -> bool:
    if not isinstance(c, dict):
        return False
    d = c
    ur = str(d.get("user_requirement_zh") or "").strip()
    cat = str(d.get("category") or "").strip().lower()
    label = str(d.get("fit_label") or "").strip()
    if len(ur) < USER_REQUIREMENT_MIN_LEN or len(ur) > USER_REQUIREMENT_MAX_LEN:
        return False
    if label not in FIT_LABELS:
        return False
    fs = d.get("fit_score")
    if isinstance(fs, bool) or fs is None:
        return False
    try:
        fi = int(fs)
    except (TypeError, ValueError):
        return False
    if not (1 <= fi <= 10):
        return False
    allowed_cat = {
        "movies",
        "animation",
        "anime",
        "games",
        "heritage",
        "ip",
        "tourism",
        "art",
        "music",
        "literature",
        "mythology",
        "mood",
        "food",
        "trend",
        "other",
    }
    if cat not in allowed_cat:
        return False
    vt = str(d.get("video_title_zh") or "").strip()
    nvt = len(vt)
    if nvt < VIDEO_TITLE_MIN_CHARS or nvt > VIDEO_TITLE_MAX_CHARS:
        return False
    if any(ch.isspace() for ch in vt):
        return False
    return True


def validate_theme_fit(
    data: dict[str, object],
    *,
    candidate_count: int,
    summary_key: str | None = None,
) -> bool:
    sk = summary_key or SUMMARY_KEY
    if sk not in data or not str(data.get(sk) or "").strip():
        return False
    raw = data.get(CANDIDATES_KEY)
    if not isinstance(raw, list) or len(raw) != candidate_count:
        return False
    return all(_candidate_ok(x) for x in raw)


def normalize_output(
    data: dict[str, object],
    *,
    candidate_count: int,
    summary_key: str | None = None,
) -> dict[str, object]:
    sk = summary_key or SUMMARY_KEY
    summary = str(data[sk]).strip()
    raw = data[CANDIDATES_KEY]
    assert isinstance(raw, list)
    out_list: list[dict[str, object]] = []
    for c in raw:
        assert isinstance(c, dict)
        ur = str(c.get("user_requirement_zh") or "").strip()
        if len(ur) > USER_REQUIREMENT_MAX_LEN:
            ur = ur[: USER_REQUIREMENT_MAX_LEN].rstrip()
        out_list.append(
            {
                "user_requirement_zh": ur,
                "video_title_zh": str(c.get("video_title_zh") or "").strip(),
                "fit_score": int(c["fit_score"]),
                "fit_label": str(c["fit_label"]).strip(),
                "category": str(c["category"]).strip().lower(),
            }
        )
    return {sk: summary, CANDIDATES_KEY: out_list}


def build_candidate_csv_rows(
    *,
    template_name: str,
    image_path: str,
    summary_zh: str,
    variation_seed: str,
    blob: dict[str, object],
) -> list[dict[str, str]]:
    """由已校验的 ``blob`` 展开为 CSV 行（每候选一行，``user_requirement_zh`` 可直接进 YAML）。"""
    raw = blob[CANDIDATES_KEY]
    assert isinstance(raw, list)
    rows: list[dict[str, str]] = []
    for i, c in enumerate(raw, start=1):
        assert isinstance(c, dict)
        rows.append(
            {
                "template_name": template_name,
                "image_path": image_path,
                "variation_seed": variation_seed,
                "template_summary_zh": summary_zh,
                "candidate_index": str(i),
                "video_title_zh": str(c.get("video_title_zh") or "").strip(),
                "fit_score": str(int(c["fit_score"])),
                "fit_label": str(c["fit_label"]).strip(),
                "category": str(c["category"]).strip().lower(),
                "user_requirement_zh": str(c["user_requirement_zh"]).strip(),
            }
        )
    return rows


def _row_sort_key(row: dict[str, str]) -> tuple[str, int]:
    tn = (row.get("template_name") or "").strip()
    ci = (row.get("candidate_index") or "").strip()
    if ci.isdigit():
        return tn, int(ci)
    return tn, 10**9


def _row_has_candidate_body(r: dict[str, str]) -> bool:
    ur = (r.get("user_requirement_zh") or "").strip()
    if ur:
        return True
    # 旧版长表：theme_zh + image_ground_zh
    if (r.get("theme_zh") or "").strip() and (r.get("image_ground_zh") or "").strip():
        return True
    return False


def completed_templates(rows: list[dict[str, str]], *, n_cand: int) -> set[str]:
    """已跑满的 ``template_name``：带 candidate_index 的有效行数 ≥ n_cand，或旧版单行含 ``theme_fit_json``。"""
    counts: defaultdict[str, int] = defaultdict(int)
    legacy: set[str] = set()
    for r in rows:
        tn = (r.get("template_name") or "").strip()
        if not tn:
            continue
        ci = (r.get("candidate_index") or "").strip()
        if ci.isdigit() and _row_has_candidate_body(r):
            counts[tn] += 1
        elif (r.get("theme_fit_json") or "").strip():
            legacy.add(tn)
    return {t for t, c in counts.items() if c >= n_cand} | legacy


def analyze_one(
    image_path: Path,
    *,
    candidate_count: int,
    variation_seed: str,
    theme_hint: str,
    retry: int,
    enable_search: bool,
    temperature: float,
) -> tuple[str, dict[str, object]]:
    """返回 (summary_zh, 已规范化的 blob dict)。"""
    data_url = file_to_data_url(image_path)
    user_text = build_user_prompt(
        candidate_count=candidate_count,
        variation_seed=variation_seed,
        theme_hint=theme_hint,
    )
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": user_text},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        }
    ]
    last_err = ""
    for attempt in range(1, retry + 1):
        try:
            raw = qwen_chat(
                messages=messages,
                temperature=temperature,
                top_p=0.9,
                enable_search=enable_search,
            )
            obj = parse_json_object(raw)
            if validate_theme_fit(obj, candidate_count=candidate_count):
                normalized = normalize_output(obj, candidate_count=candidate_count)
                summary = str(normalized[SUMMARY_KEY]).strip()
                return summary, normalized
            last_err = f"JSON 校验未通过（须恰好 {candidate_count} 条候选且字段合法）。"
        except Exception as exc:  # noqa: BLE001
            last_err = f"{type(exc).__name__}: {exc}"
        print(f"[WARN] {image_path.name} 第 {attempt}/{retry} 次失败: {last_err}", flush=True)
    raise RuntimeError(f"分析失败: {image_path} — {last_err}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "根据 stage1 预览图生成可直接用作 pipeline user_requirement 的候选 CSV；"
            f"默认每图 {DEFAULT_CANDIDATE_COUNT} 条，须指定 --run-subdir 或 --output-csv。"
        ),
    )
    parser.add_argument(
        "--preview-dir",
        type=Path,
        default=None,
        help="预览图目录；默认使用 SETTINGS.output_root 下的 stage1_body_template_preview。",
    )
    parser.add_argument(
        "--run-subdir",
        default=None,
        metavar="NAME",
        help=(
            f"输出子目录名（位于 output/{STAGE3A_RUN_ROOT_NAME}/<NAME>/ 下，写入 "
            f"{STAGE3A_CSV_BASENAME}）。便于手动命名与检索；与 --output-csv 二选一。"
        ),
    )
    parser.add_argument(
        "--output-csv",
        type=Path,
        default=None,
        help="输出 CSV 的完整路径（与 --run-subdir 二选一）。",
    )
    parser.add_argument(
        "--auto-gen-yml",
        action="store_true",
        help=(
            "不调用模型：从本 run 的 Stage3a CSV 筛选 fit_label=很合适，"
            "写入 output/<产品线>/stage4_10/<截断>/pipeline_render_prefs.yml（默认产品线 手办服装IP）"
        ),
    )
    parser.add_argument(
        "--pipeline-line",
        default=DEFAULT_IP_PIPELINE_LINE,
        metavar="NAME",
        help=f"--auto-gen-yml 时 output 下产品线目录名，默认「{DEFAULT_IP_PIPELINE_LINE}」",
    )
    parser.add_argument(
        "--overwrite-yml",
        action="store_true",
        help="--auto-gen-yml 时若目标 pipeline_render_prefs.yml 已存在则覆盖写入",
    )
    parser.add_argument(
        "--pref-prompt-count",
        type=int,
        default=DEFAULT_PROMPT_COUNT,
        metavar="N",
        help=(
            f"--auto-gen-yml 时写入 YAML 的 prompt_count（顶层与各 body_templates）；默认 {DEFAULT_PROMPT_COUNT}"
        ),
    )
    parser.add_argument(
        "--only-template",
        default=None,
        metavar="NAME",
        help="仅处理该 template_name（与 png stem 一致）；与 --templates 互斥",
    )
    parser.add_argument(
        "--templates",
        nargs="+",
        default=None,
        metavar="NAME",
        help="只处理这些 template_name（须存在 <预览目录>/<NAME>.png）；可多个；与 --only-template 互斥",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="若输出 CSV 中该模板已有完整候选行（行数≥--candidate-count）则跳过；兼容旧版单行含 theme_fit_json。",
    )
    parser.add_argument(
        "--disable-search",
        action="store_true",
        help="关闭 DashScope 联网搜索（可省 Token；热点参考会弱）。",
    )
    parser.add_argument(
        "--retry",
        type=int,
        default=3,
        help="单张图解析失败时的最大重试次数。",
    )
    parser.add_argument(
        "--candidate-count",
        type=int,
        default=None,
        metavar="N",
        help=(
            "每套模板输出的候选条数；省略时：有 --theme-hint 则默认 1（单条定名式主题），"
            f"否则默认 {DEFAULT_CANDIDATE_COUNT}。"
        ),
    )
    parser.add_argument(
        "--theme-hint",
        default="",
        metavar="ZH",
        help="本轮中文主题/发散提示（可选），例如「偏国潮」「NBA主题」",
    )
    parser.add_argument(
        "--variation-seed",
        default=None,
        metavar="STR",
        help="变化种子字符串；省略则每次随机生成，便于多轮结果刻意错位。",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.82,
        help="采样温度，默认 0.82 以增强轮次间差异；可调低以收紧。",
    )
    args = parser.parse_args()

    out_root = SETTINGS.output_root
    preview_dir = (args.preview_dir or (out_root / "stage1_body_template_preview")).resolve()
    run_sub = (args.run_subdir or "").strip()
    out_csv_arg = Path(args.output_csv).expanduser().resolve() if args.output_csv else None
    has_run = bool(run_sub)
    has_csv = bool(out_csv_arg)
    if has_run and has_csv:
        print("[ERROR] --run-subdir 与 --output-csv 请只指定其一。", file=sys.stderr)
        sys.exit(2)
    if not has_run and not has_csv:
        print("[ERROR] 须指定 --run-subdir <名称> 或 --output-csv <路径>。", file=sys.stderr)
        sys.exit(2)

    output_csv = resolve_output_csv(out_root, run_subdir=run_sub or None, output_csv=out_csv_arg)

    if args.auto_gen_yml:
        run_auto_gen_yml_from_stage3a(
            csv_path=output_csv,
            output_root=Path(out_root).resolve(),
            pipeline_line=str(args.pipeline_line or ""),
            overwrite_yml=bool(args.overwrite_yml),
            pref_prompt_count=max(1, int(args.pref_prompt_count)),
        )
        return

    if not preview_dir.is_dir():
        print(f"[ERROR] 预览目录不存在: {preview_dir}", file=sys.stderr)
        sys.exit(1)

    tpl_list = [x.strip() for x in (args.templates or []) if x.strip()]
    only = (args.only_template or "").strip()
    if tpl_list and only:
        print("[ERROR] 请勿同时使用 --templates 与 --only-template。", file=sys.stderr)
        sys.exit(2)

    images: list[Path]
    if tpl_list:
        want = sorted(frozenset(tpl_list))
        images = []
        missing: list[str] = []
        for name in want:
            p = preview_dir / f"{name}.png"
            if p.is_file():
                images.append(p)
            else:
                missing.append(name)
        for m in missing:
            print(f"[WARN] 无预览图，跳过: {preview_dir / f'{m}.png'}", flush=True)
        if not images:
            print("[ERROR] --templates 中无任何可用预览图。", file=sys.stderr)
            sys.exit(1)
    elif only:
        p = preview_dir / f"{only}.png"
        if not p.is_file():
            print(f"[ERROR] 未找到预览图: {p}", file=sys.stderr)
            sys.exit(1)
        images = [p]
    else:
        images = sorted(preview_dir.glob("*.png"))

    existing_rows: list[dict[str, str]] = []
    if output_csv.is_file():
        existing_rows = [coerce_stage3a_row(dict(r)) for r in read_csv(output_csv)]

    ensure_dir(output_csv.parent)
    print(f"[RUN] 本次输出目录: {output_csv.parent}", flush=True)
    print(f"[RUN] 输出 CSV: {output_csv}", flush=True)

    seed = (args.variation_seed or "").strip()
    if not seed:
        seed = f"auto-{random.randint(10**9, 10**10 - 1)}"
    print(f"[RUN] 变化种子: {seed}", flush=True)
    thint = str(args.theme_hint or "").strip()
    if thint:
        print(f"[RUN] 主题提示: {thint}", flush=True)

    if args.candidate_count is None:
        n_cand = 1 if thint else DEFAULT_CANDIDATE_COUNT
    else:
        n_cand = max(1, int(args.candidate_count))
    print(f"[RUN] 每模板候选条数: {n_cand}", flush=True)
    temp = float(args.temperature)
    if not (0.0 <= temp <= 2.0):
        print("[ERROR] --temperature 建议在 0～2 之间。", file=sys.stderr)
        sys.exit(2)

    done = completed_templates(existing_rows, n_cand=n_cand) if args.resume else set()

    all_rows: list[dict[str, str]] = list(existing_rows)

    enable_search = not args.disable_search
    for image_path in images:
        template_name = image_path.stem
        if template_name in done:
            print(f"[SKIP] {template_name}（已有完整 {n_cand} 条或旧版结果）", flush=True)
            continue
        print(f"[RUN] {template_name} …", flush=True)
        summary, blob = analyze_one(
            image_path,
            candidate_count=n_cand,
            variation_seed=seed,
            theme_hint=thint,
            retry=max(1, int(args.retry)),
            enable_search=enable_search,
            temperature=temp,
        )
        sum0 = str(blob.get(SUMMARY_KEY) or "").strip()
        if seed and seed not in sum0:
            sum1 = f"{sum0}（变化种子：{seed}）"
            blob[SUMMARY_KEY] = sum1
            summary = sum1
        new_rows = build_candidate_csv_rows(
            template_name=template_name,
            image_path=str(image_path),
            summary_zh=summary,
            variation_seed=seed,
            blob=blob,
        )
        all_rows = [r for r in all_rows if (r.get("template_name") or "").strip() != template_name]
        all_rows.extend(new_rows)
        all_rows.sort(key=_row_sort_key)
        write_csv(output_csv, all_rows, FIELDNAMES)
        print(f"[OK] {template_name} -> {output_csv}（{len(new_rows)} 行）", flush=True)

    if not images:
        print("[WARN] 未找到任何 *.png 预览图。", flush=True)


if __name__ == "__main__":
    main()
