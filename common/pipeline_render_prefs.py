"""与 ``output/<PIPELINE_LINE>/stage4_10/<fashion_tag>/<body_template>/`` 上一级（主题根）同名的渲染偏好 YAML。

路径：``output/<PIPELINE_LINE>/stage4_10/<truncate(fashion_tag)>/pipeline_render_prefs.yml``（``PIPELINE_LINE`` 默认「手办服装IP」，环境变量 ``PIPELINE_LINE`` 可改为「卡通人偶定制」等）。
供 Stage4、Stage11 等在**启动时**同步：已存在则从文件读缺省；命令行有则覆盖并写回；
亦持久化 ``body_templates``（列表）；可选顶层 ``prompt_count`` 仅用于字符串简写项的默认条数。

``user_requirement`` / ``fashion_tag`` 等记录服装主题锚点（含随身小配饰、手中玩偶/玩具等须与母题一致）；``hair_object`` / ``hair_color`` 供 Blender 导入 solid 发型与染色；``head_object``、Tint 供渲染。

**服装锚点**：统一使用 ``user_requirement``（与手办 IP 线一致）。旧 YAML 若仅有 ``body_requirement``，加载时视作 ``user_requirement`` 的回退来源；写回时会合并进 ``user_requirement`` 并省略空的弃用键。

可选 ``body_textured_glb`` / ``hair_textured_glb`` 用于显式覆盖 Stage8 身体 GLB 等；卡通人偶头发一般为 **solid mesh + ``hair_color``**，不再依赖已移除的头发新纹理阶段。
"""

from __future__ import annotations

import random
import re
from pathlib import Path
from typing import Any

from common.studio_render_constants import STUDIO_TINT_HEX_PRESETS

RUN_RENDER_PREFS_FILENAME = "pipeline_render_prefs.yml"

DEFAULT_HEAD_OBJECT = "female_03_head"
DEFAULT_HAIR_OBJECT = "female_03_hair"
DEFAULT_PROMPT_COUNT = 20

_HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")

_YAML_HEADER = (
    "# 流水线渲染偏好（可手改）。\n"
    "# studio_tint_hex: Studio 背景墙 Tint，#RRGGBB（与 stage11 --studio-tint-hex 一致）。\n"
    "# 亦可用键名 studio_tint_color（与 studio_tint_hex 等价）。\n"
    "# head_object: Blender 内置头物体名（如 female_01_head）；或 0～119999 的纯数字 template_id（6 位亦可），\n"
    "#   此时加载 REAL_HEAD_120K_ROOT 下 solid/<id>/akintisan3d/template_aligned/mcr_head.glb\n"
    "#   （可用 REAL_HEAD_MESH_REL_PATTERN 覆盖）。导入后隐藏内置头，缩放 0.1。\n"
    "# hair_object: 若为 female_03_hair 等内置名则沿用 .blend 头发；若为 solid_hair 下子目录名（如 female_hair_01），\n"
    "#   则从 resource/blender/solid_hair/<hair_object>/low_poly/hair.obj 导入发型。\n"
    "# hair_color: 发色名（见 common.hair_assets.HAIR_COLORS，如 brown、black）或内联 #RRGGBB / RRGGBB；与 solid / 内置头发材质 Base Color 一致。\n"
    "# user_requirement: 阶段4 服装纹理主题锚点（手办 IP 与卡通人偶线统一字段）；须覆盖整身含随身小配饰、手中玩偶/玩具等，配色与纹样气质与母题一致，勿因体积小而忽略。\n"
    "# body_requirement: （已弃用，兼容旧 YAML）若存在且无 user_requirement，工具会读入后合并写入 user_requirement。\n"
    "# body_textured_glb / hair_textured_glb: 可选。相对本套模板 run 的路径；头发默认 solid + hair_color，仅特殊覆盖时填 hair_textured_glb。\n"
    "# fashion_tag: 与 --fashion-tag 一致；用于目录 output/<产品线>/stage4_10/<截断>/<body>/。\n"
    "# body_templates: 本主题参与的服装模板列表。推荐写法（每项自带 prompt_count，无需顶层重复）：\n"
    "#   body_templates:\n"
    "#     - template_name: body_65\n"
    "#       prompt_count: 20\n"
    "#     - template_name: body_80_female\n"
    "#       prompt_count: 20\n"
    "# 若使用字符串简写（如 - body_65），可写顶层 prompt_count 作为这些项的默认条数；\n"
    "# 顶层 prompt_count 会在「删掉后与删掉前解析结果一致」时由工具省略。\n"
)


