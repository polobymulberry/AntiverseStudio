"""Pet Stage3b：Blender 渲染宠物浮雕 360° 旋转视频。

依赖工程：``resource/blender/pet_relief_360.blend``（或 env ``PET_RELIEF_BLEND_FILE``，尚未提供时需自行放置）。

输入：``output/宠物定制/pet_relief/<order_id>/model/*.glb``（优先 GLB）
输出：``…/pet_relief_360/<order_id>_360.mp4``

说明：
    本脚本为骨架实现：导入模型、绕 Z 轴旋转、Cycles 渲染帧序列并用 FFmpeg 封装。
    待 ``.blend`` 提供后，可在此脚本中对接工程内相机、灯光与材质预设。
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

import bpy

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from common.blender_cycles_gpu import ensure_cycles_cuda
from common.pet_pipeline_paths import pet_relief_model_dir, pet_relief_video_dir
from common.pipeline_lines import DEFAULT_PET_PIPELINE_LINE
from common.settings import SETTINGS

# 默认 180 帧 @ 30fps = 6 秒一圈
DEFAULT_FRAME_END = 180
DEFAULT_FPS = 30


def parse_cli_args() -> argparse.Namespace:
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1 :]
    else:
        argv = []
    parser = argparse.ArgumentParser(description="Pet Stage3b：浮雕 360° 旋转视频。")
    parser.add_argument("--order-id", required=True)
    parser.add_argument("--pipeline-line", default=DEFAULT_PET_PIPELINE_LINE)
    parser.add_argument("--fps", type=int, default=DEFAULT_FPS)
    parser.add_argument("--frame-end", type=int, default=DEFAULT_FRAME_END)
    parser.add_argument(
        "--resume",
        action="store_true",
        help="若输出 mp4 已存在且非空则跳过",
    )
    return parser.parse_args(argv)


def _find_primary_glb(model_dir: Path) -> Path:
    """在 model 目录中选取主 GLB（优先 .glb，否则其它 3D 格式）。"""
    model_dir = Path(model_dir)
    glbs = sorted(model_dir.glob("*.glb"))
    if glbs:
        return glbs[0]
    for ext in (".gltf", ".obj", ".fbx", ".stl"):
        found = sorted(model_dir.glob(f"*{ext}"))
        if found:
            return found[0]
    raise FileNotFoundError(f"未在 {model_dir} 找到 GLB/GLTF/OBJ/FBX/STL 模型文件。")


def _clear_previous_imports() -> None:
    """删除场景中除相机/灯光外的 mesh 物体，避免重复导入叠影。"""
    keep_types = {"CAMERA", "LIGHT"}
    to_remove = [o for o in bpy.data.objects if o.type not in keep_types]
    if not to_remove:
        return
    bpy.ops.object.select_all(action="DESELECT")
    for obj in to_remove:
        obj.select_set(True)
    bpy.ops.object.delete()


def _import_model(path: Path) -> bpy.types.Object:
    """导入 3D 模型并返回根物体。"""
    suffix = path.suffix.lower()
    if suffix == ".glb" or suffix == ".gltf":
        bpy.ops.import_scene.gltf(filepath=str(path))
    elif suffix == ".obj":
        bpy.ops.wm.obj_import(filepath=str(path))
    elif suffix == ".fbx":
        bpy.ops.import_scene.fbx(filepath=str(path))
    elif suffix == ".stl":
        bpy.ops.wm.stl_import(filepath=str(path))
    else:
        raise ValueError(f"不支持的模型格式: {path}")
    meshes = [o for o in bpy.context.selected_objects if o.type == "MESH"]
    if not meshes:
        raise RuntimeError(f"导入后无 MESH 物体: {path}")
    root = meshes[0]
    while root.parent:
        root = root.parent
    return root


def _ensure_camera_and_light() -> tuple[bpy.types.Object, bpy.types.Object]:
    """若工程中无相机/主光，创建默认棚拍布局。"""
    cam = bpy.data.objects.get("PetReliefCamera")
    if cam is None:
        cam_data = bpy.data.cameras.new("PetReliefCamera")
        cam = bpy.data.objects.new("PetReliefCamera", cam_data)
        bpy.context.collection.objects.link(cam)
        cam.location = (0.0, -2.5, 1.2)
        cam.rotation_euler = (1.1, 0.0, 0.0)
    light = bpy.data.objects.get("PetReliefKeyLight")
    if light is None:
        light_data = bpy.data.lights.new("PetReliefKeyLight", type="AREA")
        light_data.energy = 800.0
        light = bpy.data.objects.new("PetReliefKeyLight", light_data)
        bpy.context.collection.objects.link(light)
        light.location = (1.5, -1.0, 2.5)
    return cam, light


def _setup_turntable(root: bpy.types.Object, frame_end: int) -> None:
    """为导入根物体添加 Z 轴 360° 旋转关键帧。"""
    root.rotation_mode = "XYZ"
    root.rotation_euler = (0.0, 0.0, 0.0)
    root.keyframe_insert(data_path="rotation_euler", frame=1)
    root.rotation_euler = (0.0, 0.0, 6.283185307)
    root.keyframe_insert(data_path="rotation_euler", frame=frame_end)


def _setup_render(output_mp4: Path, fps: int, frame_end: int) -> None:
    """配置 Cycles + FFmpeg 视频输出。"""
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    ensure_cycles_cuda(scene)
    scene.render.fps = fps
    scene.frame_start = 1
    scene.frame_end = frame_end
    scene.render.image_settings.file_format = "FFMPEG"
    scene.render.ffmpeg.format = "MPEG4"
    scene.render.ffmpeg.codec = "H264"
    scene.render.filepath = str(output_mp4.with_suffix(""))  # Blender 会自动加扩展名


def _ffmpeg_remux_if_needed(blender_out: Path, final_mp4: Path) -> None:
    """Blender 有时输出无 .mp4 后缀；统一 remux 到目标路径。"""
    candidates = [
        final_mp4,
        blender_out.with_suffix(".mp4"),
        Path(str(blender_out) + ".mp4"),
    ]
    for c in candidates:
        if c.is_file() and c.stat().st_size > 0:
            if c.resolve() != final_mp4.resolve():
                shutil.copy2(c, final_mp4)
            return
    raise RuntimeError(f"未找到 Blender 渲染输出，期望类似: {blender_out}")


def main() -> None:
    args = parse_cli_args()
    model_dir = pet_relief_model_dir(
        SETTINGS.output_root, args.order_id, pipeline_line=args.pipeline_line
    )
    video_dir = pet_relief_video_dir(
        SETTINGS.output_root, args.order_id, pipeline_line=args.pipeline_line
    )
    video_dir.mkdir(parents=True, exist_ok=True)
    output_mp4 = video_dir / f"{args.order_id}_360.mp4"

    if args.resume and output_mp4.is_file() and output_mp4.stat().st_size > 0:
        print(f"[SKIP] 已存在有效视频: {output_mp4}", flush=True)
        return

    glb = _find_primary_glb(model_dir)
    print(f"[RUN] 导入模型: {glb}", flush=True)

    _clear_previous_imports()
    root = _import_model(glb)
    _ensure_camera_and_light()
    _setup_turntable(root, args.frame_end)
    _setup_render(output_mp4, args.fps, args.frame_end)

    print(f"[RUN] 渲染 {args.frame_end} 帧 -> {output_mp4}", flush=True)
    bpy.ops.render.render(animation=True)

    _ffmpeg_remux_if_needed(output_mp4, output_mp4)
    print(f"[OK] 360 视频: {output_mp4}", flush=True)


if __name__ == "__main__":
    main()
