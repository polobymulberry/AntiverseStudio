"""Blender 内嵌脚本专用：将当前场景切到 Cycles 并尽量启用 CUDA GPU。"""

from __future__ import annotations


def ensure_cycles_cuda() -> None:
    """与 Stage11 一致：Cycles + CUDA 设备；失败时打印告警并沿用当前设置。"""
    import bpy

    scene = bpy.context.scene
    if scene.render.engine != "CYCLES":
        scene.render.engine = "CYCLES"
    try:
        prefs = bpy.context.preferences.addons["cycles"].preferences
        if hasattr(prefs, "get_devices"):
            prefs.get_devices()
        prefs.compute_device_type = "CUDA"
        for dev in prefs.devices:
            if dev.type == "CUDA":
                dev.use = True
        scene.cycles.device = "GPU"
        print("Cycles: compute_device_type=CUDA, scene.cycles.device=GPU")
    except Exception as e:  # noqa: BLE001
        print(f"Cycles CUDA 未启用（将用当前 .blend / 默认设备）: {e}")
