#!/usr/bin/env python3
"""在 ``resource/blender/hair_color/`` 下生成与 ``common.hair_assets.HAIR_COLORS`` 一致的纯色 PNG 色块。

无需第三方依赖。仓库根执行::

    python scripts/generate_hair_color_swatches.py
"""

from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from common.hair_assets import HAIR_COLORS, hair_color_swatches_dir, hex_to_rgb01


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def write_png_rgb(path: Path, r: int, g: int, b: int, w: int = 256, h: int = 256) -> None:
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    raw_rows = b"".join(b"\x00" + bytes([r, g, b]) * w for _ in range(h))
    comp = zlib.compress(raw_rows, 9)
    body = sig + _png_chunk(b"IHDR", ihdr) + _png_chunk(b"IDAT", comp) + _png_chunk(b"IEND", b"")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)


def main() -> None:
    out_dir = hair_color_swatches_dir(_REPO)
    for name, hex_s in sorted(HAIR_COLORS.items()):
        r01, g01, b01 = hex_to_rgb01(hex_s)
        r, g, b = int(r01 * 255), int(g01 * 255), int(b01 * 255)
        path = out_dir / f"{name}.png"
        write_png_rgb(path, r, g, b)
        print(f"[OK] {path.relative_to(_REPO)}", flush=True)
    print(f"共 {len(HAIR_COLORS)} 个色块 -> {out_dir}", flush=True)


if __name__ == "__main__":
    main()
