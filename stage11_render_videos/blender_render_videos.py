"""Stage9（封面）与 Stage11（环绕视频）：工程 resource/blender/blender_render_videos.blend

- --pass covers：为 stage8 下各 GLB 渲第 18 帧：``<label>_cover.png``（带 Studio 背景）与 ``<label>_cover_rgba.png``（Cylinder 背景集合 **Holdout** + 胶片透明 PNG RGBA）。``--resume`` 时二者分别判断，缺谁补谁。
- --pass videos：仅对 ``stage10_render_covers_selected/`` 中出现的 ``*_cover.png`` 所对应的模型渲 mp4 到 ``.../stage11_render_videos/``（当前流程约定目录内约 **6** 张已选封面，对应正片 **5** 套 + 备损 **1** 套）。可用 ``--all-glbs`` 恢复「全部 GLB 都渲」的旧行为（仍输出到 stage11）。可用 ``--only-glb-stems 'A,B'`` 再限定其中若干 GLB 主名（逗号分隔），与 ``--workers`` 多进程兼容。

Studio 背景墙 ``Studio_Fabric_1.001`` 的 **Tint** 颜色默认使用本脚本内 ``HEX_COLORS`` 首项，可用 ``--studio-tint-hex`` 固定，避免多模型时随机色导致成片割裂。子进程经 STAGE11_JSON 或（兼容）STAGE9_JSON 收参。

当同时使用 ``--template`` 与 ``--user-requirement`` 或 ``--fashion-tag`` 时，启动即同步 ``pipeline_render_prefs.yml``：无则创建；CLI 有指定则覆盖写回；否则用文件或随机/默认并立即落盘。之后可省略上述三参数。

``hair_object`` 可为 ``resource/blender/solid_hair/<子目录>/low_poly/hair.obj`` 的目录名（如 ``female_hair_01``），由本脚本导入 OBJ；``hair_color`` 为发色名（见 ``common/hair_assets.HAIR_COLORS``）。无需手改 ``blender_render_videos.blend``。

Run (封面):
  blender -b --python-use-system-env resource/blender/blender_render_videos.blend \\
    -P stage11_render_videos/blender_render_videos.py -- \\
    --pass covers --template ... --fashion-tag ... \\
    （若已有 ``pipeline_render_prefs.yml`` 可无 --head-object / --hair-object）

Run (正片，仅已选):
  ... --pass videos --studio-tint-hex '#E3D9C6' ...

Run (正片，只渲指定服装名，可多选逗号分隔，可与 --workers 并发):
  ... --pass videos --only-glb-stems '蜡笔小新,邋遢大王' ...

临时改输出目录（默认不写）：``--render-output-dir /path/to/dir``
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import bpy

# Blender 内嵌 Python 默认不包含仓库根目录，须先加入才能 import common
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from common.blender_cycles_gpu import ensure_cycles_cuda
from common.blender_render_pool_lease import compute_spawn_worker_count
from common.hair_assets import hex_to_rgb01, resolve_hair_hex, solid_hair_obj_path
from common.pipeline_render_prefs import sync_pipeline_render_prefs_at_start
from common.settings import SETTINGS
from common.studio_render_constants import STUDIO_TINT_HEX_PRESETS
from common.utils import PIPELINE_TEMPLATE_USER_SUBDIR, ensure_dir, output_template_user_dir

REPO_ROOT = _REPO_ROOT
WORLD_HDRI_PATH = REPO_ROOT / "resource" / "blender" / "castel_st_angelo_roof_4k.exr"

# 与 common.studio_render_constants 同步；--studio-tint-hex 可指定其中一项或任意 #RRGGBB
HEX_COLORS = STUDIO_TINT_HEX_PRESETS

_TINT_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
# 场景中多套头/发命名：female_03_head、male_07_hair 等；仅 YAML/CLI 指定的一对参与渲染。
_HEAD_HAIR_TEMPLATE_RE = re.compile(r"^(female|male)_[0-9]+_(head|hair)$", re.IGNORECASE)
# 每次导入 GLB 前须清空：body 以及 Blender 重名产生的 body.001 …
_BODY_OBJECT_NAME_RE = re.compile(r"^body(\.\d+)?$", re.IGNORECASE)
_JSON_ENVS = ("STAGE11_JSON", "STAGE9_JSON")

SUBDIR_COVERS = "stage9_render_covers"
SUBDIR_VIDEOS = "stage11_render_videos"
SUBDIR_SELECTED = "stage10_render_covers_selected"

# 透明封面：对工程内 Cylinder 背景集合内物体设 is_holdout；名称与 blend 一致（含「Collection」后缀的变体）
_BACKDROP_COLLECTION_NAMES: tuple[str, ...] = ("Cylinder Backdrop Collection", "Cylinder Backdrop")


def _parse_hex_tint(s: str) -> str:
    t = s.strip()
    if not t.startswith("#"):
        t = "#" + t
    if not _TINT_RE.match(t):
        presets = ", ".join(HEX_COLORS)
        raise SystemExit(
            f"[ERROR] --studio-tint-hex 须为 #RRGGBB，例如 {HEX_COLORS[0]}。预设列表: {presets}"
        )
    return t


def parse_cli_args() -> argparse.Namespace:
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1 :]
    else:
        argv = []
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input-root",
        default=str(SETTINGS.output_root / PIPELINE_TEMPLATE_USER_SUBDIR),
        help=(
            "递归扫描 *.glb 的根目录。若同时给出 --template 与 --user-requirement 或 --fashion-tag，"
            "则改为只扫描该 run（output/stage4_10/<模板>/<路径段>/），本参数被忽略。"
        ),
    )
    parser.add_argument(
        "--template",
        default=None,
        metavar="NAME",
        help="与阶段4～8 一致；与 --user-requirement 或 --fashion-tag 成对出现时限定单一 run",
    )
    parser.add_argument(
        "--user-requirement",
        default=None,
        help="与阶段4～8 需求全文一致；与 --fashion-tag 二选一或同传（同传时目录以 tag 为准）；须与 --template 同时指定",
    )
    parser.add_argument(
        "--fashion-tag",
        default=None,
        metavar="TAG",
        help="与阶段4 一致；仅定位 run 目录（与文生/贴图类 prompt 无关）；须与 --template 同时指定",
    )
    parser.add_argument(
        "--output-root",
        default=str(SETTINGS.output_root / SUBDIR_VIDEOS),
        help="仅用于旧版 GLB 目录布局；新版在 …/stage8… 旁写出 stage9/11 子目录。",
    )
    parser.add_argument(
        "--model-name",
        default="legacy_stage9",
        help="仅旧版浅路径布局时作为输出子目录名之一。",
    )
    parser.add_argument(
        "--head-object",
        default=None,
        help=".blend 场景中头物体名；与 --template +（需求或 tag）且存在 pipeline_render_prefs.yml 时可省略",
    )
    parser.add_argument(
        "--hair-object",
        default=None,
        help="内置头发物体名（如 female_01_hair）或 solid_hair 子目录名（如 female_hair_01）；同上 run 有 YAML 时可省略",
    )
    parser.add_argument(
        "--hair-color",
        default=None,
        metavar="NAME",
        help="发色名（见 common.hair_assets.HAIR_COLORS）；与 YAML 键 hair_color 一致；默认可由 prefs 指定",
    )
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--seconds", type=int, default=5)
    parser.add_argument(
        "--workers",
        type=int,
        default=int(os.environ.get("BLENDER_WORKERS", "1")),
        help=">1 时父进程拉起多个 Blender 子进程分片渲染",
    )
    parser.add_argument(
        "--only-glb-stem",
        default=None,
        metavar="STEM",
        help="只处理该 GLB 主文件名（不含 .glb）。若同时给出 --only-glb-stems，以列表为准。",
    )
    parser.add_argument(
        "--only-glb-stems",
        default=None,
        metavar="A,B,...",
        help=(
            "只处理这些 GLB 主名，逗号分隔（如 蜡笔小新,邋遢大王），须与 stage8 中 .glb 主名一致。"
            "covers / videos 均可用；videos 且未加 --all-glbs 时，会先与 stage10 已选封面求交再过滤。"
            "与多进程 --workers 兼容（经 STAGE11_JSON 下发）。"
        ),
    )
    parser.add_argument(
        "--pass",
        dest="render_pass",
        choices=("covers", "videos"),
        default="covers",
        help="covers=仅阶段9 封面；videos=阶段11 环绕 mp4（默认仅已选，见 --all-glbs）。",
    )
    parser.add_argument(
        "--all-glbs",
        action="store_true",
        help="仅与 --pass videos 合用：忽略 stage10 已选，为本 run 下全部 stage8 GLB 渲视频（与旧 Stage9 行为类似）。",
    )
    parser.add_argument(
        "--selected-covers-subdir",
        default=SUBDIR_SELECTED,
        help=f"相对 run 根目录的已选封面目录，默认 {SUBDIR_SELECTED}。",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="断点续跑：covers 对 *_cover.png 与 *_cover_rgba.png 分别判断，缺或损坏才补；videos 只重渲缺失/异常 mp4。",
    )
    parser.add_argument(
        "--render-output-dir",
        default=None,
        metavar="DIR",
        help=(
            "可选。指定则本批所有封面/视频直接写入该目录（会创建目录）；默认仍写入各 run 下 "
            "stage9_render_covers / stage11_render_videos。临时调试用；与 --workers 兼容。"
        ),
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--studio-tint-hex",
        default=None,
        metavar="#RRGGBB",
        help=(
            "固定 Studio 背景布 Tint 色（可填 HEX_COLORS 中任一项，或 #RRGGBB）。"
            "省略时默认使用预设列表首项，避免每套衣服随机一色。若需旧版随机，请用 --random-studio-tint。"
        ),
    )
    group.add_argument(
        "--random-studio-tint",
        action="store_true",
        help="每个 GLB 各自随机选 HEX_COLORS 之一（易与成片其它镜头不一致）。",
    )
    return parser.parse_args(argv)


def resolve_stage11_input_root(args: argparse.Namespace | SimpleNamespace) -> Path:
    """限定到某一 (模板, 需求或 tag) run，或保留整棵 stage4_10 扫描。"""
    template = (getattr(args, "template", None) or "").strip()
    requirement = (getattr(args, "user_requirement", None) or "").strip()
    fashion_tag = (getattr(args, "fashion_tag", None) or "").strip()
    if template and (requirement or fashion_tag):
        return output_template_user_dir(
            SETTINGS.output_root,
            template,
            requirement,
            fashion_tag=fashion_tag or None,
        ).resolve()
    if template or requirement or fashion_tag:
        print(
            "[ERROR] --template 须与 --user-requirement 或 --fashion-tag **同时**指定，"
            "或三者均省略并使用 --input-root。",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return Path(args.input_root).resolve()


def apply_resolved_input_root(args: argparse.Namespace | SimpleNamespace) -> None:
    args.input_root = str(resolve_stage11_input_root(args))


def setup_world_environment_hdri(exr_path: Path) -> None:
    """将场景 World 背景设为指定 EXR 的环境贴图（Cycles）。"""
    if not exr_path.is_file():
        raise FileNotFoundError(f"找不到 HDR 文件: {exr_path}")

    scene = bpy.context.scene
    world = scene.world
    if world is None:
        world = bpy.data.worlds.new("World")
        scene.world = world

    world.use_nodes = True
    nt = world.node_tree
    if nt is None:
        raise RuntimeError("World 无 node_tree，无法设置环境贴图。")

    nodes = nt.nodes
    links = nt.links
    exr_abs = str(exr_path.resolve())

    image = None
    for im in bpy.data.images:
        fp = bpy.path.abspath(im.filepath) if im.filepath else ""
        if fp == exr_abs or im.filepath == exr_abs:
            image = im
            break
    if image is None:
        image = bpy.data.images.load(exr_abs, check_existing=True)

    bg = next((n for n in nodes if n.type == "BACKGROUND"), None)
    if bg is None:
        bg = nodes.new("ShaderNodeBackground")
        bg.location = (0, 0)

    env_tex = next((n for n in nodes if n.type == "TEX_ENVIRONMENT"), None)
    if env_tex is None:
        env_tex = nodes.new("ShaderNodeTexEnvironment")
        env_tex.location = (-320, 0)

    env_tex.image = image

    out = next((n for n in nodes if n.type == "OUTPUT_WORLD"), None)
    if out is None:
        out = nodes.new("ShaderNodeOutputWorld")
        out.location = (320, 0)

    def disconnect_input(sock) -> None:
        for link in list(sock.links):
            links.remove(link)

    disconnect_input(bg.inputs["Color"])
    disconnect_input(out.inputs["Surface"])
    links.new(env_tex.outputs["Color"], bg.inputs["Color"])
    links.new(bg.outputs["Background"], out.inputs["Surface"])

    print(f"World 环境贴图已设为: {exr_abs}")


def _args_from_env() -> SimpleNamespace:
    for key in _JSON_ENVS:
        raw = os.environ.get(key, "")
        if raw:
            break
    else:
        raise SystemExit(
            f"子进程缺少 {' 或 '.join(_JSON_ENVS)}，请由父进程启动或单进程使用 -- 传参。"
        )
    data = json.loads(raw)
    data.setdefault("model_name", "legacy_stage9")
    data.setdefault("only_glb_stem", None)
    data.setdefault("only_glb_stems", None)
    data.setdefault("render_pass", "covers")
    data.setdefault("all_glbs", False)
    data.setdefault("resume", False)
    data.setdefault("template", None)
    data.setdefault("user_requirement", None)
    data.setdefault("fashion_tag", None)
    data.setdefault("selected_covers_subdir", SUBDIR_SELECTED)
    data.setdefault("studio_tint_hex", None)
    data.setdefault("random_studio_tint", False)
    data.setdefault("render_output_dir", None)
    data.setdefault("hair_color", "black")
    return SimpleNamespace(**data)


def args_to_dict(ns: argparse.Namespace | SimpleNamespace) -> dict:
    return {
        "input_root": str(ns.input_root),
        "output_root": str(ns.output_root),
        "model_name": ns.model_name,
        "head_object": ns.head_object,
        "hair_object": ns.hair_object,
        "hair_color": getattr(ns, "hair_color", None) or "black",
        "fps": int(ns.fps),
        "seconds": int(ns.seconds),
        "workers": int(ns.workers),
        "only_glb_stem": getattr(ns, "only_glb_stem", None),
        "only_glb_stems": getattr(ns, "only_glb_stems", None),
        "render_pass": getattr(ns, "render_pass", "covers"),
        "all_glbs": bool(getattr(ns, "all_glbs", False)),
        "resume": bool(getattr(ns, "resume", False)),
        "template": getattr(ns, "template", None),
        "user_requirement": getattr(ns, "user_requirement", None),
        "fashion_tag": getattr(ns, "fashion_tag", None),
        "selected_covers_subdir": getattr(ns, "selected_covers_subdir", SUBDIR_SELECTED),
        "studio_tint_hex": getattr(ns, "studio_tint_hex", None),
        "random_studio_tint": bool(getattr(ns, "random_studio_tint", False)),
        "render_output_dir": (
            None
            if not (v := getattr(ns, "render_output_dir", None)) or not str(v).strip()
            else str(Path(str(v).strip()).expanduser().resolve())
        ),
    }


def _collect_tasks_impl(
    input_root: Path, output_root: Path, model_name_fallback: str, mode: str
) -> list[tuple[Path, Path]]:
    tasks: list[tuple[Path, Path]] = []
    for glb_path in sorted(input_root.rglob("*.glb")):
        if glb_path.parent.name == "stage8_new_texture_model_generation":
            out_dir = glb_path.parent.with_name(
                SUBDIR_COVERS if mode == "covers" else SUBDIR_VIDEOS
            )
            tasks.append((glb_path, out_dir))
            continue
        try:
            rel = glb_path.relative_to(input_root)
        except ValueError:
            continue
        if len(rel.parts) <= 1:
            out_dir = output_root / model_name_fallback
        else:
            out_dir = output_root / rel.parent
        # 旧版无 stage8 目录名时，covers/videos 均落到 output 镜像
        tasks.append((glb_path, out_dir))
    return tasks


def collect_tasks(
    input_root: Path, output_root: Path, model_name_fallback: str, mode: str
) -> list[tuple[Path, Path]]:
    """mode: 'covers' | 'videos' — 同 run 下为 stage9_render_covers 或 stage11_render_videos；旧版仍按 output_root 镜像。"""
    return _collect_tasks_impl(input_root, output_root, model_name_fallback, mode)


def parse_only_glb_stems_arg(args: argparse.Namespace | SimpleNamespace) -> set[str] | None:
    """由 --only-glb-stems（逗号分隔）或单独的 --only-glb-stem 得到待渲 stem 集合；未指定则 None。"""
    raw_list = getattr(args, "only_glb_stems", None)
    if raw_list is not None and str(raw_list).strip():
        parts = [p.strip() for p in str(raw_list).split(",") if p.strip()]
        if parts:
            return set(parts)
    single = getattr(args, "only_glb_stem", None)
    if single is not None and str(single).strip():
        return {str(single).strip()}
    return None


def resolve_stems_from_selected_covers(
    run_dir: Path, subdir: str
) -> set[str]:
    """从 ``<run>/<subdir>/*_cover.png`` 解析 GLB 主文件名（stem）。"""
    d = (run_dir / subdir).resolve()
    if not d.is_dir():
        return set()
    out: set[str] = set()
    for p in d.glob("*_cover.png"):
        if not p.is_file():
            continue
        # stem 如 哪吒闹海_cover -> 取 哪吒闹海
        s = p.stem
        if s.endswith("_cover"):
            out.add(s[: -len("_cover")])
    return out


def tasks_for_worker(
    tasks: list[tuple[Path, Path]], worker_id: int, worker_count: int
) -> list[tuple[Path, Path]]:
    return [t for i, t in enumerate(tasks) if i % worker_count == worker_id]


def spawn_parallel_blenders(worker_count: int, config_json: str) -> int:
    blend = (bpy.data.filepath or os.environ.get("BLENDER_BLEND", "")).strip()
    if not blend:
        raise SystemExit(
            "多进程需要 .blend 路径：请使用 blender -b --python-use-system-env /path/to/scene.blend "
            "-P stage11_render_videos/blender_render_videos.py，"
            "或设置环境变量 BLENDER_BLEND=/绝对路径/scene.blend"
        )
    blend = os.path.abspath(blend)
    script = os.path.abspath(__file__)
    exe = bpy.app.binary_path
    effective = int(compute_spawn_worker_count(worker_count))
    if effective < worker_count:
        print(
            f"[租约] 全局并行渲槽紧张（BLENDER_POOL_MAX），本次仅启动 {effective}/{worker_count} "
            f"个子 Blender；分片仍正确（少进程时由单 worker 顺序处理多片）。",
            flush=True,
        )
    print(f"父进程：将启动 {effective} 个 Blender 子进程（请求 {worker_count}）", flush=True)
    print(f"  blend={blend}")
    print(f"  script={script}")
    procs = []
    for wid in range(effective):
        env = os.environ.copy()
        env["BLENDER_WORKER_ID"] = str(wid)
        env["BLENDER_WORKERS"] = str(effective)
        env["STAGE11_JSON"] = config_json
        env["STAGE9_JSON"] = config_json  # 兼容旧名
        cmd = [exe, "-b", "--python-use-system-env", blend, "-P", script]
        procs.append(subprocess.Popen(cmd, env=env))
    codes = []
    for wid, p in enumerate(procs):
        rc = p.wait()
        codes.append(rc)
        print(f"子进程 worker {wid} 退出码: {rc}")
    return max(codes) if codes else 0


def hex_to_rgba(hex_color: str) -> tuple[float, float, float, float]:
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i : i + 2], 16) / 255 for i in (0, 2, 4)) + (1.0,)


def cleanup_body() -> None:
    """删除场景中所有上一轮导入的 GLB 根 ``body`` / ``body.001`` … 及其子层级。

    每次渲封面或视频前**必须**调用，避免与新建 ``body`` 叠在一起导致材质/网格错乱。
    """
    bpy.ops.object.select_all(action="DESELECT")
    candidates = {o for o in bpy.data.objects if _BODY_OBJECT_NAME_RE.match(o.name)}
    if not candidates:
        return
    # 只删「根」：父物体不在 candidates 里，避免子网格被重复选中
    roots = [o for o in candidates if o.parent not in candidates]
    names = [o.name for o in roots]
    for name in names:
        obj = bpy.data.objects.get(name)
        if obj is None:
            continue
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        for ch in obj.children_recursive:
            ch.select_set(True)
        bpy.ops.object.delete()
    print(f"已清理 GLB 根物体及其子层级: {', '.join(names)}", flush=True)


def set_background_tint(
    *, hex_explicit: str | None, per_model_random: bool, rng: random.Random
) -> None:
    mat = bpy.data.materials.get("Studio_Fabric_1.001")
    if not mat or not mat.use_nodes:
        return
    node = mat.node_tree.nodes.get("Tint")
    if not node:
        return
    if per_model_random:
        c = rng.choice(HEX_COLORS)
    elif hex_explicit:
        c = _parse_hex_tint(hex_explicit)
    else:
        c = HEX_COLORS[0]
    node.outputs[0].default_value = hex_to_rgba(c)
    print(f"Studio 背景布 Tint: {c}")


def set_focus(body_obj) -> None:
    camera = bpy.data.cameras.get("Camera")
    if camera:
        camera.dof.focus_object = body_obj


def configure_visible_head_hair(head_name: str, hair_name: str) -> None:
    """隐藏所有 ``female_*_{head,hair}`` / ``male_*_{head,hair}``，仅保留配置中的头/发参与渲染。"""
    head = (head_name or "").strip()
    hair = (hair_name or "").strip()
    active = {n for n in (head, hair) if n}

    for obj in bpy.data.objects:
        if _HEAD_HAIR_TEMPLATE_RE.match(obj.name):
            hide = obj.name not in active
            obj.hide_render = hide
            obj.hide_viewport = hide

    for n in active:
        obj = bpy.data.objects.get(n)
        if obj is None:
            print(f"[WARN] 场景中未找到头/发物体: {n!r}（请核对 pipeline_render_prefs.yml 或 CLI）", flush=True)
            continue
        obj.hide_render = False
        obj.hide_viewport = False

    print(
        f"头/发可见性: 仅渲染 {sorted(active)}；其余匹配 "
        f"female|male_<数字>_head|hair 的物体已 hide_render。",
        flush=True,
    )


def _purge_solid_hair_marked() -> None:
    for obj in list(bpy.data.objects):
        if obj.get("solid_hair"):
            bpy.data.objects.remove(obj, do_unlink=True)


def _hide_all_template_head_hair() -> None:
    for obj in bpy.data.objects:
        if _HEAD_HAIR_TEMPLATE_RE.match(obj.name):
            obj.hide_render = True
            obj.hide_viewport = True


def _unhide_objects_by_names(names: set[str]) -> None:
    for n in names:
        if not n:
            continue
        obj = bpy.data.objects.get(n)
        if obj is None:
            print(f"[WARN] 场景中未找到物体: {n!r}（请核对 pipeline_render_prefs.yml 或 CLI）", flush=True)
            continue
        obj.hide_render = False
        obj.hide_viewport = False


def _apply_rgb_to_materials_of_object(obj: bpy.types.Object, rgb: tuple[float, float, float]) -> None:
    """将发色写入 Principled Base Color。

    solid_hair 导入的材质往往把 **贴图** 连到 Base Color，此时仅改 ``default_value`` 不会生效；
    须先断开该插槽上的链接再赋纯色（与 ``pipeline_render_prefs.yml`` 的 ``hair_color`` 一致）。
    """
    if obj.type != "MESH" or obj.data is None:
        return
    mesh = obj.data
    for mat in mesh.materials:
        if mat is None:
            continue
        if not mat.use_nodes:
            mat.use_nodes = True
        nt = mat.node_tree
        if nt is None:
            continue
        nodes = nt.nodes
        bsdf = nodes.get("Principled BSDF") or next(
            (n for n in nodes if n.type == "BSDF_PRINCIPLED"),
            None,
        )
        if bsdf is None:
            continue
        sock = bsdf.inputs.get("Base Color")
        if sock is None:
            continue
        for link in list(sock.links):
            nt.links.remove(link)
        sock.default_value = (rgb[0], rgb[1], rgb[2], 1.0)
        if "Metallic" in bsdf.inputs:
            bsdf.inputs["Metallic"].default_value = 0.0
        if "Roughness" in bsdf.inputs:
            bsdf.inputs["Roughness"].default_value = 1.0


def _import_solid_hair_obj(abs_path: str) -> list[bpy.types.Object]:
    before_ids = {id(o) for o in bpy.data.objects}
    fp = abs_path.replace("\\", "/")
    try:
        bpy.ops.wm.obj_import(filepath=fp)
    except AttributeError:
        bpy.ops.import_scene.obj(filepath=fp, axis_forward="-Z", axis_up="Y")
    new_objs = [o for o in bpy.data.objects if id(o) not in before_ids]
    for o in new_objs:
        o["solid_hair"] = 1
    # 与 render_one_glb 中导入的 GLB 身体根节点一致，避免头发与 body 量级错位
    new_set = set(new_objs)
    for root in (o for o in new_objs if o.parent is None or o.parent not in new_set):
        root.scale = (0.1, 0.1, 0.1)
    return new_objs


def _apply_solid_hair_color(rgb: tuple[float, float, float]) -> None:
    for obj in bpy.data.objects:
        if obj.get("solid_hair"):
            _apply_rgb_to_materials_of_object(obj, rgb)
            for ch in obj.children_recursive:
                if ch.type == "MESH":
                    _apply_rgb_to_materials_of_object(ch, rgb)


def configure_head_and_hair(
    head_name: str,
    hair_name: str,
    hair_color_key: str,
    repo: Path,
) -> None:
    """内置头 +（solid_hair OBJ 或 .blend 内置头发）；发色作用于 Principled Base Color。"""
    head = (head_name or "").strip()
    hair = (hair_name or "").strip()
    hex_s = resolve_hair_hex(hair_color_key, default="#0D0D0D")
    rgb = hex_to_rgb01(hex_s)
    sp = solid_hair_obj_path(repo, hair)

    if sp is not None:
        _purge_solid_hair_marked()
        _hide_all_template_head_hair()
        _unhide_objects_by_names({head})
        print(f"[RUN] solid hair: 导入 {sp} 发色={hair_color_key!r} -> {hex_s}", flush=True)
        _import_solid_hair_obj(str(sp.resolve()))
        _apply_solid_hair_color(rgb)
        print(
            f"头/发可见性: 头={head!r}；头发为 OBJ；模板 female|male_*_hair 已 hide_render。",
            flush=True,
        )
        return

    configure_visible_head_hair(head, hair)
    ho = bpy.data.objects.get(hair)
    if ho is not None:
        _apply_rgb_to_materials_of_object(ho, rgb)
        for ch in ho.children_recursive:
            if ch.type == "MESH":
                _apply_rgb_to_materials_of_object(ch, rgb)
        print(f"[RUN] 已为内置头发 {hair!r} 设置 Base Color ≈ {hex_s}", flush=True)


def tweak_body_materials(body_obj) -> None:
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


def _backdrop_collection_objects() -> list[bpy.types.Object]:
    """工程 ``blender_render_videos.blend`` 中圆柱布景集合及其子级物体（用于 Holdout 透明封面）。"""
    seen: set[bpy.types.Object] = set()
    ordered: list[bpy.types.Object] = []
    for name in _BACKDROP_COLLECTION_NAMES:
        col = bpy.data.collections.get(name)
        if col is None:
            continue
        for obj in col.all_objects:
            if obj not in seen:
                seen.add(obj)
                ordered.append(obj)
        if ordered:
            return ordered
    return []


def _snapshot_object_holdout(objs: list[bpy.types.Object]) -> list[tuple[bpy.types.Object, bool]]:
    snap: list[tuple[bpy.types.Object, bool]] = []
    for o in objs:
        try:
            snap.append((o, bool(o.is_holdout)))
        except (AttributeError, TypeError, ReferenceError):
            continue
    return snap


def _set_objects_holdout(objs: list[bpy.types.Object], value: bool) -> None:
    for o in objs:
        try:
            o.is_holdout = value
        except (AttributeError, TypeError, ReferenceError):
            pass


def _restore_object_holdout(snap: list[tuple[bpy.types.Object, bool]]) -> None:
    for o, prev in snap:
        try:
            o.is_holdout = prev
        except (AttributeError, TypeError, ReferenceError):
            pass


def render_one_glb(
    glb_path: Path,
    output_dir: Path,
    *,
    fps: int,
    seconds: int,
    cover_only: bool,
    write_still: bool = True,
    render_cover_opaque: bool = True,
    render_cover_rgba: bool = True,
) -> None:
    if not glb_path.is_file():
        print(f"文件不存在: {glb_path}")
        return

    cleanup_body()
    before_names = {o.name for o in bpy.data.objects}
    bpy.ops.import_scene.gltf(filepath=str(glb_path))
    new_objs = [o for o in bpy.data.objects if o.name not in before_names]
    new_set = set(new_objs)
    roots = [o for o in new_objs if o.parent is None or o.parent not in new_set]
    for root in roots:
        root.scale = (0.1, 0.1, 0.1)

    body_obj = bpy.data.objects.get("body")
    if body_obj:
        body_obj.scale = (0.1, 0.1, 0.1)
        set_focus(body_obj)
        tweak_body_materials(body_obj)

    scene = bpy.context.scene
    scene.render.fps = fps
    ensure_dir(output_dir)

    if not cover_only:
        scene.frame_start = 1
        scene.frame_end = fps * seconds
        scene.render.image_settings.file_format = "FFMPEG"
        scene.render.ffmpeg.format = "MPEG4"
        scene.render.ffmpeg.codec = "H264"
        video_path = output_dir / f"{glb_path.stem}.mp4"
        scene.render.filepath = str(video_path)
        print(f"正在开始渲染: {glb_path.name} -> {video_path.name} ...")
        bpy.ops.render.render(animation=True)
        print(f"完成动画渲染: {video_path}")
    else:
        print(f"仅输出第 18 帧封面: {glb_path.name}")
        write_still = True

    if write_still and cover_only:
        scene.frame_set(18)
        if not render_cover_opaque and not render_cover_rgba:
            return
        if render_cover_opaque:
            scene.render.image_settings.file_format = "PNG"
            model_cover_path = output_dir / f"{glb_path.stem}_cover.png"
            scene.render.filepath = str(model_cover_path)
            bpy.ops.render.render(write_still=True)
            print(f"已输出封面(带背景): {model_cover_path}", flush=True)
        if render_cover_rgba:
            backdrop_objs = _backdrop_collection_objects()
            if not backdrop_objs:
                print(
                    f"[WARN] 未找到背景集合 {_BACKDROP_COLLECTION_NAMES!r}，跳过透明封面: {glb_path.stem}",
                    flush=True,
                )
            else:
                hold_snap = _snapshot_object_holdout(backdrop_objs)
                _set_objects_holdout(backdrop_objs, True)
                r = scene.render
                img = r.image_settings
                saved_format = img.file_format
                saved_color_mode = img.color_mode
                saved_film = r.film_transparent
                try:
                    r.film_transparent = True
                    img.file_format = "PNG"
                    img.color_mode = "RGBA"
                    rgba_path = output_dir / f"{glb_path.stem}_cover_rgba.png"
                    r.filepath = str(rgba_path)
                    print(f"输出透明封面(Holdout+RGBA): {rgba_path.name}", flush=True)
                    bpy.ops.render.render(write_still=True)
                    print(f"已输出封面(透明): {rgba_path}", flush=True)
                finally:
                    _restore_object_holdout(hold_snap)
                    img.color_mode = saved_color_mode
                    img.file_format = saved_format
                    r.film_transparent = saved_film
    elif write_still:
        scene.frame_set(18)
        scene.render.image_settings.file_format = "PNG"
        model_cover_path = output_dir / f"{glb_path.stem}_cover.png"
        scene.render.filepath = str(model_cover_path)
        bpy.ops.render.render(write_still=True)
        print(f"已输出封面: {model_cover_path}")


def _looks_valid_mp4(path: Path) -> bool:
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


def process_tasks(
    tasks: list[tuple[Path, Path]],
    args: SimpleNamespace,
    *,
    cover_only: bool,
    write_still: bool,
) -> None:
    if not tasks:
        print("本 worker 无任务，跳过")
        return
    ensure_cycles_cuda()
    cleanup_body()
    setup_world_environment_hdri(WORLD_HDRI_PATH)
    configure_head_and_hair(
        str(args.head_object or ""),
        str(args.hair_object or ""),
        str(getattr(args, "hair_color", None) or "black"),
        REPO_ROOT,
    )

    resume = bool(getattr(args, "resume", False))
    per_random = bool(getattr(args, "random_studio_tint", False))
    raw_hex: str | None = getattr(args, "studio_tint_hex", None)
    tint_resolved: str | None
    if raw_hex and not per_random:
        tint_resolved = _parse_hex_tint(raw_hex)
    else:
        tint_resolved = None

    for glb_path, out_dir in tasks:
        rng = random.Random()
        if per_random:
            set_background_tint(hex_explicit=None, per_model_random=True, rng=rng)
        else:
            set_background_tint(hex_explicit=tint_resolved, per_model_random=False, rng=rng)

        if cover_only:
            cover_png = out_dir / f"{glb_path.stem}_cover.png"
            rgba_png = out_dir / f"{glb_path.stem}_cover_rgba.png"
            need_opaque = True
            need_rgba = True
            if resume:
                if _looks_valid_png(cover_png):
                    need_opaque = False
                if _looks_valid_png(rgba_png):
                    need_rgba = False
            if not need_opaque and not need_rgba:
                print(f"[SKIP] 已有有效封面(含透明): {glb_path.stem}", flush=True)
                continue
            render_one_glb(
                glb_path,
                out_dir,
                fps=args.fps,
                seconds=args.seconds,
                cover_only=True,
                write_still=True,
                render_cover_opaque=need_opaque,
                render_cover_rgba=need_rgba,
            )
        else:
            if resume:
                mp4_path = out_dir / f"{glb_path.stem}.mp4"
                if _looks_valid_mp4(mp4_path):
                    print(f"[SKIP] 视频有效，跳过: {glb_path.stem}")
                    continue
            render_one_glb(
                glb_path,
                out_dir,
                fps=args.fps,
                seconds=args.seconds,
                cover_only=False,
                write_still=write_still,
            )
        print(f"[OK] {glb_path} -> {out_dir}")


def _run_uses_template_run_ident(args: argparse.Namespace | SimpleNamespace) -> bool:
    return bool(
        (getattr(args, "template", None) or "").strip()
        and (
            (getattr(args, "user_requirement", None) or "").strip()
            or (getattr(args, "fashion_tag", None) or "").strip()
        )
    )


def main() -> None:
    worker_id_env = os.environ.get("BLENDER_WORKER_ID")
    if worker_id_env is not None:
        args = _args_from_env()
    else:
        args = parse_cli_args()

    apply_resolved_input_root(args)
    input_root = Path(args.input_root)
    if _run_uses_template_run_ident(args) and worker_id_env is None:
        prefs_written = sync_pipeline_render_prefs_at_start(input_root, args)
        print(f"[RUN] 已同步 pipeline_render_prefs.yml: {prefs_written}", flush=True)
    elif not _run_uses_template_run_ident(args):
        ho = (getattr(args, "head_object", None) or "").strip()
        ha = (getattr(args, "hair_object", None) or "").strip()
        if not ho or not ha:
            print(
                "[ERROR] 未同时指定 --template 与（--user-requirement 或 --fashion-tag）时，必须在命令行指定 "
                "--head-object 与 --hair-object（此模式下不读写 pipeline_render_prefs.yml）。",
                file=sys.stderr,
            )
            raise SystemExit(2)

    if getattr(args, "studio_tint_hex", None) and not getattr(
        args, "random_studio_tint", False
    ):
        _parse_hex_tint(str(args.studio_tint_hex))

    output_root = Path(args.output_root)
    render_pass = str(getattr(args, "render_pass", "covers"))
    all_glbs = bool(getattr(args, "all_glbs", False))
    sub_sel = str(getattr(args, "selected_covers_subdir", SUBDIR_SELECTED))
    if render_pass not in ("covers", "videos"):
        raise SystemExit(2)

    mode = "covers" if render_pass == "covers" else "videos"
    print(
        f"[RUN] 扫描根目录: {input_root}  pass={render_pass}  output_mode={mode}",
        flush=True,
    )
    all_tasks = collect_tasks(input_root, output_root, args.model_name, mode)

    if mode == "videos" and not all_glbs:
        stems = resolve_stems_from_selected_covers(input_root, sub_sel)
        if not stems:
            print(
                f"[ERROR] --pass videos 且未加 --all-glbs 时，需要在「本 run 根」下先建立 "
                f"「{sub_sel}」并放入所选的 <模型名>_cover.png（如从 stage9 复制）。"
                f" 当前未解析到任何 stem。",
                file=sys.stderr,
            )
            raise SystemExit(2)
        all_tasks = [(g, o) for g, o in all_tasks if g.stem in stems]
        if not all_tasks:
            print(
                f"[ERROR] 已选 stem {sorted(stems)} 在 stage8 中找不到对应 .glb。",
                file=sys.stderr,
            )
            raise SystemExit(2)
        print(f"[RUN] 仅渲染已选模型（共 {len(stems)} 个 stem, {len(all_tasks)} 个任务）", flush=True)

    stems_filter = parse_only_glb_stems_arg(args)
    if stems_filter:
        filtered = [(g, o) for g, o in all_tasks if g.stem in stems_filter]
        if not filtered:
            stems2 = sorted({g.stem for g, _ in all_tasks})
            preview = stems2[:40]
            more = f" … 共 {len(stems2)} 个" if len(stems2) > 40 else ""
            missing = sorted(stems_filter - set(stems2))
            print(
                f"[ERROR] 指定的 stem 在当前任务集中无匹配 GLB。缺少: {missing}。"
                f" 候选 stem: {preview}{more}",
                file=sys.stderr,
            )
            raise SystemExit(2)
        unknown = stems_filter - {g.stem for g, _ in filtered}
        if unknown:
            print(
                f"[WARN] 下列 stem 无对应任务（可能未在已选封面或未在 stage8）: {sorted(unknown)}",
                flush=True,
            )
        all_tasks = filtered
        print(
            f"[RUN] --only-glb-stems 过滤后 {len(all_tasks)} 个任务: "
            f"{sorted({g.stem for g, _ in all_tasks})}",
            flush=True,
        )

    rod = getattr(args, "render_output_dir", None)
    if rod is not None and str(rod).strip():
        out_base = Path(str(rod).strip()).expanduser().resolve()
        out_base.mkdir(parents=True, exist_ok=True)
        all_tasks = [(g, out_base) for g, _ in all_tasks]
        print(f"[RUN] --render-output-dir 临时输出: {out_base}", flush=True)

    cover_only = render_pass == "covers"
    write_still = cover_only  # 正片 pass 不重复写 _cover（封面已在 stage9）

    workers = int(os.environ.get("BLENDER_WORKERS", str(args.workers)))
    if worker_id_env is not None:
        from common.blender_render_pool_lease import acquire_render_slot, release_render_slot

        wid = int(worker_id_env)
        chunk = tasks_for_worker(all_tasks, wid, workers)
        print(f"Worker {wid}/{workers}，任务数 {len(chunk)}", flush=True)
        acquire_render_slot()
        try:
            process_tasks(
                chunk, args, cover_only=cover_only, write_still=write_still
            )
        finally:
            release_render_slot()
        return

    if workers > 1:
        config_json = json.dumps(args_to_dict(args), ensure_ascii=False)
        rc = spawn_parallel_blenders(workers, config_json)
        if rc != 0:
            raise SystemExit(rc)
        return

    from common.blender_render_pool_lease import acquire_render_slot, release_render_slot

    acquire_render_slot()
    try:
        process_tasks(all_tasks, args, cover_only=cover_only, write_still=write_still)
    finally:
        release_render_slot()


if __name__ == "__main__":
    main()
