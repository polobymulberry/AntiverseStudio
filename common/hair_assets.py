"""Solid hair 资源路径与发色名 / 内联 hex → #RRGGBB（供 Stage11 等 Blender 脚本与普通 Python 共用，不依赖 bpy）。"""

from __future__ import annotations

import re
from pathlib import Path

# 发色名 → #RRGGBB（与 scripts/generate_hair_color_swatches.py 一致）。
# ``pipeline_render_prefs.yml`` / CLI 的 ``hair_color`` 亦可写 ``#RRGGBB`` 或 ``RRGGBB``（见 ``parse_inline_hair_hex`` / ``resolve_hair_hex``）。
HAIR_COLORS: dict[str, str] = {
    "auburn": "#712F2C",
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
# solid_hair 子目录名：female_hair_01 / male_hair_03
_SOLID_HAIR_ID_RE = re.compile(r"^(female|male)_hair_[0-9]+$", re.IGNORECASE)
_INLINE_HAIR_HEX_RE = re.compile(r"^#?(?P<h>[0-9A-Fa-f]{6})$")


def hair_root_dir(repo: Path) -> Path:
    return (repo / "resource" / "blender" / "solid_hair").resolve()


def hair_style_preview_png(repo: Path, hair_subdir: str) -> Path:
    """``solid_hair_preview/hair_style/<子目录名>.png``（Stage1 发型纯预览批处理产出）。"""
    sub = _safe_subdir_name(hair_subdir)
    if not sub:
        return Path()
    return (repo / "resource" / "blender" / "solid_hair_preview" / "hair_style" / f"{sub}.png").resolve()


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


def is_solid_hair_style_id(name: str) -> bool:
    """``hair_object`` 是否为 ``solid_hair/<id>/low_poly/hair.obj`` 的发型 id。"""
    return bool(_SOLID_HAIR_ID_RE.match((name or "").strip()))


def parse_inline_hair_hex(raw: str) -> str | None:
    """若为 ``#RRGGBB`` 或 ``RRGGBB``（6 位十六进制），返回规范 ``#RRGGBB``；否则 ``None``。"""
    s = (raw or "").strip()
    m = _INLINE_HAIR_HEX_RE.match(s)
    if not m:
        return None
    return f"#{m.group('h').upper()}"


def resolve_hair_hex(color_name: str, *, default: str = "#0D0D0D") -> str:
    """发色名或内联 hex（``#RRGGBB`` / ``RRGGBB``）→ 规范 ``#RRGGBB``；未知则 ``default``。"""
    s = (color_name or "").strip()
    if not s:
        return default
    inline = parse_inline_hair_hex(s)
    if inline is not None:
        return inline
    key = s.lower().replace(" ", "_")
    hex_s = HAIR_COLORS.get(key)
    if hex_s is None:
        return default
    h = hex_s.strip()
    if not h.startswith("#"):
        h = "#" + h
    return h if len(h) == 7 else default


def _srgb_channel_01_to_linear(c: float) -> float:
    """sRGB 编码单通道 0..1 → 场景线性 0..1（IEC 61966-2-1）。"""
    if c <= 0.0:
        return 0.0
    c = min(c, 1.0)
    if c <= 0.04045:
        return c / 12.92
    return ((c + 0.055) / 1.055) ** 2.4


def hex_to_srgb01(hex_s: str) -> tuple[float, float, float]:
    """``#RRGGBB`` 或 ``RRGGBB`` → **sRGB 编码** RGB 各通道 0..1（与屏显 / hex 字面值一致；PNG 色块等）。"""
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


def hex_to_linear_rgb01(hex_s: str) -> tuple[float, float, float]:
    """``#RRGGBB`` 或 ``RRGGBB`` → **场景线性** RGB 0..1（Blender Cycles/Eevee Principled BSDF Base Color）。"""
    rs, gs, bs = hex_to_srgb01(hex_s)
    return (
        _srgb_channel_01_to_linear(rs),
        _srgb_channel_01_to_linear(gs),
        _srgb_channel_01_to_linear(bs),
    )


def hex_to_rgb01(hex_s: str) -> tuple[float, float, float]:
    """兼容旧名：与 :func:`hex_to_srgb01` 相同（sRGB 0..1）。新代码请按场景区分 sRGB / 线性。"""
    return hex_to_srgb01(hex_s)


def list_hair_color_names() -> list[str]:
    return sorted(HAIR_COLORS.keys())


def _hex_to_rgb_int(hex_s: str) -> tuple[int, int, int]:
    h = (hex_s or "").strip().lstrip("#")
    if len(h) != 6:
        return (0, 0, 0)
    try:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    except ValueError:
        return (0, 0, 0)


def nearest_hair_color_key(rgb: tuple[int, int, int]) -> str:
    """在 ``HAIR_COLORS`` 的 sRGB 六元组上与 ``rgb`` 做欧氏距离平方，返回最近键名。"""
    r0, g0, b0 = rgb
    best: str = "black"
    best_d = 1e30
    for name, hx in HAIR_COLORS.items():
        r, g, b = _hex_to_rgb_int(hx)
        d = (r - r0) ** 2 + (g - g0) ** 2 + (b - b0) ** 2
        if d < best_d:
            best_d = d
            best = name
    return best


def estimate_hair_rgb_from_photo_upper_band(
    photo_path: Path,
    *,
    band_ratio: float = 0.35,
) -> tuple[int, int, int]:
    """从参考图**上方条带**（默认高度约 35%，常见含发区）采样 RGB；裁掉最暗/最亮各约 5% 像素后取均值。

    无 Pillow 或读图失败时返回近黑 ``(13, 13, 13)``，由调用方映射为 ``black``。
    """
    try:
        from PIL import Image  # type: ignore[import-not-found]
    except ImportError:
        return (13, 13, 13)
    p = Path(photo_path)
    if not p.is_file():
        return (13, 13, 13)
    try:
        with Image.open(p) as im:
            im = im.convert("RGB")
            w, h = im.size
            if w < 2 or h < 2:
                return (13, 13, 13)
            band = max(1, min(h, int(h * max(0.08, min(band_ratio, 0.55)))))
            crop = im.crop((0, 0, w, band))
            pixels = list(crop.getdata())
    except OSError:
        return (13, 13, 13)
    if not pixels:
        return (13, 13, 13)

    def _lum(px: tuple[int, int, int]) -> float:
        r, g, b = px
        return 0.299 * r + 0.587 * g + 0.114 * b

    sp = sorted(pixels, key=_lum)
    n = len(sp)
    k = max(1, n // 20)
    core = sp[k : n - k] if n > 2 * k else sp
    if not core:
        core = sp
    r = sum(px[0] for px in core) // len(core)
    g = sum(px[1] for px in core) // len(core)
    b = sum(px[2] for px in core) // len(core)
    return (r, g, b)


def hair_color_key_from_reference_photo(photo_path: Path) -> str:
    """根据真人参考图估计发色，返回 ``HAIR_COLORS`` 中的英文键名（与 Stage3b 落盘一致）。"""
    rgb = estimate_hair_rgb_from_photo_upper_band(photo_path)
    return nearest_hair_color_key(rgb)
