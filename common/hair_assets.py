"""Solid hair 资源路径与发色名 → hex（供 Stage11 等 Blender 脚本与普通 Python 共用，不依赖 bpy）。"""

from __future__ import annotations

import re
from pathlib import Path

# 发色名 → #RRGGBB（与 scripts/generate_hair_color_swatches.py 一致）
HAIR_COLORS: dict[str, str] = {
    "brown": "#583E3A",
    "black": "#0D0D0D",
    "blue": "#3E6BA0",
    "burgundy": "#800020",
    "dark_gold": "#7A6344",
    "dark_gray": "#808080",
    "dark_red": "#800000",
    "ginger_yellow": "#FFC000",
    "golden": "#FEB769",
    "gray": "#747C89",
    "green": "#167392",
    "light_brown": "#A07850",
    "light_gold": "#DEB887",
    "light_gray": "#C0C0C0",
    "light_red": "#FF6446",
    "linen": "#DBD5BD",
    "medium_brown": "#6E4C28",
    "medium_gold": "#B38C50",
    "medium_red": "#C84646",
    "pink": "#EF888F",
    "platinum_gold": "#F0E8D7",
    "purple": "#6D62B2",
}

# .blend 内置命名：female_03_hair / male_08_hair
_BLEND_HAIR_RE = re.compile(r"^(female|male)_[0-9]+_hair$", re.IGNORECASE)


def hair_root_dir(repo: Path) -> Path:
    return (repo / "resource" / "blender" / "solid_hair").resolve()


def hair_color_swatches_dir(repo: Path) -> Path:
    return (repo / "resource" / "blender" / "hair_color").resolve()


def solid_hair_obj_path(repo: Path, hair_subdir: str) -> Path | None:
    """``resource/blender/solid_hair/<hair_subdir>/low_poly/hair.obj`` 存在则返回路径。"""
    sub = _safe_subdir_name(hair_subdir)
    if not sub:
        return None
    p = hair_root_dir(repo) / sub / "low_poly" / "hair.obj"
    return p if p.is_file() else None


def _safe_subdir_name(hair_subdir: str) -> str:
    s = (hair_subdir or "").strip()
    if not s or ".." in s or "/" in s or "\\" in s:
        return ""
    # 仅允许一层目录名，如 female_hair_01
    return Path(s).name


def is_blend_builtin_hair_name(name: str) -> bool:
    return bool(_BLEND_HAIR_RE.match((name or "").strip()))


def resolve_hair_hex(color_name: str, *, default: str = "#0D0D0D") -> str:
    """发色名 → ``#RRGGBB``；未知则 ``default``。"""
    key = (color_name or "").strip().lower().replace(" ", "_")
    if not key:
        return default
    hex_s = HAIR_COLORS.get(key)
    if hex_s is None:
        return default
    h = hex_s.strip()
    if not h.startswith("#"):
        h = "#" + h
    return h if len(h) == 7 else default


def hex_to_rgb01(hex_s: str) -> tuple[float, float, float]:
    """``#RRGGBB`` 或 ``RRGGBB`` → 线性 RGB 0..1。"""
    h = (hex_s or "").strip().lstrip("#")
    if len(h) != 6:
        return (0.05, 0.05, 0.05)
    try:
        r = int(h[0:2], 16) / 255.0
        g = int(h[2:4], 16) / 255.0
        b = int(h[4:6], 16) / 255.0
    except ValueError:
        return (0.05, 0.05, 0.05)
    return (r, g, b)


def list_hair_color_names() -> list[str]:
    return sorted(HAIR_COLORS.keys())
