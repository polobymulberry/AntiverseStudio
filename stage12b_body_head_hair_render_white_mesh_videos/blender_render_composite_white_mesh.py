"""Stage 12b：白模身体 + 白模贴图头发 + 真人头（白模）合成透明视频。

在 ``resource/blender/render_around_white_mesh.blend`` 中运行（与 Stage12 相同入口习惯）：

```bash
blender -b --python-use-system-env resource/blender/render_around_white_mesh.blend \\
  -P stage12b_body_head_hair_render_white_mesh_videos/blender_render_composite_white_mesh.py -- \\
  --fashion-tag <TAG> --template <BODY_TEMPLATE>
```

多 GLB 时可用 ``--workers N``（默认 **6**，或由环境 ``BLENDER_WORKERS`` 覆盖）拉起多个 Blender 子进程，各处理 ``stem`` 分片；与 ``scripts/blender_render_pool.py`` 及 ``common/blender_render_pool_lease`` 的渲片租约一致。

依赖 ``pipeline_render_prefs.yml`` 中 ``head_object``、``hair_object``（solid 发型子目录名）与同主题下 Stage8 身体 ``*.glb``；头发使用 ``resource/blender/solid_hair/<hair_object>/low_poly/hair.obj`` 导入后统一白模材质（与身体一致），**不再**依赖 Stage8b 贴图头发 GLB。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import bpy

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from common.blender_cycles_gpu import ensure_cycles_cuda
from common.blender_render_pool_lease import compute_spawn_worker_count
from common.pipeline_render_prefs import load_render_prefs_dict, pipeline_render_prefs_path
from common.real_head_assets import resolve_existing_real_head_mesh
from common.settings import SETTINGS
from common.utils import body_template_run_dir

from stage12_render_white_mesh_videos.blender_render_white_mesh_videos import (
    WHITE_MESH_STILL_FRAME,
    WHITE_MESH_VIDEO_NAME,
    _configure_movie_output,
    _configure_png_still_output,
    _existing_white_mesh_video,
    _looks_valid_png,
    _restore_render_output,
    _snapshot_render_output,
    apply_white_material,
    build_white_diffuse_material,
    cleanup_body,
)


_STAGE12B_JSON_ENV = "STAGE12B_JSON"


def parse_cli_args() -> argparse.Namespace:
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1 :]
    else:
        argv = []
    parser = argparse.ArgumentParser(description="Stage12b 身体+头发+头白模合成")
    parser.add_argument("--fashion-tag", required=True)
    parser.add_argument("--template", required=True)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--only-glb-stem", default=None)
    parser.add_argument(
        "--workers",
        type=int,
        default=max(1, int(os.environ.get("BLENDER_WORKERS", "6"))),
        help=(
            "Stage8 下多个 GLB 时并行 Blender 子进程数（默认 6，可由 BLENDER_WORKERS 覆盖）；"
            "受 BLENDER_POOL_MAX 渲片租约约束时实际启动数可能更少。"
        ),
    )
    return parser.parse_args(argv)


def args_to_dict(ns: argparse.Namespace | SimpleNamespace) -> dict[str, object]:
    only = getattr(ns, "only_glb_stem", None)
    only_s = str(only).strip() if only is not None else ""
    return {
        "fashion_tag": str(ns.fashion_tag),
        "template": str(ns.template),
        "fps": int(ns.fps),
        "resume": bool(getattr(ns, "resume", False)),
        "only_glb_stem": only_s or None,
        "workers": int(ns.workers),
    }


def args_from_stage12b_json() -> SimpleNamespace:
    raw = (os.environ.get(_STAGE12B_JSON_ENV) or "").strip()
    if not raw:
        raise SystemExit(
            f"子进程缺少环境变量 {_STAGE12B_JSON_ENV}，请由父进程启动或使用 -- 传参单进程运行。"
        )
    data = json.loads(raw)
    data.setdefault("only_glb_stem", None)
    data.setdefault("resume", False)
    data.setdefault("fps", 30)
    data.setdefault("workers", 6)
    ft = str(data.get("fashion_tag") or "").strip()
    tpl = str(data.get("template") or "").strip()
    if not ft or not tpl:
        raise SystemExit(f"{_STAGE12B_JSON_ENV} 缺少 fashion_tag 或 template")
    data["fashion_tag"] = ft
    data["template"] = tpl
    return SimpleNamespace(**data)


def tasks_for_worker_glbs(glbs: list[Path], worker_id: int, worker_count: int) -> list[Path]:
    return [g for i, g in enumerate(glbs) if i % worker_count == worker_id]


def spawn_parallel_blenders(worker_count: int, config_json: str) -> int:
    blend = (bpy.data.filepath or os.environ.get("BLENDER_BLEND", "")).strip()
    if not blend:
        raise SystemExit(
            "多进程需要 .blend 路径：请使用 blender -b --python-use-system-env "
            "resource/blender/render_around_white_mesh.blend "
            "-P stage12b_body_head_hair_render_white_mesh_videos/blender_render_composite_white_mesh.py，"
            "或设置环境变量 BLENDER_BLEND=/绝对路径/scene.blend"
        )
    blend = os.path.abspath(blend)
    script = os.path.abspath(__file__)
    exe = bpy.app.binary_path
    effective = int(compute_spawn_worker_count(worker_count))
    if effective < worker_count:
        print(
            f"[租约] 全局并行渲槽紧张（BLENDER_POOL_MAX），本次仅启动 {effective}/{worker_count} "
            "个子 Blender；分片仍正确（少进程时由单 worker 顺序处理多片）。",
            flush=True,
        )
    print(f"父进程：将启动 {effective} 个 Blender 子进程（请求 {worker_count}）", flush=True)
    print(f"  blend={blend}")
    print(f"  script={script}")
    procs: list[subprocess.Popen] = []
    for wid in range(effective):
        env = os.environ.copy()
        env["BLENDER_WORKER_ID"] = str(wid)
        env["BLENDER_WORKERS"] = str(effective)
        env[_STAGE12B_JSON_ENV] = config_json
        cmd = [exe, "-b", "--python-use-system-env", blend, "-P", script]
        procs.append(subprocess.Popen(cmd, env=env))
    codes: list[int] = []
    for wid, p in enumerate(procs):
        rc = p.wait()
        codes.append(int(rc))
        print(f"子进程 worker {wid} 退出码: {rc}", flush=True)
    return max(codes) if codes else 0


def cleanup_imported_roots(mark_key: str) -> None:
    for obj in list(bpy.data.objects):
        if obj.get(mark_key):
            bpy.data.objects.remove(obj, do_unlink=True)


def import_glb_scaled(
    abs_path: Path, *, mark: str, scale: tuple[float, float, float]
) -> list[bpy.types.Object]:
    before = {id(o) for o in bpy.data.objects}
    bpy.ops.import_scene.gltf(filepath=str(abs_path.resolve()).replace("\\", "/"))
    new_objs = [o for o in bpy.data.objects if id(o) not in before]
    new_set = set(new_objs)
    roots: list[bpy.types.Object] = []
    for o in new_objs:
        if o.parent is None or o.parent not in new_set:
            o.scale = scale
            o[mark] = 1
            roots.append(o)
    return roots


def import_real_head_white(template_id: str, white_mat: bpy.types.Material) -> None:
    tid = template_id.strip().zfill(6)
    rh = resolve_existing_real_head_mesh(SETTINGS.real_head_120k_root, tid)
    if rh is None:
        print(f"[ERROR] 未找到真人头部 mesh template_id={tid}", file=sys.stderr)
        sys.exit(1)
    before = {id(o) for o in bpy.data.objects}
    fp = str(rh.resolve()).replace("\\", "/")
    if rh.suffix.lower() == ".glb":
        bpy.ops.import_scene.gltf(filepath=fp)
    else:
        try:
            bpy.ops.wm.obj_import(filepath=fp)
        except AttributeError:
            bpy.ops.import_scene.obj(filepath=fp, axis_forward="-Z", axis_up="Y")
    new_objs = [o for o in bpy.data.objects if id(o) not in before]
    for o in new_objs:
        o["real_head_white"] = 1
    new_set = set(new_objs)
    roots = [o for o in new_objs if o.parent is None or o.parent not in new_set]
    for o in roots:
        o.scale = (0.1, 0.1, 0.1)
        apply_white_material(o, white_mat)


def import_solid_hair_white(hair_style_id: str, repo_root: Path, white_mat: bpy.types.Material) -> None:
    """导入 solid 发型 OBJ，缩放与身体一致并套白模材质。"""
    from common.hair_assets import solid_hair_obj_path

    sp = solid_hair_obj_path(repo_root, hair_style_id)
    if sp is None:
        print(f"[ERROR] solid 发型 mesh 不存在: {hair_style_id!r}", file=sys.stderr)
        sys.exit(1)
    cleanup_imported_roots("solid_hair_stage12b")
    before = {id(o) for o in bpy.data.objects}
    fp = str(sp.resolve()).replace("\\", "/")
    try:
        bpy.ops.wm.obj_import(filepath=fp)
    except AttributeError:
        bpy.ops.import_scene.obj(filepath=fp, axis_forward="-Z", axis_up="Y")
    new_objs = [o for o in bpy.data.objects if id(o) not in before]
    for o in new_objs:
        o["solid_hair_stage12b"] = 1
    new_set = set(new_objs)
    roots = [o for o in new_objs if o.parent is None or o.parent not in new_set]
    for root in roots:
        root.scale = (0.1, 0.1, 0.1)
    if roots:
        apply_white_material(roots[0], white_mat)
    else:
        for o in new_objs:
            if o.type == "MESH":
                apply_white_material(o, white_mat)
                break


def render_composite(
    body_glb: Path,
    hair_style_id: str,
    repo_root: Path,
    out_dir: Path,
    head_tid: str,
    fps: int,
    *,
    resume: bool,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    video_path = out_dir / WHITE_MESH_VIDEO_NAME
    still_path = out_dir / f"white_body_head_hair_frame_{WHITE_MESH_STILL_FRAME}.png"
    existing_video, legacy = _existing_white_mesh_video(out_dir)
    if resume and existing_video and _looks_valid_png(still_path):
        print("[SKIP] Stage12b 已有视频与白模静帧", flush=True)
        return

    cleanup_body()
    cleanup_imported_roots("solid_hair_stage12b")
    cleanup_imported_roots("real_head_white")

    white_mat = build_white_diffuse_material("Stage12b_WhiteDiffuse")

    body_roots = import_glb_scaled(body_glb, mark="body_white_stage12b", scale=(0.1, 0.1, 0.1))
    body_obj = bpy.data.objects.get("body")
    if body_obj is None and body_roots:
        body_obj = body_roots[0]
    if body_obj is None:
        raise RuntimeError(f"导入身体 GLB 失败: {body_glb}")
    apply_white_material(body_obj, white_mat)

    import_solid_hair_white(hair_style_id, repo_root, white_mat)

    import_real_head_white(head_tid, white_mat)

    scene = bpy.context.scene
    scene.render.film_transparent = True
    scene.frame_start = 1
    scene.frame_end = 180
    scene.render.fps = fps
    if body_obj:
        cam = bpy.data.cameras.get("Camera")
        if cam:
            cam.dof.focus_object = body_obj

    _configure_movie_output(scene, video_path)
    print(f"[Stage12b] 渲染合成白模视频 -> {video_path.name}", flush=True)
    bpy.ops.render.render(animation=True)
    snap = _snapshot_render_output(scene)
    try:
        scene.frame_set(WHITE_MESH_STILL_FRAME)
        _configure_png_still_output(scene, still_path)
        bpy.ops.render.render(write_still=True)
    finally:
        _restore_render_output(scene, snap)
    print(f"[OK] Stage12b -> {video_path}", flush=True)


def run_stage12b_glbs(
    body_glbs: list[Path],
    *,
    run_dir: Path,
    head_obj: str,
    hair_id: str,
    fps: int,
    resume: bool,
) -> None:
    """对给定 GLB 列表依次渲染（单 Blender 进程内）。"""
    out_root = run_dir / "stage12b_body_head_hair_render_white_mesh_videos"
    out_root.mkdir(parents=True, exist_ok=True)
    ensure_cycles_cuda()
    for body_glb in body_glbs:
        sub_out = out_root / body_glb.stem
        sub_out.mkdir(parents=True, exist_ok=True)
        render_composite(
            body_glb,
            hair_id,
            _REPO_ROOT,
            sub_out,
            head_obj,
            fps,
            resume=resume,
        )


def main() -> None:
    worker_id_env = os.environ.get("BLENDER_WORKER_ID")
    if worker_id_env is not None:
        args = args_from_stage12b_json()
    else:
        args = parse_cli_args()

    run_dir = body_template_run_dir(SETTINGS.output_root, args.fashion_tag, args.template)
    prefs = pipeline_render_prefs_path(run_dir.parent)
    pdata = load_render_prefs_dict(prefs) if prefs.is_file() else {}
    head_obj = str(pdata.get("head_object") or "").strip()
    if not head_obj:
        print("[ERROR] YAML 缺少 head_object（真人 template_id）", file=sys.stderr)
        sys.exit(1)

    hair_id = str(pdata.get("hair_object") or "").strip()
    if not hair_id:
        print("[ERROR] YAML 缺少 hair_object（发型 id）", file=sys.stderr)
        sys.exit(1)

    stage8_dir = run_dir / "stage8_new_texture_model_generation"
    if not stage8_dir.is_dir():
        print(f"[ERROR] 缺少目录: {stage8_dir}", file=sys.stderr)
        sys.exit(1)
    glbs = sorted(stage8_dir.glob("*.glb"))
    only = (args.only_glb_stem or "").strip()
    if only:
        glbs = [p for p in glbs if p.stem == only]
    if not glbs:
        print("[ERROR] stage8 下无 GLB", file=sys.stderr)
        sys.exit(1)

    (run_dir / "stage12b_body_head_hair_render_white_mesh_videos").mkdir(parents=True, exist_ok=True)

    workers = max(1, int(os.environ.get("BLENDER_WORKERS", str(args.workers))))

    if worker_id_env is not None:
        from common.blender_render_pool_lease import acquire_render_slot, release_render_slot

        wid = int(worker_id_env)
        chunk = tasks_for_worker_glbs(glbs, wid, workers)
        print(f"Worker {wid}/{workers}，GLB 数 {len(chunk)}", flush=True)
        acquire_render_slot()
        try:
            run_stage12b_glbs(
                chunk,
                run_dir=run_dir,
                head_obj=head_obj,
                hair_id=hair_id,
                fps=int(args.fps),
                resume=bool(args.resume),
            )
        finally:
            release_render_slot()
        return

    if workers > 1:
        config_json = json.dumps(args_to_dict(args), ensure_ascii=False)
        rc = spawn_parallel_blenders(workers, config_json)
        if rc != 0:
            sys.exit(rc)
        return

    from common.blender_render_pool_lease import acquire_render_slot, release_render_slot

    acquire_render_slot()
    try:
        run_stage12b_glbs(
            glbs,
            run_dir=run_dir,
            head_obj=head_obj,
            hair_id=hair_id,
            fps=int(args.fps),
            resume=bool(args.resume),
        )
    finally:
        release_render_slot()


if __name__ == "__main__":
    main()
