"""Stage 3b：真人头像 × 服装模板 × 发型预览，生成服装主题 ``user_requirement``，并挑选 ``hair_object`` + ``hair_color``（卡通人偶线）。

默认**每张人脸**输出 **5** 条互斥选题行（``--themes-per-face``）；单条 ``user_requirement_zh`` 内默认可延展分支为 **1**（``--style-branches-per-theme``）。``batch_summary_zh`` 为整脸总述，**勿**写与行数对齐的「N 大母题」清单。弃用参数 ``--candidate-count`` 仍可用，等同 ``--themes-per-face``。

头发**不再**走新纹理生成链路：下游 Stage11/12 使用 solid 发型 mesh + ``common.hair_assets.HAIR_COLORS`` 中的发色键；**发色键由流水线根据参考图顶部区域估计 RGB，再与 ``HAIR_COLORS`` 各键的 hex 最近邻选定**，与服装母题无关。

输入目录默认 ``resource/real_head_120k_selected``（可用 ``--photo-dir`` 覆盖）；文件名须包含 6 位 ``real_head_id``。
服装候选列表来自 ``output/stage1_body_template_preview/*.png``（与 ``OUTPUT_ROOT`` 一致，不按 ``PIPELINE_LINE`` 分目录）；
发型候选来自 ``resource/blender/solid_hair_preview/hair_style/*.png``。

输出：``<OUTPUT_ROOT>/stage3b_body_and_hair_template_theme_fit/<run-subdir>/stage3b_body_and_hair_template_theme_fit.csv``
（与服装预览相同，**不**写在 ``output/<PIPELINE_LINE>/`` 下）。

**每处理完一张真人图即追加写入 CSV**（不必等全部跑完）；默认 ``--workers=4`` 多线程并发，**仅当该行数据已 flush 追加到 CSV 后**该线程才领取下一张脸。中断后可加 ``--resume`` 跳过 CSV 里已有 ``real_head_id`` 的照片。

若 ``--run-subdir`` 对应目录下 **已有 CSV** 且未加 ``--resume`` / ``--overwrite``，会报错退出；``--overwrite`` 会先删除该子目录再重跑。``--auto-gen-yml``：从该子目录 CSV 中筛选 ``fit_label=很合适`` 的行，为每条生成
``output/<PIPELINE_LINE>/stage4_10/<截断标题>/pipeline_render_prefs.yml``（默认 ``PIPELINE_LINE=卡通人偶定制``），与 Stage4 及后续阶段共用同一主题根目录；YAML 仅写 ``user_requirement``（与手办 IP 线字段一致；须覆盖随身小配饰、手中玩偶/玩具等，与母题同色同气质），并写 ``hair_object`` / ``hair_color`` / ``head_object``；``prompt_count`` 对卡通人偶线**默认为 1**，可用 ``--pref-prompt-count`` 覆盖。

**与 Stage3a 的关系**：服装新纹理的 ``user_requirement_zh`` / ``video_title_zh`` / 评分与 ``category`` 的**提示词与校验**与 ``stage3a_body_template_theme_fit/analyze_theme_fit.py`` **共用**（``build_user_prompt``）；Stage3b 仅增加真人脸主图、``body_template_name`` / ``hair_style_id`` / ``hair_color`` 选择与总述键名 ``batch_summary_zh``（等同 Stage3a 的 ``summary_zh``）。

依赖 DashScope 多模态；默认联网。"""

from __future__ import annotations

import argparse
import csv
import random
import re
import shutil
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from common.llm_clients import qwen_chat
from common.hair_assets import hair_color_key_from_reference_photo, list_hair_color_names
from common.pipeline_render_prefs import write_render_prefs_yml
from common.settings import SETTINGS
from common.studio_render_constants import STUDIO_TINT_HEX_PRESETS
from common.utils import ensure_dir, file_to_data_url, read_csv, truncate_for_path
from stage3a_body_template_theme_fit.analyze_theme_fit import (
    CANDIDATES_KEY,
    SUMMARY_KEY,
    USER_REQUIREMENT_MAX_LEN,
    build_user_prompt,
    parse_json_object,
    validate_theme_fit,
)

STAGE3B_SUMMARY_KEY = "batch_summary_zh"