def pipeline_render_prefs_path(run_dir: Path) -> Path:
    return run_dir.resolve() / RUN_RENDER_PREFS_FILENAME


def _load_yaml(path: Path) -> dict[str, Any]:
    import yaml

    raw = path.read_text(encoding="utf-8")
    data = yaml.safe_load(raw)
    return data if isinstance(data, dict) else {}


def _dump_yaml(data: dict[str, Any]) -> str:
    import yaml

    body = yaml.safe_dump(
        data,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    )
    return _YAML_HEADER + "\n" + body


def _str_field(val: Any) -> str:
    if val is None:
        return ""
    return str(val).strip()


def _coerce_hex(val: Any) -> str | None:
    if val is None:
        return None
    t = str(val).strip()
    if not t:
        return None
    if not t.startswith("#"):
        t = "#" + t
    if _HEX_RE.match(t):
        return t
    return None


def load_render_prefs_dict(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return _load_yaml(path)


# 单套 body 模板 run 目录下的 YAML 可覆盖主题根中的渲染项（头/发/发色/Tint）
_RUN_OVERRIDABLE_PREF_KEYS: tuple[str, ...] = (
    "head_object",
    "hair_object",
    "hair_color",
    "studio_tint_hex",
    "studio_tint_color",
)


def load_render_prefs_merged(body_template_run_dir: Path) -> dict[str, Any]:
    """读取渲染偏好：主题根 ``pipeline_render_prefs.yml`` 为底，模板 run 下同名文件覆盖头/发等。"""
    run_dir = body_template_run_dir.resolve()
    theme_dir = run_dir.parent
    theme_path = pipeline_render_prefs_path(theme_dir)
    data = load_render_prefs_dict(theme_path) if theme_path.is_file() else {}
    local_path = pipeline_render_prefs_path(run_dir)
    if local_path.is_file() and local_path.resolve() != theme_path.resolve():
        local = load_render_prefs_dict(local_path)
        overridden: list[str] = []
        for key in _RUN_OVERRIDABLE_PREF_KEYS:
            if key in local and _str_field(local.get(key)):
                data[key] = local[key]
                if key not in ("studio_tint_hex", "studio_tint_color"):
                    overridden.append(key)
        if overridden:
            print(
                f"[RUN] 模板级 pipeline_render_prefs 覆盖: {local_path.name} "
                f"({', '.join(overridden)})",
                flush=True,
            )
    return data


def resolve_body_theme_requirement(data: dict[str, Any]) -> str:
    """服装主题：``user_requirement`` 优先；旧 YAML 仅含 ``body_requirement`` 时回退。"""
    u = _str_field(data.get("user_requirement"))
    if u:
        return u
    return _str_field(data.get("body_requirement"))


def parse_body_templates_from_prefs(data: dict[str, Any]) -> list[tuple[str, int]]:
    """从 YAML 字典解析 ``(template_name, prompt_count)`` 列表。"""
    default_n = int(data.get("prompt_count") or DEFAULT_PROMPT_COUNT)
    raw = data.get("body_templates")
    out: list[tuple[str, int]] = []
    if raw is None:
        return out
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return out
    for item in raw:
        if isinstance(item, str):
            name = item.strip()
            if name:
                out.append((name, default_n))
        elif isinstance(item, dict):
            name = (item.get("template_name") or item.get("name") or "").strip()
            n = int(item.get("prompt_count") or default_n)
            if name:
                out.append((name, n))
    return out


def top_level_prompt_count_is_redundant(data: dict[str, Any]) -> bool:
    """若去掉顶层 ``prompt_count`` 后，``parse_body_templates_from_prefs`` 结果不变，则视为冗余（可省略）。"""
    if "prompt_count" not in data:
        return False
    before = parse_body_templates_from_prefs(data)
    trimmed = {k: v for k, v in data.items() if k != "prompt_count"}
    after = parse_body_templates_from_prefs(trimmed)
    return before == after


def list_body_template_names_for_fashion_tag(
    output_root: Path,
    fashion_tag: str,
    *,
    pipeline_line: str | None = None,
) -> list[str]:
    """按主题根 ``pipeline_render_prefs.yml`` 中 ``body_templates`` 顺序返回模板名（供 Stage5/6/8 批量遍历）。"""
    from common.utils import fashion_tag_run_dir

    tag = (fashion_tag or "").strip()
    if not tag:
        raise ValueError("fashion_tag 不能为空。")
    root = fashion_tag_run_dir(output_root, tag, pipeline_line=pipeline_line)
    path = pipeline_render_prefs_path(root)
    if not path.is_file():
        raise FileNotFoundError(
            f"未找到主题偏好文件: {path}\n"
            "请在该目录放置 pipeline_render_prefs.yml 并填写 body_templates，"
            "或使用 --template 只处理单套模板。"
        )
    pairs = parse_body_templates_from_prefs(load_render_prefs_dict(path))
    if not pairs:
        raise ValueError(f"{path} 中 body_templates 为空或缺失。")
    return [name for name, _ in pairs]


def write_render_prefs_yml(
    run_dir: Path,
    *,
    studio_tint_hex: str,
    head_object: str,
    hair_object: str,
    hair_color: str = "black",
    user_requirement: str = "",
    body_requirement: str = "",
    hair_requirement: str = "",
    fashion_tag: str = "",
    prompt_count: int | None = None,
    body_templates: Any | None = None,
    preserve_keys: dict[str, Any] | None = None,
) -> Path:
    """写入偏好文件（含可选的需求与 tag、body_templates 记录）。"""
    run_dir = run_dir.resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    path = pipeline_render_prefs_path(run_dir)
    data: dict[str, Any] = {
        "studio_tint_hex": _coerce_hex(studio_tint_hex) or studio_tint_hex.strip(),
        "head_object": head_object.strip(),
        "hair_object": hair_object.strip(),
        "hair_color": _str_field(hair_color) or "black",
        "user_requirement": _str_field(user_requirement),
        "fashion_tag": _str_field(fashion_tag),
    }
    br = _str_field(body_requirement)
    hr = _str_field(hair_requirement)
    if br:
        data["body_requirement"] = br
    if hr:
        data["hair_requirement"] = hr
    if prompt_count is not None:
        data["prompt_count"] = int(prompt_count)
    if body_templates is not None:
        data["body_templates"] = body_templates
    if preserve_keys:
        for k, v in preserve_keys.items():
            if k not in data and v is not None:
                data[k] = v
    path.write_text(_dump_yaml(data), encoding="utf-8")
    return path


def merge_cli_from_render_prefs(args: Any, prefs_path: Path) -> None:
    """仅将 YAML 中未在 CLI 上指定的字段写入 ``args``（CLI 已传的项不覆盖）。"""
    data = load_render_prefs_dict(prefs_path)
    if not data:
        return
    if not (getattr(args, "studio_tint_hex", None) or "").strip():
        alt = data.get("studio_tint_hex") or data.get("studio_tint_color")
        h = _coerce_hex(alt)
        if h:
            args.studio_tint_hex = h
    if not (getattr(args, "head_object", None) or "").strip():
        ho = data.get("head_object")
        if ho is not None and str(ho).strip():
            args.head_object = str(ho).strip()
    if not (getattr(args, "hair_object", None) or "").strip():
        ha = data.get("hair_object")
        if ha is not None and str(ha).strip():
            args.hair_object = str(ha).strip()
    if not (getattr(args, "hair_color", None) or "").strip():
        hc = data.get("hair_color")
        if hc is not None and str(hc).strip():
            args.hair_color = str(hc).strip()


def sync_pipeline_render_prefs_at_start(run_dir: Path, args: Any) -> Path:
    """启动时同步 ``args`` 与磁盘上的 ``pipeline_render_prefs.yml``。

    - 若命令行已给 ``--head-object`` / ``--hair-object`` / ``--studio-tint-hex``，以其为准并**写回** YAML。
    - 若未给且 YAML 中有值，则读入 ``args``。
    - 若仍未有 Tint，则在**非** ``--random-studio-tint`` 时随机选一色写入并赋给 ``args``。
    - ``--random-studio-tint`` 时不给 ``args`` 赋 ``studio_tint_hex``；YAML 仍保留一份十六进制作默认记录（随机选取或沿用文件）。
    - ``user_requirement`` / ``fashion_tag``：命令行非空则写回；否则沿用 YAML 已有值（便于仅传 ``--fashion-tag`` 时保留阶段4 记入的主题锚点）。
    - ``hair_color``：同上（可为 HAIR_COLORS 键名或 ``#RRGGBB`` / ``RRGGBB``）；缺省为 ``black``。
    """
    run_dir = run_dir.resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    path = pipeline_render_prefs_path(run_dir)
    data = load_render_prefs_dict(path) if path.is_file() else {}

    cli_h = _str_field(getattr(args, "head_object", None))
    cli_r = _str_field(getattr(args, "hair_object", None))
    cli_hc = _str_field(getattr(args, "hair_color", None))
    cli_t = _coerce_hex(getattr(args, "studio_tint_hex", None))
    rnd = bool(getattr(args, "random_studio_tint", False))

    file_h = _str_field(data.get("head_object"))
    file_r = _str_field(data.get("hair_object"))
    file_hc = _str_field(data.get("hair_color"))
    file_t = _coerce_hex(data.get("studio_tint_hex") or data.get("studio_tint_color"))

    head = cli_h or file_h or DEFAULT_HEAD_OBJECT
    hair = cli_r or file_r or DEFAULT_HAIR_OBJECT
    hair_color = cli_hc or file_hc or "black"

    if rnd:
        setattr(args, "studio_tint_hex", None)
        tint_file = file_t or random.choice(STUDIO_TINT_HEX_PRESETS)
    else:
        tint = cli_t or file_t or random.choice(STUDIO_TINT_HEX_PRESETS)
        args.studio_tint_hex = tint
        tint_file = tint

    args.head_object = head
    args.hair_object = hair
    args.hair_color = hair_color

    cli_u = _str_field(getattr(args, "user_requirement", None))
    cli_br = _str_field(getattr(args, "body_requirement", None))
    cli_ft = _str_field(getattr(args, "fashion_tag", None))
    file_u = _str_field(data.get("user_requirement"))
    file_br = _str_field(data.get("body_requirement"))
    file_ft = _str_field(data.get("fashion_tag"))
    user_req = cli_u or file_u or cli_br or file_br
    fashion_tag_out = cli_ft or file_ft

    preserve: dict[str, Any] = {}
    if "body_templates" in data:
        preserve["body_templates"] = data["body_templates"]
    if "prompt_count" in data and not top_level_prompt_count_is_redundant(data):
        preserve["prompt_count"] = data["prompt_count"]
    if not path.is_file():
        preserve.setdefault("body_templates", [])
    for optional_glbs in ("body_textured_glb", "hair_textured_glb"):
        if optional_glbs in data and _str_field(data.get(optional_glbs)):
            preserve[optional_glbs] = _str_field(data.get(optional_glbs))

    write_render_prefs_yml(
        run_dir,
        studio_tint_hex=tint_file,
        head_object=head,
        hair_object=hair,
        hair_color=hair_color,
        user_requirement=user_req,
        body_requirement="",
        hair_requirement="",
        fashion_tag=fashion_tag_out,
        preserve_keys=preserve if preserve else None,
    )
    return path


def ensure_initial_render_prefs_yml(
    run_dir: Path,
    *,
    user_requirement: str = "",
    body_requirement: str = "",
    hair_requirement: str = "",
    fashion_tag: str = "",
) -> Path | None:
    """Stage4：启动时同步 YAML；写入本次需求 / ``fashion_tag``。

    若调用前文件不存在则返回路径供打日志，已存在则返回 None。
    """
    from types import SimpleNamespace

    path = pipeline_render_prefs_path(run_dir.resolve())
    existed = path.is_file()
    sync_pipeline_render_prefs_at_start(
        run_dir,
        SimpleNamespace(
            head_object=None,
            hair_object=None,
            hair_color=None,
            studio_tint_hex=None,
            random_studio_tint=False,
            user_requirement=user_requirement or None,
            body_requirement=body_requirement or None,
            hair_requirement=hair_requirement or None,
            fashion_tag=fashion_tag or None,
        ),
    )
    return None if existed else path
