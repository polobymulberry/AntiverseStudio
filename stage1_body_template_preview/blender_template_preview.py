"""Stage 1: Render default preview image for each clothing template.

Run example（需 ``--python-use-system-env`` 以加载 ``pip install --user`` 的包，见 README）：
blender -b --python-use-system-env resource/blender/body_template_preview.blend \\
  -P stage1_body_template_preview/blender_template_preview.py

只渲若干套（``template_root`` 下子目录 basename，可多个）：

blender -b --python-use-system-env resource/blender/body_template_preview.blend \\
  -P stage1_body_template_preview/blender_template_preview.py -- --templates body_05

仅做导入前提检查（不渲染）：验证导入后场景里是否存在名为 ``body`` 的根物体（与贴图、Blender GLB 渲染脚本一致）：

blender -b --python-use-system-env resource/blender/body_template_preview.blend \\
  -P stage1_body_template_preview/blender_template_preview.py -- --check-prerequisite

当前从 ``high_poly/body.obj`` 导入；若以后改为 ``body.glb``，仍应保证导入后根对象名为 ``body``。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Blender 内嵌 Python 默认不包含仓库根目录，须先加入才能 import common
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import bpy

from common.settings import SETTINGS
from common.utils import ensure_dir


def parse_cli_args() -> argparse.Namespace:
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1 :]
    else:
        argv = []
    parser = argparse.ArgumentParser(description="Stage1 模板预览渲染 / 前提检查")
    parser.add_argument(
        "--check-prerequisite",
        action="store_true",
        help="仅检查：每个模板导入模型后是否存在名为 body 的对象；不渲染；任一项失败则退出码 1",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=3,
        metavar="N",
        help="每个模板渲染失败（异常或输出无效）时最多尝试次数，默认 3",
    )
    parser.add_argument(
        "--min-output-bytes",
        type=int,
        default=1024,
        metavar="B",
        help="认为 PNG 有效的最小字节数，过小则判失败并重试，默认 1024",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="若输出 PNG 已存在且大于等于 min-output-bytes，则跳过该模板（用于补跑失败项）",
    )
    parser.add_argument(
        "--templates",
        nargs="+",
        default=None,
        metavar="DIR_NAME",
        help="只处理这些模板目录名（须为 BODY_TEMPLATE_ROOT 下直接子目录的 basename）；默认处理全部子目录",
    )
    return parser.parse_args(argv)


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


def cleanup_body() -> None:
    if "body" not in bpy.data.objects:
        return
    obj = bpy.data.objects["body"]
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    for child in obj.children_recursive:
        child.select_set(True)
    bpy.ops.object.delete()


def model_path_for_template(template_dir: Path) -> Path | None:
    p = template_dir / "high_poly" / "body.obj"
    return p if p.is_file() else None


def list_template_dirs(*, only_names: frozenset[str] | None) -> tuple[list[Path], frozenset[str]]:
    """返回 (待处理目录列表, 请求但未找到的模板名)。

    原始几何来自环境变量 ``BODY_TEMPLATE_ROOT``（见 ``common.settings.SETTINGS.template_root``）
    下各 ``<模板名>/high_poly/body.obj``。
    """
    all_dirs = sorted(p for p in SETTINGS.template_root.iterdir() if p.is_dir())
    if only_names is None:
        return all_dirs, frozenset()
    by_name = {p.name: p for p in all_dirs}
    ordered: list[Path] = []
    for name in sorted(only_names):
        p = by_name.get(name)
        if p is not None:
            ordered.append(p)
    missing = frozenset(n for n in only_names if n not in by_name)
    return ordered, missing


def import_model(model_path: Path) -> None:
    cleanup_body()
    bpy.ops.wm.obj_import(filepath=str(model_path))


def body_object_exists() -> bool:
    return bpy.data.objects.get("body") is not None


def tweak_body_materials(body_obj) -> None:
    """将 body 及其子网格上原理化 BSDF 的 Metallic/Roughness 固定为与环绕渲染一致。"""
    all_objects = [body_obj] + list(body_obj.children_recursive)
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
                    print(f"已修改材质: {slot.material.name}")


def _render_one_attempt(model_path: Path, out_path: Path) -> None:
    import_model(model_path)
    body_obj = bpy.data.objects.get("body")
    if body_obj:
        tweak_body_materials(body_obj)
    bpy.context.scene.render.filepath = str(out_path)
    ret = bpy.ops.render.render(write_still=True)
    if ret != {"FINISHED"}:
        raise RuntimeError(f"bpy.ops.render.render 返回 {ret!r}，预期 {{'FINISHED'}}")
    if not out_path.is_file():
        raise RuntimeError("渲染结束但输出文件不存在")
    size = out_path.stat().st_size
    if size < 1:
        raise RuntimeError(f"输出文件大小为 0: {out_path}")


def render_template(
    template_dir: Path,
    output_dir: Path,
    *,
    max_attempts: int,
    min_output_bytes: int,
    resume: bool,
) -> tuple[bool, str]:
    """返回 (是否达成有效输出, 失败原因说明)。成功时第二项为空字符串。"""
    out_path = output_dir / f"{template_dir.name}.png"
    model_path = model_path_for_template(template_dir)
    if model_path is None:
        return False, "缺少 high_poly/body.obj"

    if resume and out_path.is_file() and out_path.stat().st_size >= min_output_bytes:
        cleanup_body()
        return True, ""

    last_reason = ""
    for attempt in range(1, max_attempts + 1):
        try:
            _render_one_attempt(model_path, out_path)
            sz = out_path.stat().st_size
            if sz < min_output_bytes:
                raise RuntimeError(f"输出 PNG 过小 ({sz} bytes)，可能未正确渲染")
            cleanup_body()
            return True, ""
        except Exception as exc:  # noqa: BLE001
            last_reason = f"{type(exc).__name__}: {exc}"
            print(f"[WARN] {template_dir.name} 第 {attempt}/{max_attempts} 次失败: {last_reason}")
            cleanup_body()
            try:
                if out_path.is_file():
                    out_path.unlink()
            except OSError:
                pass

    return False, last_reason or "未知错误"


def check_prerequisites_for_all_templates(*, only_names: frozenset[str] | None = None) -> int:
    """导入每个模板的模型，确认存在名为 body 的根物体后清理；不渲染。"""
    template_dirs, missing = list_template_dirs(only_names=only_names)
    if missing:
        print(f"[WARN] 以下名称不在 template_root 下，已忽略: {', '.join(sorted(missing))}", flush=True)
    failures: list[str] = []
    skipped: list[str] = []

    for template_dir in template_dirs:
        model_path = model_path_for_template(template_dir)
        if model_path is None:
            skipped.append(template_dir.name)
            print(f"[SKIP] {template_dir.name} 缺少 high_poly/body.obj")
            continue
        import_model(model_path)
        if not body_object_exists():
            failures.append(template_dir.name)
            print(f"[PREREQ FAIL] {template_dir.name} 导入后不存在名为 body 的根物体")
        else:
            print(f"[PREREQ OK] {template_dir.name}")
        cleanup_body()

    if skipped:
        print(f"未检查（缺模型）: {len(skipped)} 个")
    if failures:
        print(f"前提检查失败: {len(failures)} 个 -> {', '.join(failures)}")
        return 1
    checked = len(template_dirs) - len(skipped)
    print(f"前提检查通过（已检查 {checked} 个模板）")
    return 0


def main() -> None:
    args = parse_cli_args()
    only: frozenset[str] | None = None
    if args.templates:
        only = frozenset(x.strip() for x in args.templates if x.strip())
        if not only:
            only = None
    if args.check_prerequisite:
        raise SystemExit(check_prerequisites_for_all_templates(only_names=only))

    output_dir = ensure_dir(SETTINGS.output_root / "stage1_body_template_preview")
    ensure_cycles_cuda()

    template_dirs, missing = list_template_dirs(only_names=only)
    if missing:
        print(f"[WARN] 以下名称不在 template_root 下，已忽略: {', '.join(sorted(missing))}", flush=True)
    if only:
        print(f"[INFO] template_root={SETTINGS.template_root}", flush=True)
        print(f"[INFO] 仅渲染: {', '.join(p.name for p in template_dirs) or '（无匹配目录）'}", flush=True)
    success = 0
    skipped_resume = 0
    failed: list[str] = []

    for template_dir in template_dirs:
        out_path = output_dir / f"{template_dir.name}.png"
        resume_hit = (
            args.resume
            and out_path.is_file()
            and out_path.stat().st_size >= args.min_output_bytes
        )
        ok, reason = render_template(
            template_dir,
            output_dir,
            max_attempts=args.max_attempts,
            min_output_bytes=args.min_output_bytes,
            resume=args.resume,
        )
        if ok:
            success += 1
            if resume_hit:
                skipped_resume += 1
                print(f"[OK] {template_dir.name} (--resume 已有有效 PNG，跳过渲染)")
            else:
                print(f"[OK] {template_dir.name}")
        else:
            failed.append(f"{template_dir.name}: {reason}")
            print(f"[FAIL] {template_dir.name}: {reason}")

    print(
        f"Stage1 完成: 有效输出 {success}/{len(template_dirs)}"
        + (f"（其中 --resume 跳过 {skipped_resume} 个）" if skipped_resume else "")
    )
    if failed:
        print(f"仍失败 {len(failed)} 个（可增大 --max-attempts 或检查 GPU/显存/模型）：")
        for line in failed:
            print(f"  - {line}")


if __name__ == "__main__":
    main()