RUN_ROOT_NAME = "stage3b_body_and_hair_template_theme_fit"
CSV_NAME = "stage3b_body_and_hair_template_theme_fit.csv"

FIELDNAMES = [
    "real_head_id",
    "photo_path",
    "body_template_name",
    "hair_style_id",
    "hair_color",
    "candidate_index",
    "video_title_zh",
    "fit_score",
    "fit_label",
    "category",
    "user_requirement_zh",
    "variation_seed",
    "batch_summary_zh",
]

_VALID_HAIR_COLORS = frozenset(list_hair_color_names())


def normalize_hair_color_key(raw: str) -> str:
    k = (raw or "").strip().lower().replace(" ", "_")
    return k if k in _VALID_HAIR_COLORS else "black"


def coerce_stage3b_row(raw: dict[str, str]) -> dict[str, str]:
    """兼容旧 CSV 列名（body_requirement_zh / 缺 hair_color）。"""
    base = {fn: (raw.get(fn) or "").strip() for fn in FIELDNAMES}
    if not base["user_requirement_zh"]:
        base["user_requirement_zh"] = (raw.get("body_requirement_zh") or "").strip()
    if not base["hair_color"]:
        base["hair_color"] = normalize_hair_color_key(raw.get("hair_color") or "black")
    else:
        base["hair_color"] = normalize_hair_color_key(base["hair_color"])
    return base

_ID_RE = re.compile(r"(\d{6})")

FIT_LABEL_BEST = "很合适"
STAGE4_THEME_SUBDIR = "stage4_10"
DEFAULT_DOLL_PIPELINE_LINE = "卡通人偶定制"
# 卡通人偶线 --auto-gen-yml 写入 YAML 的 Stage4 条数：主题已在 Stage3b 写细，默认每模板仅 1 条扩展（手办 IP 仍可在自建 YAML 中用更大 prompt_count）。
DOLL_PREF_PROMPT_COUNT = 1


def run_auto_gen_yml(
    *,
    run_subdir: str,
    output_root: Path,
    pipeline_line: str,
    overwrite_yml: bool,
    pref_prompt_count: int,
) -> None:
    """从 Stage3b CSV 筛选「很合适」，写入 ``output/<产品线>/stage4_10/<截断标题_真人id>/pipeline_render_prefs.yml``。

    YAML 中 ``fashion_tag`` 与目录名一致，便于下游 ``--fashion-tag`` 唯一对应一条选题。
    ``pref_prompt_count`` 写入顶层 ``prompt_count`` 与各 ``body_templates[].prompt_count``（卡通人偶线默认 1）。
    """
    csv_path = output_root.resolve() / RUN_ROOT_NAME / run_subdir.strip() / CSV_NAME
    if not csv_path.is_file():
        print(f"[ERROR] 未找到 Stage3b CSV: {csv_path}", file=sys.stderr)
        sys.exit(1)
    rows = [coerce_stage3b_row(dict(r)) for r in read_csv(csv_path)]
    picked = [r for r in rows if (r.get("fit_label") or "").strip() == FIT_LABEL_BEST]
    if not picked:
        print(f"[WARN] 无 fit_label={FIT_LABEL_BEST!r} 的行，未生成任何 YAML。", flush=True)
        return

    line = (pipeline_line or "").strip() or DEFAULT_DOLL_PIPELINE_LINE
    base = output_root.resolve() / line / STAGE4_THEME_SUBDIR
    used_stems: set[str] = set()
    n_ok = 0
    for r in picked:
        title = (r.get("video_title_zh") or "").strip()
        body_t = (r.get("body_template_name") or "").strip()
        hair_id = (r.get("hair_style_id") or "").strip()
        rid_raw = (r.get("real_head_id") or "").strip()
        user_req = (r.get("user_requirement_zh") or "").strip()
        hair_color = (r.get("hair_color") or "").strip()
        if not title or not body_t or not hair_id or not rid_raw or not user_req:
            print(f"[SKIP] 行字段不全: video_title={title!r} body={body_t!r} hair={hair_id!r}", flush=True)
            continue
        hair_color = normalize_hair_color_key(hair_color)
        rid = rid_raw.zfill(6) if rid_raw.isdigit() else rid_raw
        stem = truncate_for_path(f"{title}_{rid}")
        if stem in used_stems:
            suf = (r.get("candidate_index") or "0").strip()
            stem = truncate_for_path(f"{title}_{rid}_{suf}")[:48]
        used_stems.add(stem)

        n_prompts = max(1, int(pref_prompt_count))

        run_dir = ensure_dir(base / stem)
        yml_path = run_dir / "pipeline_render_prefs.yml"
        if yml_path.is_file() and not overwrite_yml:
            print(f"[SKIP] 已存在（加 --overwrite-yml 覆盖）: {yml_path}", flush=True)
            continue

        # fashion_tag 与目录 stem 一致，避免同一 video_title_zh、不同真人 id 时 --fashion-tag 冲突。
        write_render_prefs_yml(
            run_dir,
            studio_tint_hex=random.choice(STUDIO_TINT_HEX_PRESETS),
            head_object=rid,
            hair_object=hair_id,
            hair_color=hair_color,
            user_requirement=user_req,
            body_requirement="",
            hair_requirement="",
            fashion_tag=stem,
            prompt_count=n_prompts,
            body_templates=[{"template_name": body_t, "prompt_count": n_prompts}],
            preserve_keys={"video_title_zh": title},
        )
        n_ok += 1
        print(f"[OK] {yml_path}（fashion_tag={stem!r} video_title_zh={title!r}）", flush=True)

    print(f"[DONE] 共生成 {n_ok} 个 pipeline_render_prefs.yml，根目录: {base}", flush=True)


