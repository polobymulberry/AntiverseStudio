"""Stage 12: 渲染白模服装视频（FFmpeg **PNG** 编码，RGBA 透明背景）。

使用 `resource/blender/render_around_white_mesh.blend`：
- 删除工程中的 `body`（若存在）
- 导入 Stage8 生成的 GLB
- 将导入后的 `body` 缩放到 0.1
- 将 body 及子网格材质替换为纯白 Diffuse BSDF（Roughness=1.0）
- 渲染 1-180 帧到 stage12 目录（`white_model.mov`，QuickTime + PNG / RGBA）
- 同步输出第 18 帧白模 PNG（显式切换为 **PNG 图像输出**；动画段为 **FFmpeg 视频输出**）
- `--resume`：若视频与白模图均已有效则跳过；若仅有视频、白模图缺失则只补渲 PNG（不重渲视频）
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import bpy

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from common.blender_cycles_gpu import ensure_cycles_cuda
from common.settings import SETTINGS
from common.utils import PIPELINE_TEMPLATE_USER_SUBDIR, body_template_run_dir, fashion_tag_run_dir

# 与 Stage11 封面帧一致，便于下游对齐时间线。
WHITE_MESH_STILL_FRAME: int = 18
# QuickTime 容器 + PNG 编码；扩展名须为 .mov，避免剪映等按 .mp4 误用 ISO MP4 路径解包导致部分帧报错。
WHITE_MESH_VIDEO_NAME: str = "white_model.mov"
LEGACY_WHITE_MESH_VIDEO_NAME: str = "white_model.mp4"


def parse_cli_args() -> argparse.Namespace:
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1 :]
    else:
        argv = []
    parser = argparse.ArgumentParser(
        description=(
            "渲染白模服装视频：扫描 Stage8 的 GLB，输出到同 run 的 "
            "stage12_render_white_mesh_videos/。建议指定 --fashion-tag（可选 --template）限定 run。"
        )
    )
    parser.add_argument(
        "--input-root",
        default=str(SETTINGS.pipeline_run_root() / PIPELINE_TEMPLATE_USER_SUBDIR),
        help="递归扫描 GLB 根目录；若指定 --fashion-tag（可选 --template），本参数被忽略",
    )
    parser.add_argument("--template", default=None, metavar="NAME")
    parser.add_argument(
        "--pass",
        default=None,
        metavar="NAME",
        help="可选占位（如 white_mesh），与 blender_render_pool 的 ETA 分桶一致；本脚本不使用。",
    )
    parser.add_argument("--user-requirement", default=None)
    parser.add_argument(
        "--fashion-tag",
        default=None,
        metavar="TAG",
        help="与阶段4 一致；仅定位 run，不参与任何生成用 prompt。",
    )
    parser.add_argument(
        "--only-glb-stem",
        default=None,
        metavar="STEM",
        help="仅渲染指定 GLB 主文件名（不含后缀）",
    )
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument(
        "--resume",
        action="store_true",
        help=(
            "跳过已有效产物：视频与白模 PNG 都存在则整任务跳过；"
            "仅视频存在而白模 PNG 缺失时只补渲白模图（不重渲整段视频）。"
        ),
    )
    return parser.parse_args(argv)


def resolve_input_root(args: argparse.Namespace | SimpleNamespace) -> Path:
    template = (getattr(args, "template", None) or "").strip()
    fashion_tag = (getattr(args, "fashion_tag", None) or "").strip()
    if fashion_tag and template:
        return body_template_run_dir(SETTINGS.output_root, fashion_tag, template).resolve()
    if fashion_tag:
        return fashion_tag_run_dir(SETTINGS.output_root, fashion_tag).resolve()
    if template:
        raise SystemExit("[ERROR] 指定 --template 时必须同时指定 --fashion-tag，或二者均省略。")
    return Path(args.input_root).resolve()


def collect_glbs(input_root: Path) -> list[tuple[Path, Path]]:
    tasks: list[tuple[Path, Path]] = []
    for glb in sorted(input_root.rglob("*.glb")):
        if glb.parent.name != "stage8_new_texture_model_generation":
            continue
        out_dir = glb.parent.with_name("stage12_render_white_mesh_videos")
        tasks.append((glb, out_dir))
    return tasks


def _looks_valid_movie_container(path: Path) -> bool:
    """粗检 Blender FFmpeg 输出的 MOV/MP4（ISO BMFF 族，头部含 ftyp）。"""
    if not path.is_file():
        return False
    try:
        if path.stat().st_size < 1024:
            return False
        with path.open("rb") as f:
            head = f.read(32)
        return b"ftyp" in head
    except OSError:
        return False


def _existing_white_mesh_video(out_dir: Path) -> tuple[Path | None, bool]:
    """若目录里已有可复用的成片，返回 (路径, 是否为旧版 .mp4 扩展名)。"""
    mov = out_dir / WHITE_MESH_VIDEO_NAME
    legacy = out_dir / LEGACY_WHITE_MESH_VIDEO_NAME
    if mov.is_file() and _looks_valid_movie_container(mov):
        return mov, False
    if legacy.is_file() and _looks_valid_movie_container(legacy):
        return legacy, True
    return None, False


def _looks_valid_png(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        if path.stat().st_size < 256:
            return False
        with path.open("rb") as f:
            sig = f.read(8)
        return sig == b"\x89PNG\r\n\x1a\n"
    except OSError:
        return False


def cleanup_body() -> None:
    bpy.ops.object.select_all(action="DESELECT")
    obj = bpy.data.objects.get("body")
    if obj is None:
        return
    obj.select_set(True)
    for child in obj.children_recursive:
        child.select_set(True)
    bpy.ops.object.delete()


def build_white_diffuse_material(name: str = "Stage11_WhiteDiffuse") -> bpy.types.Material:
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    if nt is None:
        raise RuntimeError("材质无 node_tree，无法设置白模材质。")
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.location = (240, 0)
    diffuse = nt.nodes.new("ShaderNodeBsdfDiffuse")
    diffuse.location = (-40, 0)
    diffuse.inputs["Color"].default_value = (1.0, 1.0, 1.0, 1.0)
    diffuse.inputs["Roughness"].default_value = 1.0
    nt.links.new(diffuse.outputs["BSDF"], out.inputs["Surface"])
    return mat


def apply_white_material(body_obj: bpy.types.Object, mat: bpy.types.Material) -> None:
    targets = [body_obj] + list(body_obj.children_recursive)
    for obj in targets:
        if obj.type != "MESH":
            continue
        if len(obj.material_slots) == 0:
            obj.data.materials.append(mat)
            continue
        for idx in range(len(obj.material_slots)):
            obj.material_slots[idx].material = mat


def _prepare_white_mesh_scene(glb_path: Path, fps: int) -> bpy.types.Scene:
    """导入 GLB、白模材质与场景时间轴；不负责设置输出 filepath 或调用 render。"""
    cleanup_body()
    bpy.ops.import_scene.gltf(filepath=str(glb_path))

    body_obj = bpy.data.objects.get("body")
    if body_obj is None:
        raise RuntimeError(f"导入后未找到 body 物体: {glb_path}")
    body_obj.scale = (0.1, 0.1, 0.1)

    white_mat = build_white_diffuse_material()
    apply_white_material(body_obj, white_mat)

    scene = bpy.data.scenes["Scene"]
    scene.render.film_transparent = True
    scene.frame_start = 1
    scene.frame_end = 180
    scene.render.fps = fps
    return scene


@dataclass(frozen=True)
class _RenderOutputSnapshot:
    """Blender 输出面板中与「视频 / 单图」切换相关的字段快照，用于静帧后恢复。"""

    use_file_extension: bool
    file_format: str
    color_mode: str
    color_depth: str
    compression: int
    ffmpeg_format: str
    ffmpeg_codec: str


def _snapshot_render_output(scene: bpy.types.Scene) -> _RenderOutputSnapshot:
    r = scene.render
    img = r.image_settings
    ff = r.ffmpeg
    depth = getattr(img, "color_depth", None)
    comp = getattr(img, "compression", None)
    return _RenderOutputSnapshot(
        use_file_extension=bool(r.use_file_extension),
        file_format=str(img.file_format),
        color_mode=str(img.color_mode),
        color_depth=str(depth) if depth is not None else "8",
        compression=int(comp) if comp is not None else 15,
        ffmpeg_format=str(ff.format),
        ffmpeg_codec=str(ff.codec),
    )


def _restore_render_output(scene: bpy.types.Scene, snap: _RenderOutputSnapshot) -> None:
    """恢复进入 PNG 静帧前的输出配置；经 PNG 过渡再写 color_mode，避免 FFMPEG 下 RGBA 枚举报错。"""
    r = scene.render
    img = r.image_settings
    ff = r.ffmpeg
    r.use_file_extension = snap.use_file_extension
    img.file_format = "PNG"
    img.color_mode = snap.color_mode
    img.file_format = snap.file_format
    if snap.file_format == "FFMPEG":
        ff.format = snap.ffmpeg_format
        ff.codec = snap.ffmpeg_codec
    try:
        img.color_mode = snap.color_mode
    except TypeError:
        pass
    if hasattr(img, "color_depth"):
        try:
            img.color_depth = snap.color_depth
        except TypeError:
            pass
    if hasattr(img, "compression"):
        try:
            img.compression = snap.compression
        except TypeError:
            pass


def _configure_movie_output(scene: bpy.types.Scene, video_path: Path) -> None:
    """动画：FFmpeg 视频模式。PNG 编码须 QuickTime 容器（与 README / 工程一致）。"""
    r = scene.render
    img = r.image_settings
    ff = r.ffmpeg
    img.file_format = "FFMPEG"
    ff.format = "QUICKTIME"
    ff.codec = "PNG"
    img.color_mode = "RGBA"
    r.film_transparent = True
    r.use_file_extension = False
    r.filepath = str(video_path)


def _configure_png_still_output(scene: bpy.types.Scene, still_path: Path) -> None:
    """单帧：PNG 图像模式（非 FFMPEG），与视频输出配置分离。"""
    r = scene.render
    img = r.image_settings
    img.file_format = "PNG"
    img.color_mode = "RGBA"
    if hasattr(img, "color_depth"):
        img.color_depth = "8"
    if hasattr(img, "compression"):
        img.compression = 15
    r.film_transparent = True
    r.use_file_extension = False
    r.filepath = str(still_path)


def _render_white_mesh_still(scene: bpy.types.Scene, still_path: Path) -> None:
    snap = _snapshot_render_output(scene)
    try:
        scene.frame_set(WHITE_MESH_STILL_FRAME)
        _configure_png_still_output(scene, still_path)
        print(
            f"[Stage12] 输出第 {WHITE_MESH_STILL_FRAME} 帧白模 PNG（PNG 图像模式 / RGBA 透明） -> {still_path.name}",
            flush=True,
        )
        bpy.ops.render.render(write_still=True)
        print(f"[OK] {still_path}", flush=True)
    finally:
        _restore_render_output(scene, snap)


def render_one(glb_path: Path, out_dir: Path, fps: int, *, resume: bool = False) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    video_path = out_dir / WHITE_MESH_VIDEO_NAME
    still_path = out_dir / f"white_model_frame_{WHITE_MESH_STILL_FRAME}.png"
    existing_video, existing_is_legacy_mp4 = _existing_white_mesh_video(out_dir)
    video_ok = existing_video is not None
    still_ok = _looks_valid_png(still_path)

    if resume and video_ok and still_ok:
        if existing_is_legacy_mp4:
            print(
                "[WARN] 当前成片为旧路径 "
                f"{LEGACY_WHITE_MESH_VIDEO_NAME}（QuickTime+PNG 却使用 .mp4 扩展名），"
                "剪映等客户端可能按 MP4 解包导致部分帧「媒体格式不支持」。"
                f"请删除该文件后去掉 --resume 重跑 Stage12，以生成 {WHITE_MESH_VIDEO_NAME}。",
                flush=True,
            )
        print(
            f"[SKIP] --resume：已有有效视频与白模图 {still_path.name}（来源 {glb_path.name}）",
            flush=True,
        )
        return

    scene = _prepare_white_mesh_scene(glb_path, fps)

    if resume and video_ok and not still_ok:
        if existing_is_legacy_mp4:
            print(
                "[WARN] 成片仍为旧路径 "
                f"{LEGACY_WHITE_MESH_VIDEO_NAME}；补渲 PNG 后建议删除该 .mp4 并无 --resume 重渲，"
                f"以生成 {WHITE_MESH_VIDEO_NAME}，避免剪映对部分帧报错。",
                flush=True,
            )
        print(
            f"[RUN] --resume：视频已存在，仅补渲白模 PNG（不重渲视频），来源 {glb_path.name}",
            flush=True,
        )
        _render_white_mesh_still(scene, still_path)
        return

    _configure_movie_output(scene, video_path)
    print(
        f"[Stage12] 渲染白模视频（FFmpeg 视频模式：QuickTime + PNG + RGBA，来源 {glb_path.name}） -> {video_path.name}",
        flush=True,
    )
    bpy.ops.render.render(animation=True)
    print(f"[OK] {video_path}", flush=True)
    _render_white_mesh_still(scene, still_path)


def main() -> None:
    args = parse_cli_args()
    input_root = resolve_input_root(args)
    tasks = collect_glbs(input_root)
    only_stem = (args.only_glb_stem or "").strip()
    if only_stem:
        tasks = [(g, o) for g, o in tasks if g.stem == only_stem]
    elif len(tasks) > 1:
        # 白模视频不包含纹理风格，默认仅导出单个 white_model.mov，避免重复覆盖。
        print(
            f"[RUN] 发现 {len(tasks)} 个 GLB；Stage12 默认仅输出一个 white_model.mov，"
            f"将使用首个模型: {tasks[0][0].name}",
            flush=True,
        )
        tasks = tasks[:1]
    if not tasks:
        print("[DONE] 没有可渲染的 Stage8 GLB。", flush=True)
        return

    print(f"[RUN] Stage12 输入根目录: {input_root}", flush=True)
    print(f"[RUN] 待渲染 {len(tasks)} 个白模视频（1-180 帧）", flush=True)
    ensure_cycles_cuda()
    for glb, out in tasks:
        render_one(glb, out, fps=args.fps, resume=bool(args.resume))


if __name__ == "__main__":
    main()

