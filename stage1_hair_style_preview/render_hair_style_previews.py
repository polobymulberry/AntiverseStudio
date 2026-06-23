"""发型纯预览：从 ``solid_hair/*/low_poly/hair.obj`` 导入；**默认隐藏**场景中已有 ``body``，将发型根物体 Z 设为 -4 后渲染 PNG；
导入的头发网格上 **Principled BSDF：Metallic=0、Roughness=1**（与 Stage1 身体预览一致）。

运行示例（Blender 自带 Python 需能 import 仓库 ``common``，见 README ``--python-use-system-env``）：

```bash
blender -b --python-use-system-env resource/blender/body_template_preview.blend \\
  -P stage1_hair_style_preview/render_hair_style_previews.py -- \\
  --output-dir resource/blender/solid_hair_preview/hair_style
```

默认输出至仓库内 ``resource/blender/solid_hair_preview/hair_style/<发型目录名>.png``。

若成片「全透明」，多为工程中 ``film_transparent`` 未关闭；本脚本会在渲染前强制 **不透明 RGB PNG**。
调试可加 ``--no-hide-body`` 保留场景中 ``body``，确认取景与导入是否正常。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import bpy

from common.hair_assets import hair_root_dir
from common.utils import ensure_dir


def parse_cli_args() -> argparse.Namespace:
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1 :]
    else:
        argv = []
    parser = argparse.ArgumentParser(description="solid_hair 发型预览 PNG 批量渲染")
    parser.add_argument(
        "--blend-file",
        default=str(_REPO_ROOT / "resource" / "blender" / "body_template_preview.blend"),
        help="起始 Blender 工程路径",
    )
    parser.add_argument(
        "--hair-root",
        default="",
        help="solid_hair 根目录；默认 resource/blender/solid_hair",
    )
    parser.add_argument(
        "--output-dir",
        default=str(_REPO_ROOT / "resource" / "blender" / "solid_hair_preview" / "hair_style"),
        help="PNG 输出目录（每个子目录名对应一张图）",
    )
    parser.add_argument(
        "--z-offset",
        type=float,
        default=-4.0,
        help="导入后发型根级物体 location.z，默认 -4",
    )
    parser.add_argument(
        "--only",
        default="",
        metavar="NAME",
        help="仅处理 solid_hair 下某一子目录名",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="若目标 PNG 已存在且非空则跳过",
    )
    parser.add_argument(
        "--min-output-bytes",
        type=int,
        default=1024,
        metavar="B",
        help="判定 PNG 有效的最小字节数",
    )
    parser.add_argument(
        "--no-hide-body",
        action="store_true",
        help="不隐藏场景中的 body（用于排查取景/导入；默认仍会隐藏以便只看头发）",
    )
    return parser.parse_args(argv)


def configure_opaque_png_render(scene: bpy.types.Scene) -> None:
    """与 Stage1 身体预览一致：关闭胶片透明，输出 RGB PNG（避免工程内预设导致全透明）。"""
    scene.render.film_transparent = False
    img = scene.render.image_settings
    img.file_format = "PNG"
    img.color_mode = "RGB"
    if hasattr(img, "color_depth"):
        img.color_depth = "8"


def ensure_cycles_cuda() -> None:
    scene = bpy.context.scene
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
        print("Cycles CUDA 已启用。")
    except Exception as exc:  # pragma: no cover
        print(f"未启用 CUDA，将使用 Blender 默认设置: {exc}")


def _hide_body_if_present() -> bpy.types.Object | None:
    obj = bpy.data.objects.get("body")
    if obj is None:
        return None
    obj.hide_render = True
    obj.hide_viewport = True
    return obj


def _unhide_body(obj: bpy.types.Object | None) -> None:
    if obj is None:
        return
    obj.hide_render = False
    obj.hide_viewport = False


def _delete_imported_objects(imported_objs: list[bpy.types.Object]) -> None:
    """删除本次导入的子图（仅删顶层根，子级随 Blender 一并移除）。"""
    imp_set = set(imported_objs)
    roots = [o for o in imported_objs if o.parent is None or o.parent not in imp_set]
    bpy.ops.object.select_all(action="DESELECT")
    for o in roots:
        if o.name in bpy.data.objects:
            o.select_set(True)
    if bpy.context.selected_objects:
        bpy.ops.object.delete()


def tweak_hair_materials(root: bpy.types.Object) -> None:
    """头发及其子网格：原理化 BSDF Metallic=0、Roughness=1。"""
    all_objects = [root] + list(root.children_recursive)
    for obj in all_objects:
        if obj.type != "MESH":
            continue
        for slot in obj.material_slots:
            if slot.material and slot.material.use_nodes:
                nodes = slot.material.node_tree.nodes
                bsdf = next((n for n in nodes if n.type == "BSDF_PRINCIPLED"), None)
                if bsdf:
                    bsdf.inputs["Metallic"].default_value = 0.0
                    bsdf.inputs["Roughness"].default_value = 1.0


def import_hair_objects(obj_path: Path) -> tuple[list[bpy.types.Object], list[bpy.types.Object]]:
    """返回 (本次导入的全部物体, 根级物体列表)。"""
    before_ids = {id(o) for o in bpy.data.objects}
    try:
        bpy.ops.wm.obj_import(filepath=str(obj_path))
    except AttributeError:
        bpy.ops.import_scene.obj(filepath=str(obj_path), axis_forward="-Z", axis_up="Y")
    new_objs = [o for o in bpy.data.objects if id(o) not in before_ids]
    new_set = set(new_objs)
    roots = [o for o in new_objs if o.parent is None or o.parent not in new_set]
    return new_objs, roots


def render_one(
    _hair_subdir_name: str,
    obj_path: Path,
    out_png: Path,
    *,
    z_offset: float,
    min_bytes: int,
    hide_body: bool,
) -> tuple[bool, str]:
    body_ref = _hide_body_if_present() if hide_body else None
    imported_objs, roots = import_hair_objects(obj_path)

    if not roots:
        _delete_imported_objects(imported_objs)
        if hide_body:
            _unhide_body(body_ref)
        return False, "OBJ 导入后未解析到根级物体（可能导入失败或层级异常）"

    for r in roots:
        r.location.z = float(z_offset)
        r.hide_render = False
        r.hide_viewport = False
        tweak_hair_materials(r)

    print(
        f"[DEBUG] 头发根物体数={len(roots)}；首根 location={tuple(roots[0].location)} "
        f"scale={tuple(roots[0].scale)} z_offset={z_offset}",
        flush=True,
    )

    scene = bpy.context.scene
    configure_opaque_png_render(scene)
    scene.render.filepath = str(out_png)
    ret = bpy.ops.render.render(write_still=True)
    ok = ret == {"FINISHED"} and out_png.is_file() and out_png.stat().st_size >= min_bytes

    _delete_imported_objects(imported_objs)
    if hide_body:
        _unhide_body(body_ref)

    if not ok:
        return False, f"渲染失败或 PNG 过小: {out_png}"
    return True, ""


def main() -> None:
    args = parse_cli_args()
    hair_root = Path(args.hair_root).expanduser().resolve() if args.hair_root else hair_root_dir(_REPO_ROOT)
    out_dir = ensure_dir(Path(args.output_dir).expanduser().resolve())

    if not hair_root.is_dir():
        print(f"[ERROR] solid_hair 根目录不存在: {hair_root}", file=sys.stderr)
        sys.exit(1)

    blend_path = Path(args.blend_file).expanduser().resolve()
    if not blend_path.is_file():
        print(
            f"[ERROR] 未找到 Blender 工程: {blend_path}\n"
            "请将 body_template_preview.blend 置于 resource/blender/ 或通过 --blend-file 指定。",
            file=sys.stderr,
        )
        sys.exit(1)

    subdirs = sorted(p for p in hair_root.iterdir() if p.is_dir())
    only = (args.only or "").strip()
    if only:
        subdirs = [p for p in subdirs if p.name == only]
        if not subdirs:
            print(f"[ERROR] --only={only!r} 在 {hair_root} 下未找到。", file=sys.stderr)
            sys.exit(1)

    ensure_cycles_cuda()

    ok_n = 0
    skip_n = 0
    fail: list[str] = []

    for d in subdirs:
        obj_path = d / "low_poly" / "hair.obj"
        stem = d.name
        out_png = out_dir / f"{stem}.png"
        if not obj_path.is_file():
            print(f"[SKIP] {stem} 缺少 {obj_path.relative_to(d)}")
            continue
        if args.resume and out_png.is_file() and out_png.stat().st_size >= args.min_output_bytes:
            print(f"[SKIP] {stem} 已有 PNG (--resume)")
            skip_n += 1
            ok_n += 1
            continue
        try:
            good, msg = render_one(
                stem,
                obj_path,
                out_png,
                z_offset=args.z_offset,
                min_bytes=args.min_output_bytes,
                hide_body=not args.no_hide_body,
            )
            if good:
                ok_n += 1
                print(f"[OK] {stem} -> {out_png}")
            else:
                fail.append(f"{stem}: {msg}")
                print(f"[FAIL] {stem}: {msg}")
        except Exception as exc:  # noqa: BLE001
            fail.append(f"{stem}: {exc}")
            print(f"[FAIL] {stem}: {type(exc).__name__}: {exc}")

    print(
        f"完成: 成功/跳过 {ok_n}，失败 {len(fail)}，共扫描目录 {len(subdirs)} 个（hair_root={hair_root}）"
    )
    if fail:
        sys.exit(1)


if __name__ == "__main__":
    main()