def existing_real_head_ids(csv_path: Path) -> set[str]:
    if not csv_path.is_file():
        return set()
    return {
        (r.get("real_head_id") or "").strip()
        for r in read_csv(csv_path)
        if (r.get("real_head_id") or "").strip()
    }


def append_rows_to_csv(csv_path: Path, rows: list[dict[str, str]]) -> None:
    """追加写入 UTF-8；首写自动带表头。"""
    if not rows:
        return
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not csv_path.is_file()
    with csv_path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        if new_file:
            writer.writeheader()
        for row in rows:
            writer.writerow({k: (row.get(k) or "") for k in FIELDNAMES})
        f.flush()


def extract_real_head_id(path: Path) -> str:
    m = _ID_RE.search(path.stem)
    if not m:
        m = _ID_RE.search(path.parent.name)
    if not m:
        return ""
    return m.group(1)


def list_body_template_names() -> list[str]:
    """与 Stage1 默认输出一致：``<OUTPUT_ROOT>/stage1_body_template_preview``（手办线/人偶线共用同一批预览图）。"""
    prev_dir = Path(SETTINGS.output_root).resolve() / "stage1_body_template_preview"
    if not prev_dir.is_dir():
        return []
    return sorted({p.stem for p in prev_dir.glob("*.png") if p.is_file()})


def list_hair_style_names() -> list[str]:
    d = _REPO_ROOT / "resource" / "blender" / "solid_hair_preview" / "hair_style"
    if not d.is_dir():
        return []
    return sorted({p.stem for p in d.glob("*.png") if p.is_file()})


def _style_branch_block(*, style_branches_per_theme: int, themes_per_face: int) -> str:
    k = max(1, int(style_branches_per_theme))
    t = max(1, int(themes_per_face))
    if k == 1:
        return (
            "**「user_requirement_zh」条内分支（与行数解耦）**：**每条**正文只服务**本行这一条**候选的「单一」服装纹理母题轴，供 Stage4 在同一轴上做批量变体。"
            "**禁止**在正文里写「共五种风格」「本次 N 套并列方案」「第一…第二…第五…」等把**本轮候选总行数**或**任意整数**误当成「本条内含多个平级子选题」的口吻；"
            "**禁止**把多行 CSV 才会承载的多个互不相关母题，硬塞进一条里枚举。"
        )
    return (
        f"**「user_requirement_zh」条内分支（与行数解耦）**：在**仍属本条同一母题**的前提下，正文可用 **恰好 {k} 个**短分句（建议中文分号隔开），"
        f"各给一个体面差异化切口（如配色副线、纹样侧重、气质切片），方便下游拉纹理差异。"
        f"**仍禁止**出现「共 {t} 个子风格」「本条含 {t} 套方案」等把 **候选行数（{t}）** 与 **条内分句数（{k}）** 混为一谈的措辞；"
        "**禁止**「五选一套餐」式罗列多个互不相关母题。"
    )


