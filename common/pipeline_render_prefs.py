"""与 ``output/stage4_10/<模板>/<路径段>/`` 同级的渲染偏好 YAML。

文件名：``pipeline_render_prefs.yml``。供 Stage4、Stage11 等在**启动时**同步：
已存在则从文件读缺省；命令行有则覆盖并写回；皆无则用随机 Tint + 默认头/发并**立即写入**。

另可持久化 ``user_requirement`` 与 ``fashion_tag``（仅记录，不参与 Blender 逻辑）。
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

_HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")

_YAML_HEADER = (
    "# 流水线渲染偏好（可手改）。\n"
    "# studio_tint_hex: Studio 背景墙 Tint，#RRGGBB（与 stage11 --studio-tint-hex 一致）。\n"
    "# 亦可用键名 studio_tint_color（与 studio_tint_hex 等价）。\n"
    "# head_object: .blend 中头物体名（如 female_01_head）。\n"
    "# hair_object: 若为 female_03_hair 等内置名则沿用 .blend 头发；若为 solid_hair 下子目录名（如 female_hair_01），\n"
    "#   则从 resource/blender/solid_hair/<hair_object>/low_poly/hair.obj 导入发型。\n"
    "# hair_color: 发色名，见 common.hair_assets.HAIR_COLORS（如 brown、black）；与 solid / 内置头发材质 Base Color 一致。\n"
    "# user_requirement: 阶段4 生成该 run 时传入的完整需求文本（仅记录，不参与 Blender 逻辑）。\n"
    "# fashion_tag: 可选；与 --fashion-tag 一致时的目录索引标签（仅记录）。\n"
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


def write_render_prefs_yml(
    run_dir: Path,
    *,
    studio_tint_hex: str,
    head_object: str,
    hair_object: str,
    hair_color: str = "black",
    user_requirement: str = "",
    fashion_tag: str = "",
) -> Path:
    """写入偏好文件（含可选的需求与 tag 记录）。"""
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
    - ``user_requirement`` / ``fashion_tag``：命令行非空则写回；否则沿用 YAML 已有值（便于仅传 ``--fashion-tag`` 时保留阶段4 记入的需求全文）。
    - ``hair_color``：同上；缺省为 ``black``。
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
    cli_ft = _str_field(getattr(args, "fashion_tag", None))
    file_u = _str_field(data.get("user_requirement"))
    file_ft = _str_field(data.get("fashion_tag"))
    user_req = cli_u or file_u
    fashion_tag_out = cli_ft or file_ft

    write_render_prefs_yml(
        run_dir,
        studio_tint_hex=tint_file,
        head_object=head,
        hair_object=hair,
        hair_color=hair_color,
        user_requirement=user_req,
        fashion_tag=fashion_tag_out,
    )
    return path


def ensure_initial_render_prefs_yml(
    run_dir: Path,
    *,
    user_requirement: str = "",
    fashion_tag: str = "",
) -> Path | None:
    """Stage4：启动时同步 YAML；写入本次 ``user_requirement`` / ``fashion_tag``。

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
            fashion_tag=fashion_tag or None,
        ),
    )
    return None if existed else path
