"""Blender 场景中 Studio 背景墙材质 ``Studio_Fabric_1.001`` 的 Tint 可选十六进制色。

与 ``stage11_render_videos/blender_render_videos.py`` 中 ``--studio-tint-hex`` / ``--random-studio-tint`` 一致。
亦可在普通 Python（非 Blender）中 import 本模块以查看预设列表。"""

from __future__ import annotations

# 与 resource/blender/blender_render_videos.blend 中材质节点搭配；
# 均为低饱和、偏灰/米/雾感的布料与影棚背景友好色，与 resource/blender/studio_color/<HEX>.png 命名一致（无 #）。
STUDIO_TINT_HEX_PRESETS: list[str] = [
    # 原有 11 项（亚麻、鼠尾草、灰青、雾蓝、藕粉等）
    "#E3D9C6",
    "#8E9775",
    "#5F7A76",
    "#B0C4DE",
    "#D7C4BB",
    "#F5F5DC",
    "#E6E6FA",
    "#D0C8FF",  # 淡薰衣草，见 resource/blender/studio_color/D0C8FF.png
    "#B7AD99",
    "#DEE4E7",
    "#D1E9F0",
    "#F4E0E0",
    # 扩展：暖石、灰绿、燕麦、雾蓝灰、亚麻白等同气质色
    "#C9B8A4",
    "#A8ADA4",
    "#B8A89A",
    "#D4C4B0",
    "#9EB6B8",
    "#C8D4D8",
    "#DAD4C8",
    "#A39E93",
    "#8F9B8A",
    "#C6BCB3",
    "#E8E4DC",
    "#B9C4C9",
    "#A89B8C",
    "#CCD5DB",
]