def _build_stage3b_face_prompt(
    *,
    themes_per_face: int,
    style_branches_per_theme: int,
    variation_seed: str,
    body_names: list[str],
    hair_names: list[str],
    theme_hint: str,
    locked_hair_color: str,
) -> str:
    """Stage3a ``build_user_prompt`` + 真人脸 / 模板列表 / 发型发色 / 条内分支说明。"""
    t = max(1, int(themes_per_face))
    bodies = ", ".join(body_names[:80])
    hairs = ", ".join(hair_names[:80])
    color_keys = ", ".join(sorted(list_hair_color_names()))
    branch = _style_branch_block(style_branches_per_theme=style_branches_per_theme, themes_per_face=t)
    preamble = f"""你是卡通人偶线与真人参考的**成片选题总监**。
本条消息的**主图像为真人面部参考**；须输出长度恰好为 **{t}** 的 ``{CANDIDATES_KEY}`` 数组（**{t}** 行互斥选题），各行须分别从下文【可选服装模板名】【可选发型 id】**原样拷贝** ``body_template_name``、``hair_style_id``，并给出合法 ``hair_color``（见英文键表）。
**服装新纹理**相关：``user_requirement_zh``、``video_title_zh``、``fit_score``、``fit_label``、``category`` 的写作与长度/标签规则**与同仓库 Stage3a**（``stage3a_body_template_theme_fit/analyze_theme_fit.build_user_prompt``）**完全一致**；本轮 JSON 总述键名为 ``{STAGE3B_SUMMARY_KEY}``（**语义等同于** Stage3a 的 ``{SUMMARY_KEY}``，勿写进 ``{SUMMARY_KEY}`` 以免键名不一致）。"""
    insert = f"""{branch}

【Stage3b 独有：发型与发色】
- **禁忌组合**：幼儿脸配重度恐怖血溅、明显女童配硬派球星主题等须避开；服装与发型须与人物气质、年龄段与观感性别大致合拍。
- **「hair_style_id」**：必须从【可选发型 id】**原样拷贝**。**款式相似度**：在列表内优先选与真人参考图**整体发型轮廓与观感最相近**的一项（长短层次、刘海有无、扎发/披发等大类），使后续卡通头套几何尽量贴近真人；并与面部气质、本条服装母题**不冲突**。若列表中确无相近款，再选气质最稳、最不违和的一项。
- **「hair_color」**：**每一行**须填且仅允许填 **`{locked_hair_color}`**（小写英文键，与下列合法键之一完全一致）：{color_keys}
  **发色来源**：已由流水线根据参考图**上方发区**估计 RGB，再与上表各键对应 **hex**（见 ``common.hair_assets.HAIR_COLORS``）做最近邻得到 **`{locked_hair_color}`**；**禁止**为配合服装母题改选其它键或写 hex 字面量。
- **禁止**在 JSON 写刘海/分缝/编发名等发型款式细纲（几何已由 hair_style_id 固定）。

【可选服装模板名】（取自文件名）：{bodies}

【可选发型 id】（取自文件名）：{hairs}

**「{STAGE3B_SUMMARY_KEY}」写作（与 Stage3a 总述职责一致）**：
- 2～4 句；强调本轮版型侧母题如何**可批量延展**；**不要**与任一条 ``user_requirement_zh`` 逐字重复。
- **禁止**写「五/四…大母题」「足球、赛车…共 {t} 项」等**与本批候选行数 {t} 逐项对齐的母题清单**；若写覆盖面，只用笼统说法，**不**与行数对齐枚举。

"""
    core_override = f"""【核心：服装母题须与所选模板版型合拍（与 Stage3a 判据一致）】
你是**非常有品位的服装与 IP 联名视觉总监**。本条消息主图是**真人面部**；每条候选的 ``body_template_name`` 须取自上文【可选服装模板名】且**原样拷贝**，对应 Stage1 同名的无头 3D **卡通基础版型**白模预览（与 Stage3a 单模板输入为**同一资源**）。撰写 ``user_requirement_zh`` 时须**针对该模板版型**斟酌题材强度、纹样留白与裁片气质——与 Stage3a「从预览图出发」**等价**：若题材与所选 ``body_template_name`` 版型轮廓/气质弱关联，须给较低 ``fit_score``、``勉强``/``一般``，并在 ``user_requirement_zh`` 里诚实收窄表述（例如「谨慎尝试」「更适合轻量点缀」）。
每条服装纹理母题应锚在**大众熟知、可直呼其名或强指认**的具体对象上：知名影视、动画、游戏、文学名篇、绘画/艺术史或同等量级的潮流 IP 等；**禁止**「某某感」「泛运动/泛科幻」「那年很红的网游感」等**说不出具体作品/系列名**的笼统「IP 式」空话。与版型弱绑定时须降分并收窄，不得以泛化描述凑数。
"""
    return build_user_prompt(
        candidate_count=t,
        variation_seed=variation_seed,
        theme_hint=theme_hint,
        preamble=preamble,
        insert_before_output_format=insert,
        summary_json_key=STAGE3B_SUMMARY_KEY,
        candidate_extra_field_names="、`body_template_name`、`hair_style_id`、`hair_color`",
        core_section_override=core_override,
    )


def _validate_3b_list_refs(
    blob: dict[str, object],
    *,
    body_allow: frozenset[str],
    hair_allow: frozenset[str],
) -> str | None:
    raw = blob.get(CANDIDATES_KEY)
    if not isinstance(raw, list):
        return "candidates 非数组"
    for i, c in enumerate(raw, start=1):
        if not isinstance(c, dict):
            return f"candidates[{i}] 非对象"
        bt = str(c.get("body_template_name") or "").strip()
        hid = str(c.get("hair_style_id") or "").strip()
        hc_raw = str(c.get("hair_color") or "").strip()
        if bt not in body_allow:
            return f"candidates[{i}] body_template_name 不在列表: {bt!r}"
        if hid not in hair_allow:
            return f"candidates[{i}] hair_style_id 不在列表: {hid!r}"
        hc_key = hc_raw.lower().replace(" ", "_")
        if hc_key not in _VALID_HAIR_COLORS:
            return f"candidates[{i}] hair_color 非法（须为 HAIR_COLORS 键之一）: {hc_raw!r}"
    return None


def analyze_one_face(
    photo: Path,
    body_names: list[str],
    hair_names: list[str],
    themes_per_face: int,
    style_branches_per_theme: int,
    variation_seed: str,
    theme_hint: str,
    retry: int,
) -> dict[str, object]:
    locked_hair = hair_color_key_from_reference_photo(photo)
    print(
        f"[RUN] {photo.name} 发色键（参考图估计→HAIR_COLORS 最近邻）: {locked_hair}",
        flush=True,
    )
    prompt = _build_stage3b_face_prompt(
        themes_per_face=themes_per_face,
        style_branches_per_theme=style_branches_per_theme,
        variation_seed=variation_seed,
        body_names=body_names,
        hair_names=hair_names,
        theme_hint=theme_hint,
        locked_hair_color=locked_hair,
    )
    url = file_to_data_url(photo)
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": url}},
            ],
        }
    ]
    body_allow = frozenset(body_names)
    hair_allow = frozenset(hair_names)
    n = max(1, int(themes_per_face))
    max_retry = max(1, int(retry))
    last_err = ""
    for attempt in range(1, max_retry + 1):
        raw = qwen_chat(messages=messages, temperature=0.82, top_p=0.9, enable_search=True)
        try:
            obj = parse_json_object(raw)
        except Exception as exc:  # noqa: BLE001
            last_err = f"{type(exc).__name__}: {exc}"
            print(f"[WARN] {photo.name} 第 {attempt}/{max_retry} 次 JSON 解析失败: {last_err}", flush=True)
            continue
        if SUMMARY_KEY in obj and STAGE3B_SUMMARY_KEY not in obj:
            obj[STAGE3B_SUMMARY_KEY] = obj.pop(SUMMARY_KEY)
        if not validate_theme_fit(obj, candidate_count=n, summary_key=STAGE3B_SUMMARY_KEY):
            last_err = "Stage3a 等价校验未通过（batch_summary_zh / candidates 长度 / user_requirement 与标题等）"
            print(f"[WARN] {photo.name} 第 {attempt}/{max_retry} 次: {last_err}", flush=True)
            continue
        raw_pre = obj.get(CANDIDATES_KEY)
        if isinstance(raw_pre, list):
            for c in raw_pre:
                if isinstance(c, dict):
                    c["hair_color"] = locked_hair
        list_err = _validate_3b_list_refs(obj, body_allow=body_allow, hair_allow=hair_allow)
        if list_err:
            last_err = list_err
            print(f"[WARN] {photo.name} 第 {attempt}/{max_retry} 次: {list_err}", flush=True)
            continue
        raw_c = obj[CANDIDATES_KEY]
        assert isinstance(raw_c, list)
        for c in raw_c:
            if isinstance(c, dict):
                ur = str(c.get("user_requirement_zh") or "").strip()
                if len(ur) > USER_REQUIREMENT_MAX_LEN:
                    c["user_requirement_zh"] = ur[:USER_REQUIREMENT_MAX_LEN].rstrip()
        return obj
    raise RuntimeError(f"分析失败: {photo} — {last_err}")


def _build_batch_rows_from_blob(
    photo: Path,
    rid: str,
    blob: dict[str, object],
    *,
    seed: str,
    n_themes: int,
) -> tuple[list[dict[str, str]], str]:
    """将模型返回转为待写入 CSV 的行。第二项为非空时表示不应落盘。"""
    summary = str(blob.get(STAGE3B_SUMMARY_KEY) or "").strip()
    raw_c = blob.get(CANDIDATES_KEY)
    if not isinstance(raw_c, list):
        return [], "candidates 缺失或类型错误"
    if len(raw_c) != n_themes:
        return [], f"candidates 长度 {len(raw_c)} 须为 {n_themes}"
    batch_rows: list[dict[str, str]] = []
    for i, c in enumerate(raw_c, start=1):
        if not isinstance(c, dict):
            continue
        batch_rows.append(
            {
                "real_head_id": rid,
                "photo_path": str(photo),
                "body_template_name": str(c.get("body_template_name") or "").strip(),
                "hair_style_id": str(c.get("hair_style_id") or "").strip(),
                "hair_color": normalize_hair_color_key(
                    str(c.get("hair_color") or c.get("hair_color_key") or "")
                ),
                "candidate_index": str(i),
                "video_title_zh": str(c.get("video_title_zh") or "").strip(),
                "fit_score": str(c.get("fit_score") or "").strip(),
                "fit_label": str(c.get("fit_label") or "").strip(),
                "category": str(c.get("category") or "").strip().lower(),
                "user_requirement_zh": str(
                    c.get("user_requirement_zh") or c.get("body_requirement_zh") or ""
                ).strip(),
                "variation_seed": seed,
                "batch_summary_zh": summary,
            }
        )
    return batch_rows, ""


def _analyze_append_one_job(
    photo: Path,
    rid: str,
    *,
    out_csv: Path,
    bodies: list[str],
    hairs: list[str],
    n_themes: int,
    n_branches: int,
    seed: str,
    theme_hint: str,
    retry: int,
    n_jobs: int,
    csv_lock: threading.Lock,
    done_ids: set[str],
    stats: list[int],
) -> None:
    """调用模型、校验行、持锁追加 CSV 并打印进度；仅当写入完成后本任务才结束。"""
    print(f"[RUN] {photo.name} id={rid} …", flush=True)
    try:
        blob = analyze_one_face(
            photo,
            bodies,
            hairs,
            n_themes,
            n_branches,
            seed,
            theme_hint,
            retry=retry,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] id={rid} 调用失败: {exc}", file=sys.stderr, flush=True)
        return
    batch_rows, err = _build_batch_rows_from_blob(photo, rid, blob, seed=seed, n_themes=n_themes)
    if err:
        print(f"[ERROR] id={rid} {err}: {photo}", file=sys.stderr, flush=True)
        return
    with csv_lock:
        append_rows_to_csv(out_csv, batch_rows)
        done_ids.add(rid)
        stats[0] += 1
        stats[1] += len(batch_rows)
        completed = stats[0]
        rows_total = stats[1]
    print(
        f"[PROGRESS] {completed}/{n_jobs} 已落盘 id={rid} +{len(batch_rows)} 行"
        f"（本进程累计追加 {rows_total} 行） -> {out_csv}",
        flush=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Stage3b 服装+发型母题候选")
    parser.add_argument(
        "--photo-dir",
        default=str(_REPO_ROOT / "resource" / "real_head_120k_selected"),
        help="真人照片目录",
    )
    parser.add_argument("--run-subdir", required=True, help="输出子目录名（与 Stage3a 的 --run-subdir 用法相同）")
    parser.add_argument(
        "--themes-per-face",
        type=int,
        default=5,
        metavar="N",
        help="每张真人脸输出的互斥选题行数（JSON candidates 长度；默认 5）",
    )
    parser.add_argument(
        "--style-branches-per-theme",
        type=int,
        default=1,
        metavar="K",
        help=(
            "单条 user_requirement_zh 内允许的「同一母题下」体面差异化切口数（分号短分句）；"
            "默认 1 即禁止在一条里堆多个平级子选题。与 --themes-per-face（CSV 行数）无关；"
            "亦不约束 batch_summary_zh（总述禁止「与行数对齐的 N 大母题」清单，见系统提示）"
        ),
    )
    parser.add_argument(
        "--candidate-count",
        type=int,
        default=None,
        metavar="N",
        help="已弃用：等同 --themes-per-face；若传入则覆盖 --themes-per-face 并打印告警",
    )
    parser.add_argument("--theme-hint", default="", help="本轮中文主题/发散提示（可选）")
    parser.add_argument("--variation-seed", default="")
    parser.add_argument("--retry", type=int, default=3)
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        metavar="N",
        help="并行处理真人脸上限；每张须在成功追加写入 CSV 后该 worker 才领取下一张（默认 4）",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="若 CSV 已存在：跳过其中已有 real_head_id 的真人图，仅补未写入的（与增量落盘配合断点续跑）",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="若该 run 子目录已存在且已有 CSV：先删除整个子目录再重跑（与 --resume 二选一更稳妥；二者同时出现时以 --overwrite 为准）",
    )
    parser.add_argument(
        "--auto-gen-yml",
        action="store_true",
        help=(
            "不调用模型；从本 run 的 stage3b CSV 读取 fit_label=很合适 的行，"
            "生成到 output/<PIPELINE_LINE>/stage4_10/<截断目录>/pipeline_render_prefs.yml（默认产品线「卡通人偶定制」）"
        ),
    )
    parser.add_argument(
        "--pipeline-line",
        default=DEFAULT_DOLL_PIPELINE_LINE,
        metavar="NAME",
        help=f"--auto-gen-yml 时写入路径所用的产品线目录名，默认「{DEFAULT_DOLL_PIPELINE_LINE}」",
    )
    parser.add_argument(
        "--overwrite-yml",
        action="store_true",
        help="--auto-gen-yml 时若目标 pipeline_render_prefs.yml 已存在则覆盖写入",
    )
    parser.add_argument(
        "--pref-prompt-count",
        type=int,
        default=DOLL_PREF_PROMPT_COUNT,
        metavar="N",
        help=(
            f"--auto-gen-yml 时写入 YAML 的 prompt_count（顶层与各 body_templates 项；"
            f"卡通人偶线默认 {DOLL_PREF_PROMPT_COUNT}，因主题已在 Stage3b 细化；手办式多扩展可改大，如 20）"
        ),
    )
    args = parser.parse_args()

    out_root = Path(SETTINGS.output_root).resolve()
    run_sub = args.run_subdir.strip()
    out_dir = out_root / RUN_ROOT_NAME / run_sub
    out_csv = out_dir / CSV_NAME

    if args.auto_gen_yml:
        run_auto_gen_yml(
            run_subdir=run_sub,
            output_root=out_root,
            pipeline_line=args.pipeline_line,
            overwrite_yml=bool(args.overwrite_yml),
            pref_prompt_count=int(args.pref_prompt_count),
        )
        return

    if args.overwrite and args.resume:
        print("[ERROR] 请只指定 --overwrite 或 --resume 其一。", file=sys.stderr)
        sys.exit(2)

    if args.overwrite and out_dir.is_dir():
        shutil.rmtree(out_dir)
        print(f"[RUN] --overwrite：已删除 {out_dir}", flush=True)
    elif not args.resume and out_csv.is_file():
        print(
            f"[ERROR] 输出已存在: {out_csv}\n"
            "若要在全新子目录重跑，请加 --overwrite（将删除该子目录下全部文件）。\n"
            "若要在同一 CSV 上断点续跑，请加 --resume。",
            file=sys.stderr,
        )
        sys.exit(2)

    photo_dir = Path(args.photo_dir).expanduser().resolve()
    if not photo_dir.is_dir():
        print(f"[ERROR] 照片目录不存在: {photo_dir}", file=sys.stderr)
        sys.exit(1)

    bodies = list_body_template_names()
    hairs = list_hair_style_names()
    if len(bodies) < 3 or len(hairs) < 3:
        print(
            f"[ERROR] 候选过少：服装预览 {len(bodies)}、发型预览 {len(hairs)}。"
            "请先跑 Stage1 与发型预览脚本。",
            file=sys.stderr,
        )
        sys.exit(1)

    photos = sorted(
        list(photo_dir.glob("*.png"))
        + list(photo_dir.glob("*.jpg"))
        + list(photo_dir.glob("*.jpeg"))
    )
    if not photos:
        print(f"[ERROR] {photo_dir} 下无图片", file=sys.stderr)
        sys.exit(1)

    ensure_dir(out_dir)
    out_csv = out_dir / CSV_NAME

    done_ids = existing_real_head_ids(out_csv) if args.resume else set()
    seed = (args.variation_seed or "").strip() or f"auto-{random.randint(10**9, 10**10 - 1)}"
    if args.resume and done_ids:
        print(f"[RUN] --resume：CSV 中已有 {len(done_ids)} 个 real_head_id，将跳过这些照片", flush=True)

    if args.candidate_count is not None:
        print(
            "[WARN] --candidate-count 已弃用，请改用 --themes-per-face（当前仍按传入值生效）。",
            flush=True,
        )
        n_themes = max(1, int(args.candidate_count))
    else:
        n_themes = max(1, int(args.themes_per_face))
    n_branches = max(1, int(args.style_branches_per_theme))
    print(
        f"[RUN] themes_per_face={n_themes} style_branches_per_theme={n_branches}（CSV 行数 / 条内分句数）",
        flush=True,
    )

    jobs: list[tuple[Path, str]] = []
    for photo in photos:
        rid = extract_real_head_id(photo)
        if not rid:
            print(f"[SKIP] 无法从路径解析 6 位 id: {photo}", flush=True)
            continue
        if rid in done_ids:
            print(f"[SKIP] id={rid} 已在 CSV 中（--resume）", flush=True)
            continue
        jobs.append((photo, rid))

    n_workers = max(1, int(args.workers))
    print(f"[RUN] workers={n_workers} 待处理人脸 {len(jobs)}", flush=True)
    if not jobs:
        print(f"[DONE] 输出文件: {out_csv}（本进程共追加 0 行）", flush=True)
        return

    csv_lock = threading.Lock()
    stats = [0, 0]  # 已成功落盘人脸数、本进程追加行数
    retry_n = max(1, int(args.retry))
    theme_hint = str(args.theme_hint or "")
    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        futures = [
            pool.submit(
                _analyze_append_one_job,
                photo,
                rid,
                out_csv=out_csv,
                bodies=bodies,
                hairs=hairs,
                n_themes=n_themes,
                n_branches=n_branches,
                seed=seed,
                theme_hint=theme_hint,
                retry=retry_n,
                n_jobs=len(jobs),
                csv_lock=csv_lock,
                done_ids=done_ids,
                stats=stats,
            )
            for photo, rid in jobs
        ]
        for fut in as_completed(futures):
            fut.result()

    total_appended = stats[1]
    print(f"[DONE] 输出文件: {out_csv}（本进程共追加 {total_appended} 行）", flush=True)


if __name__ == "__main__":
    main()
