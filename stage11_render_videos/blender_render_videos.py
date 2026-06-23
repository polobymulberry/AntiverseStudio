"""Stage9（封面）与 Stage11（环绕视频）：工程 resource/blender/blender_render_videos.blend

- --pass covers：为 stage8 下各 GLB 渲第 18 帧：``<label>_cover.png``（带 Studio 背景）与 ``<label>_cover_rgba.png``（Cylinder 背景集合 **Holdout** + 胶片透明 PNG RGBA）。``--resume`` 时二者分别判断，缺谁补谁。同时导出 ``<label>_composite.glb``（body + head + hair，带纹理贴图，物体名分别为 body/head/hair；导出瞬间将三者根级 scale 从渲染用 0.1 临时改为 1.0 再写文件）。``--only-export`` 时**仅**导出该合成 GLB，不渲染封面/视频。**若已指定 --fashion-tag 且 YAML 中 ``head_object`` 为数字 real_head_id**，还会在**每个** ``…/stage9_render_covers/`` 下写入 ``real_head_reference.<后缀>``（来自 Stage3b CSV 的 ``photo_path``，或回退 ``resource/real_head_120k_selected`` 下文件名含该 id 的图片），便于与封面比对。
- --pass videos：仅对 ``stage10_render_covers_selected/`` 中出现的 ``*_cover.png`` 所对应的模型渲 mp4 到 ``.../stage11_render_videos/``（当前流程约定目录内约 **6** 张已选封面，对应正片 **5** 套 + 备损 **1** 套）。可用 ``--all-glbs`` 恢复「全部 GLB 都渲」的旧行为（仍输出到 stage11）。可用 ``--only-glb-stems 'A,B'`` 再限定其中若干 GLB 主名（逗号分隔），与 ``--workers`` 多进程兼容。
- ``--debug``：每个 GLB 渲染完成后，将当前 Blender 场景另存为 ``<stem>_render_debug.blend``，写入与该任务 PNG/mp4 相同的输出目录（通常为各模板下 ``stage9_render_covers`` 或 ``stage11_render_videos``），便于对照成片排查。

Studio 背景墙 ``Studio_Fabric_1.001`` 的 **Tint** 颜色默认使用本脚本内 ``HEX_COLORS`` 首项，可用 ``--studio-tint-hex`` 固定，避免多模型时随机色导致成片割裂。子进程经 STAGE11_JSON 或（兼容）STAGE9_JSON 收参。

当同时使用 ``--template`` 与 ``--user-requirement`` 或 ``--fashion-tag`` 时，启动即同步 ``pipeline_render_prefs.yml``：无则创建；CLI 有指定则覆盖写回；否则用文件或随机/默认并立即落盘。之后可省略上述三参数。

``head_object`` 可为工程内名称（如 ``female_03_head``），或 **0～119999** 的纯数字 **template_id**，
后者从 ``REAL_HEAD_120K_ROOT/solid/<6位>/akintisan3d/template_aligned/mcr_head.glb`` 导入（可用 ``REAL_HEAD_MESH_REL_PATTERN`` 覆盖为其它 glb/obj），缩放 0.1，隐藏所有内置头，Principled Metallic=0、Roughness=1。
``hair_object`` 可为 ``resource/blender/solid_hair/<子目录>/low_poly/hair.obj`` 的目录名（如 ``female_hair_01``），由本脚本导入 OBJ；``hair_color`` 为发色名（见 ``common/hair_assets.HAIR_COLORS``）或内联 hex（``#RRGGBB`` / ``RRGGBB``）。无需手改 ``blender_render_videos.blend``。

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
from common.hair_assets import (
    hex_to_linear_rgb01,
    is_solid_hair_style_id,
    resolve_hair_hex,
    solid_hair_obj_path,
)
from common.pipeline_doll_merge import resolve_textured_hair_glb_path
from common.pipeline_render_prefs import (
    load_render_prefs_dict,
    load_render_prefs_merged,
    pipeline_render_prefs_path,
    sync_pipeline_render_prefs_at_start,
)
from common.real_head_assets import (
    candidate_paths_for_template_id,
    normalize_real_head_template_id,
    resolve_existing_real_head_mesh,
)
from common.settings import SETTINGS
from common.studio_render_constants import STUDIO_TINT_HEX_PRESETS
from common.utils import (
    PIPELINE_TEMPLATE_USER_SUBDIR,
    existing_fashion_tag_run_dirs,
    fashion_tag_run_dir_candidates,
    resolve_body_template_run_dir,
    resolve_fashion_tag_run_dir,
    ensure_dir,
)

REPO_ROOT = _REPO_ROOT
WORLD_HDRI_PATH = REPO_ROOT / "resource" / "blender" / "castel_st_angelo_roof_4k.exr"

# 与 common.studio_render_constants 同步；--studio-tint-hex 可指定其中一项或任意 #RRGGBB
HEX_COLORS = STUDIO_TINT_HEX_PRESETS

_TINT_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
# 场景中多套头/发命名：female_03_head、male_07_hair 等；仅 YAML/CLI 指定的一对参与渲染。
_HEAD_HAIR_TEMPLATE_RE = re.compile(r"^(female|male)_[0-9]+_(head|hair)$", re.IGNORECASE)
_HEAD_TEMPLATE_RE = re.compile(r"^(female|male)_[0-9]+_head$", re.IGNORECASE)
_HAIR_TEMPLATE_RE = re.compile(r"^(female|male)_[0-9]+_hair$", re.IGNORECASE)
# 每次导入 GLB 前须清空：body/head/hair 以及 Blender 重名产生的 *.001 …
_BODY_OBJECT_NAME_RE = re.compile(r"^body(\.\d+)?$", re.IGNORECASE)
_HEAD_OBJECT_NAME_RE = re.compile(r"^head(\.\d+)?$", re.IGNORECASE)
_HAIR_OBJECT_NAME_RE = re.compile(r"^hair(\.\d+)?$", re.IGNORECASE)
_COMPOSITE_GLB_SUFFIX = "_composite.glb"
_JSON_ENVS = ("STAGE11_JSON", "STAGE9_JSON")

# body GLB 导入标记：新键 antiverse_body_glb；兼容旧工程 figshion_body_glb（读取时双键识别，写入时迁移到新键）
_BODY_GLB_MARK_KEY = "antiverse_body_glb"
_LEGACY_BODY_GLB_MARK_KEY = "figshion_body_glb"
_BODY_GLB_MARK_KEYS = (_BODY_GLB_MARK_KEY, _LEGACY_BODY_GLB_MARK_KEY)

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
        default=str(SETTINGS.pipeline_run_root() / PIPELINE_TEMPLATE_USER_SUBDIR),
        help=(
            "递归扫描 *.glb 的根目录。若给出 --fashion-tag（可选再加 --template），"
            "则改为只扫描该 run（output/<PIPELINE_LINE>/stage4_10/<标签>/ …），本参数被忽略。"
        ),
    )
    parser.add_argument(
        "--template",
        default=None,
        metavar="NAME",
        help="与阶段4～8 一致；与 --fashion-tag 组合时限定某一服装模板子目录（可选）。",
    )
    parser.add_argument(
        "--user-requirement",
        default=None,
        help="（可选）仅写入 pipeline_render_prefs.yml；不参与路径。路径仅由 --fashion-tag（及可选 --template）决定。",
    )
    parser.add_argument(
        "--fashion-tag",
        default=None,
        metavar="TAG",
        help="与阶段4 一致；定位 output/<产品线>/stage4_10 或 stage4_10_finish/<标签>/（可与 --template 组合定位到单套模板目录）。",
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
        help=".blend 场景中头物体名；与 --fashion-tag 且存在 pipeline_render_prefs.yml 时可省略",
    )
    parser.add_argument(
        "--hair-object",
        default=None,
        help="内置头发物体名（如 female_01_hair）或 solid_hair 子目录名（如 female_hair_01）；同上 run 有 YAML 时可省略",
    )
    parser.add_argument(
        "--hair-color",
        default=None,
        metavar="NAME_OR_HEX",
        help="发色名（见 common.hair_assets.HAIR_COLORS）或 #RRGGBB / RRGGBB；与 YAML 键 hair_color 一致；默认可由 prefs 指定",
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
        "--debug",
        action="store_true",
        help=(
            "每个 GLB 渲完后将当前场景 save 为 <stem>_render_debug.blend，"
            "落在与封面/视频相同的目录（stage9_render_covers 或 stage11_render_videos 等）；与 --workers 兼容。"
        ),
    )
    parser.add_argument(
        "--only-export",
        action="store_true",
        help=(
            "仅与 --pass covers 合用：只导出 <stem>_composite.glb（body+head+hair 带贴图），"
            "不渲染封面 PNG；适合对已跑过 Stage9 的数据补导出打印模型。"
        ),
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


def resolve_stage11_scan_roots(args: argparse.Namespace | SimpleNamespace) -> list[Path]:
    """限定扫描根：``--fashion-tag`` 时在 ``stage4_10`` 与 ``stage4_10_finish`` 中查找（可合并扫描）。"""
    template = (getattr(args, "template", None) or "").strip()
    fashion_tag = (getattr(args, "fashion_tag", None) or "").strip()
    if fashion_tag and template:
        try:
            return [resolve_body_template_run_dir(SETTINGS.output_root, fashion_tag, template)]
        except FileNotFoundError as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            raise SystemExit(2) from exc
    if fashion_tag:
        dirs = existing_fashion_tag_run_dirs(SETTINGS.output_root, fashion_tag)
        if not dirs:
            active, finish = fashion_tag_run_dir_candidates(SETTINGS.output_root, fashion_tag)
            print(
                "[ERROR] 指定 --fashion-tag 但在 stage4_10 与 stage4_10_finish 均未找到主题目录:\n"
                f"  {active}\n"
                f"  {finish}",
                file=sys.stderr,
            )
            raise SystemExit(2)
        if len(dirs) > 1:
            print(
                "[RUN] 在 stage4_10 与 stage4_10_finish 均找到该主题，将合并扫描: "
                + ", ".join(str(p) for p in dirs),
                flush=True,
            )
        return [p.resolve() for p in dirs]
    if template:
        print(
            "[ERROR] 指定 --template 时必须同时指定 --fashion-tag，或省略二者并使用 --input-root。",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return [Path(args.input_root).resolve()]


def resolve_stage11_input_root(args: argparse.Namespace | SimpleNamespace) -> Path:
    """返回主扫描根（多根扫描时的首个），兼容旧逻辑。"""
    return resolve_stage11_scan_roots(args)[0]


def apply_resolved_input_root(args: argparse.Namespace | SimpleNamespace) -> None:
    roots = resolve_stage11_scan_roots(args)
    args.input_roots = [str(p) for p in roots]
    args.input_root = str(roots[0])


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
    data.setdefault("debug", False)
    data.setdefault("only_export", False)
    data.setdefault("input_roots", None)
    ns = SimpleNamespace(**data)
    if not getattr(ns, "input_roots", None):
        ns.input_roots = [ns.input_root]
    return ns


def args_to_dict(ns: argparse.Namespace | SimpleNamespace) -> dict:
    input_roots = getattr(ns, "input_roots", None)
    if not input_roots:
        input_roots = [str(ns.input_root)]
    return {
        "input_root": str(ns.input_root),
        "input_roots": [str(p) for p in input_roots],
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
        "debug": bool(getattr(ns, "debug", False)),
        "only_export": bool(getattr(ns, "only_export", False)),
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
    input_roots: list[Path], output_root: Path, model_name_fallback: str, mode: str
) -> list[tuple[Path, Path]]:
    """mode: 'covers' | 'videos' — 同 run 下为 stage9_render_covers 或 stage11_render_videos；旧版仍按 output_root 镜像。"""
    tasks: list[tuple[Path, Path]] = []
    seen_glbs: set[Path] = set()
    for input_root in input_roots:
        for glb_path, out_dir in _collect_tasks_impl(
            input_root, output_root, model_name_fallback, mode
        ):
            key = glb_path.resolve()
            if key in seen_glbs:
                continue
            seen_glbs.add(key)
            tasks.append((glb_path, out_dir))
    return sorted(tasks, key=lambda t: str(t[0]))


def _sync_real_head_reference_for_covers(
    *,
    fashion_tag: str,
    all_tasks: list[tuple[Path, Path]],
) -> None:
    """在 ``--pass covers`` 且带 ``--fashion-tag`` 时，把 YAML 数字 ``head_object`` 对应真人照片拷入各 stage9 目录。"""
    from common.doll_real_head_photo import (
        copy_real_head_reference_into_stage9_dirs,
        load_head_object_from_theme_prefs,
        unique_stage9_output_dirs,
    )
    from common.settings import SETTINGS

    dirs = unique_stage9_output_dirs(all_tasks, covers_subdir=SUBDIR_COVERS)
    ho = load_head_object_from_theme_prefs(Path(SETTINGS.output_root), fashion_tag)
    _src, msg = copy_real_head_reference_into_stage9_dirs(
        output_root=Path(SETTINGS.output_root),
        repo_root=REPO_ROOT,
        head_object=ho,
        stage9_dirs=dirs,
    )
    if _src is not None:
        print(f"[RUN] Stage9 真人比对图: {msg}", flush=True)
        print(f"[RUN] 源图: {_src}", flush=True)
    else:
        print(f"[WARN] Stage9 真人比对图: {msg}", flush=True)


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
    run_dirs: Path | list[Path], subdir: str
) -> set[str]:
    """从已选封面目录解析 GLB 主文件名（stem）。

    支持现行布局 ``<run>/<body_template>/<subdir>/*_cover.png``，也兼容旧约定
    ``<run>/<subdir>/*_cover.png``（主题根直下）。``run_dirs`` 可为多个主题根（合并扫描）。
    """
    roots = [run_dirs] if isinstance(run_dirs, Path) else list(run_dirs)
    if not roots:
        return set()
    out: set[str] = set()

    def _consume_selected_dir(d: Path) -> None:
        if not d.is_dir():
            return
        for p in d.glob("*_cover.png"):
            if not p.is_file():
                continue
            # stem 如 哪吒闹海_cover -> 取 哪吒闹海
            s = p.stem
            if s.endswith("_cover"):
                out.add(s[: -len("_cover")])

    for run_dir in roots:
        if not run_dir.is_dir():
            continue
        for d in run_dir.rglob("*"):
            if d.is_dir() and d.name == subdir:
                _consume_selected_dir(d)
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


def _delete_object_tree(obj: bpy.types.Object) -> None:
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    for ch in obj.children_recursive:
        ch.select_set(True)
    bpy.ops.object.delete()


def _obj_has_body_glb_mark(obj: bpy.types.Object) -> bool:
    """判断物体是否带 stage8 body GLB 导入标记（含旧键 figshion_body_glb）。"""
    return any(obj.get(key) for key in _BODY_GLB_MARK_KEYS)


def _set_body_glb_mark(obj: bpy.types.Object) -> None:
    """写入新标记并清除旧键，避免场景中同时存在两套自定义属性。"""
    obj[_BODY_GLB_MARK_KEY] = 1
    if _LEGACY_BODY_GLB_MARK_KEY in obj:
        del obj[_LEGACY_BODY_GLB_MARK_KEY]


def _find_body_glb_import_roots() -> list[bpy.types.Object]:
    """查找带 body GLB 标记的导入根物体（新/旧标记均识别，去重保序）。"""
    roots: list[bpy.types.Object] = []
    seen: set[int] = set()
    for key in _BODY_GLB_MARK_KEYS:
        for obj in _find_marked_import_roots(key):
            oid = id(obj)
            if oid in seen:
                continue
            seen.add(oid)
            roots.append(obj)
    return roots


def remove_blend_preset_body() -> bool:
    """删除工程 ``blender_render_videos.blend`` 预置的 ``body`` 物体（若存在）。"""
    obj = bpy.data.objects.get("body")
    if obj is None:
        return False
    if _obj_has_body_glb_mark(obj):
        return False
    name = obj.name
    _delete_object_tree(obj)
    print(f"已删除工程预置 body 物体: {name!r}", flush=True)
    return True


def _cleanup_orphan_blender_data() -> None:
    """清理无用户的 mesh/material/image 等，避免重名导致导入后变成 ``body.001``。"""
    try:
        bpy.ops.outliner.orphans_purge(
            do_local_ids=True, do_linked_ids=True, do_recursive=True
        )
    except TypeError:
        try:
            bpy.ops.outliner.orphans_purge()
        except Exception as exc:
            print(f"[WARN] orphans_purge 失败: {exc}", flush=True)


_BLEND_PRESET_BODY_REMOVED = False


def ensure_blend_preset_body_removed() -> None:
    """打开 .blend 后首次处理任务前：删除预置 body 并 purge unused（仅执行一次）。"""
    global _BLEND_PRESET_BODY_REMOVED
    if _BLEND_PRESET_BODY_REMOVED:
        return
    if remove_blend_preset_body():
        _cleanup_orphan_blender_data()
        print("[RUN] 工程预置 body 已清除并完成 purge unused", flush=True)
    _BLEND_PRESET_BODY_REMOVED = True


def cleanup_body() -> None:
    """删除场景中 ``body`` / ``body.001`` … 及其子层级（含上轮 stage8 导入）。"""
    _cleanup_objects_by_name_re(_BODY_OBJECT_NAME_RE, label="body")


def _purge_body_glb_marked() -> None:
    for obj in list(bpy.data.objects):
        if _obj_has_body_glb_mark(obj):
            bpy.data.objects.remove(obj, do_unlink=True)


def import_body_from_stage8_glb(glb_path: Path) -> list[bpy.types.Object]:
    """从 stage8 输出导入该模型 body GLB：删上轮 body → purge unused → 导入 → 命名为 ``body``。"""
    _purge_body_glb_marked()
    cleanup_body()
    _cleanup_orphan_blender_data()

    print(f"[RUN] 从 stage8 导入 body GLB: {glb_path}", flush=True)
    before_ids = {id(o) for o in bpy.data.objects}
    bpy.ops.import_scene.gltf(filepath=str(glb_path))
    imported_objs = [o for o in bpy.data.objects if id(o) not in before_ids]
    if not imported_objs:
        print(f"[ERROR] stage8 GLB 未导入任何物体: {glb_path}", file=sys.stderr)
        return []
    for o in imported_objs:
        _set_body_glb_mark(o)
    imported_set = set(imported_objs)
    import_roots = [o for o in imported_objs if o.parent is None or o.parent not in imported_set]
    for root in import_roots:
        root.scale = (0.1, 0.1, 0.1)
    _canonicalize_body_object_name(imported_objs)
    return imported_objs


def cleanup_head_hair_import_slots() -> None:
    """每轮导入 head/hair 前：按标记与 canonical 名清理（不触碰 body，body 由 stage8 导入流程处理）。"""
    _purge_real_head_marked()
    _purge_solid_hair_marked()
    _purge_textured_hair_glb_marked()
    cleanup_head()
    cleanup_hair()
    _cleanup_orphan_blender_data()


def _cleanup_objects_by_name_re(name_re: re.Pattern[str], *, label: str) -> None:
    bpy.ops.object.select_all(action="DESELECT")
    candidates = {o for o in bpy.data.objects if name_re.match(o.name)}
    if not candidates:
        return
    roots = [o for o in candidates if o.parent not in candidates]
    names = [o.name for o in roots]
    for name in names:
        obj = bpy.data.objects.get(name)
        if obj is None:
            continue
        _delete_object_tree(obj)
    print(f"已清理 {label} 物体及其子层级: {', '.join(names)}", flush=True)


def cleanup_head() -> None:
    """删除 ``head`` / ``head.001`` … 及其子层级（每轮导入/导出前调用）。"""
    _cleanup_objects_by_name_re(_HEAD_OBJECT_NAME_RE, label="head")


def cleanup_hair() -> None:
    """删除 ``hair`` / ``hair.001`` … 及其子层级（每轮导入/导出前调用）。"""
    _cleanup_objects_by_name_re(_HAIR_OBJECT_NAME_RE, label="hair")


def _find_marked_import_roots(mark_key: str) -> list[bpy.types.Object]:
    marked = [o for o in bpy.data.objects if o.get(mark_key)]
    if not marked:
        return []
    marked_set = set(marked)
    return [o for o in marked if o.parent is None or o.parent not in marked_set]


def _ensure_unique_object_name(obj: bpy.types.Object, target_name: str) -> None:
    """将 ``obj`` 重命名为 ``target_name``；若已有同名且非同一物体则先删除冲突项（含子层级）。"""
    target = target_name.strip()
    if not target:
        return
    existing = bpy.data.objects.get(target)
    if existing is not None and existing != obj:
        bpy.ops.object.select_all(action="DESELECT")
        existing.select_set(True)
        for ch in existing.children_recursive:
            ch.select_set(True)
        bpy.ops.object.delete()
    if obj.name != target:
        obj.name = target
        print(f"已重命名物体 -> {target!r}", flush=True)


def _find_object_by_name_or_config(config_name: str) -> bpy.types.Object | None:
    """按配置名查找物体（精确匹配，忽略大小写）。"""
    key = (config_name or "").strip()
    if not key:
        return None
    obj = bpy.data.objects.get(key)
    if obj is not None:
        return obj
    key_lower = key.lower()
    for candidate in bpy.data.objects:
        if candidate.name.lower() == key_lower:
            return candidate
    return None


def _canonicalize_body_object_name(imported_objs: list[bpy.types.Object]) -> None:
    """将本轮导入的 stage8 body GLB 根物体统一命名为 ``body``（非 ``body.001``）。"""
    if not imported_objs:
        print("[WARN] 本轮未导入任何 body GLB 物体", flush=True)
        return
    imported_set = set(imported_objs)
    for o in imported_objs:
        if _BODY_OBJECT_NAME_RE.match(o.name):
            _ensure_unique_object_name(o, "body")
            return
    roots = _find_body_glb_import_roots()
    if not roots:
        roots = [o for o in imported_objs if o.parent is None or o.parent not in imported_set]
    if roots:
        _ensure_unique_object_name(roots[0], "body")
        return
    print("[WARN] 无法定位导入 body GLB 的根物体", flush=True)


def _canonicalize_composite_object_names(
    head_config: str,
    hair_config: str,
    imported_body_objs: list[bpy.types.Object],
) -> None:
    """导出前统一 body/head/hair 命名：导入 body→body；内置头/发或导入头/发→head/hair。"""
    _canonicalize_body_object_name(imported_body_objs)

    head_cfg = (head_config or "").strip()
    hair_cfg = (hair_config or "").strip()
    use_real_head = normalize_real_head_template_id(head_cfg) is not None

    if use_real_head:
        roots = _find_marked_import_roots("real_head_120k")
        if roots:
            _ensure_unique_object_name(roots[0], "head")
        else:
            print("[WARN] 未找到 real_head_120k 导入根，跳过 head 重命名", flush=True)
    elif head_cfg:
        head_obj = _find_object_by_name_or_config(head_cfg)
        if head_obj is not None:
            _ensure_unique_object_name(head_obj, "head")
        else:
            print(f"[WARN] 内置头物体未找到: {head_cfg!r}，跳过重命名", flush=True)

    imported_hair_roots: list[bpy.types.Object] = []
    for key in ("solid_hair", "textured_hair_glb"):
        imported_hair_roots.extend(_find_marked_import_roots(key))
    if imported_hair_roots:
        _ensure_unique_object_name(imported_hair_roots[0], "hair")
    elif hair_cfg:
        hair_obj = _find_object_by_name_or_config(hair_cfg)
        if hair_obj is not None:
            _ensure_unique_object_name(hair_obj, "hair")
        else:
            print(f"[WARN] 头发物体未找到: {hair_cfg!r}，跳过重命名", flush=True)

    for slot in ("body", "head", "hair"):
        o = bpy.data.objects.get(slot)
        print(
            f"[CANON] 合成导出槽位 {slot}: {o.name!r} ({o.type})" if o else f"[CANON] 合成导出槽位 {slot}: 缺失",
            flush=True,
        )


def _unhide_object_tree(obj: bpy.types.Object) -> None:
    obj.hide_set(False)
    obj.hide_viewport = False
    obj.hide_render = False
    for ch in obj.children_recursive:
        ch.hide_set(False)
        ch.hide_viewport = False
        ch.hide_render = False


def _restore_template_head_hair_names(head_config: str, hair_config: str) -> None:
    """批处理多个 GLB 时，将内置头/发从 ``head``/``hair`` 还原为 YAML 名，避免下轮 cleanup 删掉模板。"""
    head_cfg = (head_config or "").strip()
    hair_cfg = (hair_config or "").strip()
    if normalize_real_head_template_id(head_cfg) is not None:
        return

    head_obj = bpy.data.objects.get("head")
    if head_obj is not None and head_cfg and _HEAD_TEMPLATE_RE.match(head_cfg):
        if head_obj.name != head_cfg:
            head_obj.name = head_cfg
            print(f"已还原内置头名称 -> {head_cfg!r}", flush=True)

    hair_obj = bpy.data.objects.get("hair")
    if hair_obj is None or not hair_cfg:
        return
    if hair_obj.get("solid_hair") or hair_obj.get("textured_hair_glb"):
        return
    if _HAIR_TEMPLATE_RE.match(hair_cfg) and hair_obj.name != hair_cfg:
        hair_obj.name = hair_cfg
        print(f"已还原内置发名称 -> {hair_cfg!r}", flush=True)


def _collect_composite_export_roots() -> list[bpy.types.Object]:
    roots: list[bpy.types.Object] = []
    for name in ("body", "head", "hair"):
        obj = bpy.data.objects.get(name)
        if obj is not None:
            roots.append(obj)
    return roots


_COMPOSITE_EXPORT_SCALE = (1.0, 1.0, 1.0)


def _snapshot_composite_slot_scales() -> dict[str, tuple[float, float, float]]:
    snap: dict[str, tuple[float, float, float]] = {}
    for name in ("body", "head", "hair"):
        obj = bpy.data.objects.get(name)
        if obj is not None:
            snap[name] = (obj.scale[0], obj.scale[1], obj.scale[2])
    return snap


def _set_composite_slot_scales(scale: tuple[float, float, float]) -> None:
    for name in ("body", "head", "hair"):
        obj = bpy.data.objects.get(name)
        if obj is not None:
            obj.scale = scale


def _restore_composite_slot_scales(snap: dict[str, tuple[float, float, float]]) -> None:
    for name, scale in snap.items():
        obj = bpy.data.objects.get(name)
        if obj is not None:
            obj.scale = scale


def export_composite_glb(output_path: Path) -> bool:
    """导出 body + head + hair 合成 GLB（带材质与贴图）。

    渲染阶段 body/head/hair 根级 scale 为 0.1；仅在调用 glTF 导出前临时改为 1.0，导出后还原。
    """
    missing = [n for n in ("body", "head", "hair") if bpy.data.objects.get(n) is None]
    if missing:
        print(
            f"[ERROR] 合成 GLB 缺少物体 {', '.join(missing)}，跳过导出: {output_path.name}",
            flush=True,
        )
        return False

    roots = _collect_composite_export_roots()
    if len(roots) < 3:
        print(f"[ERROR] 合成 GLB 导出槽位不完整（{len(roots)}/3）: {output_path.name}", flush=True)
        return False

    scale_snap = _snapshot_composite_slot_scales()
    _set_composite_slot_scales(_COMPOSITE_EXPORT_SCALE)
    print(
        "[RUN] 合成 GLB 导出前已将 body/head/hair scale 设为 1.0（导出后还原渲染用 scale）",
        flush=True,
    )
    try:
        ensure_dir(output_path.parent)
        bpy.ops.object.select_all(action="DESELECT")
        for root in roots:
            _unhide_object_tree(root)
            root.select_set(True)
            for ch in root.children_recursive:
                ch.select_set(True)

        export_kw: dict = {
            "filepath": str(output_path.resolve()),
            "use_selection": True,
            "export_format": "GLB",
            "export_materials": "EXPORT",
            "export_image_format": "AUTO",
            "export_texcoords": True,
            "export_normals": True,
        }
        try:
            bpy.ops.export_scene.gltf(**export_kw)
        except TypeError:
            # 兼容旧版 Blender：部分参数名不同或不存在
            export_kw.pop("export_image_format", None)
            bpy.ops.export_scene.gltf(**export_kw)

        if not _looks_valid_glb(output_path):
            print(f"[WARN] 合成 GLB 导出后校验失败: {output_path}", flush=True)
            return False
        print(f"已导出合成 GLB（body+head+hair）: {output_path}", flush=True)
        return True
    finally:
        _restore_composite_slot_scales(scale_snap)


def composite_glb_path(output_dir: Path, glb_stem: str) -> Path:
    return output_dir / f"{glb_stem}{_COMPOSITE_GLB_SUFFIX}"


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


def _hide_all_builtin_heads() -> None:
    """隐藏工程中所有 ``female|male_*_head``（用于改为导入 real_head_120k OBJ）。"""
    for obj in bpy.data.objects:
        if _HEAD_TEMPLATE_RE.match(obj.name):
            obj.hide_render = True
            obj.hide_viewport = True


def _hide_all_builtin_hairs_except(keep: str | None) -> None:
    """隐藏内置头发模板；若 ``keep`` 非空则仅保留该名的可见性。"""
    keep = (keep or "").strip()
    for obj in bpy.data.objects:
        if _HAIR_TEMPLATE_RE.match(obj.name):
            hide = (not keep) or (obj.name != keep)
            obj.hide_render = hide
            obj.hide_viewport = hide
    if keep:
        ho = bpy.data.objects.get(keep)
        if ho is not None:
            ho.hide_render = False
            ho.hide_viewport = False


def _purge_real_head_marked() -> None:
    for obj in list(bpy.data.objects):
        if obj.get("real_head_120k"):
            bpy.data.objects.remove(obj, do_unlink=True)


def _set_principled_metallic_roughness(material: bpy.types.Material, *, metallic: float, roughness: float) -> None:
    if not material.use_nodes:
        material.use_nodes = True
    nt = material.node_tree
    if nt is None:
        return
    bsdf = nt.nodes.get("Principled BSDF") or next(
        (n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"),
        None,
    )
    if bsdf is None:
        return
    if "Metallic" in bsdf.inputs:
        bsdf.inputs["Metallic"].default_value = metallic
    if "Roughness" in bsdf.inputs:
        bsdf.inputs["Roughness"].default_value = roughness


def _apply_real_head_principled_defaults() -> None:
    """导入的 real_head 网格：Principled Metallic=0、Roughness=1（不改动 Base Color 链接）。"""
    seen: set[bpy.types.Material] = set()
    for obj in bpy.data.objects:
        if not obj.get("real_head_120k"):
            continue
        for o in [obj] + list(obj.children_recursive):
            if o.type != "MESH" or o.data is None:
                continue
            for slot in o.material_slots:
                mat = slot.material
                if mat is None or mat in seen:
                    continue
                seen.add(mat)
                _set_principled_metallic_roughness(mat, metallic=0.0, roughness=1.0)


def _import_real_head_mesh(abs_path: str) -> list[bpy.types.Object]:
    """从 ``mcr_head.glb``（或环境变量覆盖的 glb/obj 路径）导入；根级缩放 0.1，与身体 GLB 一致。"""
    p = Path(abs_path)
    before_ids = {id(o) for o in bpy.data.objects}
    fp = str(p.resolve()).replace("\\", "/")
    ext = p.suffix.lower()
    if ext == ".glb":
        bpy.ops.import_scene.gltf(filepath=fp)
    elif ext == ".obj":
        try:
            bpy.ops.wm.obj_import(filepath=fp)
        except AttributeError:
            bpy.ops.import_scene.obj(filepath=fp, axis_forward="-Z", axis_up="Y")
    else:
        print(f"[ERROR] 不支持的 real_head 网格扩展名: {p.suffix!r}（{abs_path}）", file=sys.stderr)
        sys.exit(1)
    new_objs = [o for o in bpy.data.objects if id(o) not in before_ids]
    for o in new_objs:
        o["real_head_120k"] = 1
    new_set = set(new_objs)
    for root in (o for o in new_objs if o.parent is None or o.parent not in new_set):
        root.scale = (0.1, 0.1, 0.1)
    return new_objs


def configure_visible_head_hair(head_name: str, hair_name: str) -> None:
    """隐藏所有 ``female_*_{head,hair}`` / ``male_*_{head,hair}``，仅保留配置中的头/发参与渲染。"""
    head = (head_name or "").strip()
    hair = (hair_name or "").strip()
    active = {head} if head else set()
    # solid 发型 id（female_hair_14）不在 .blend 内，不参与内置头/发可见性切换
    if hair and not is_solid_hair_style_id(hair):
        active.add(hair)

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


def _purge_textured_hair_glb_marked() -> None:
    for obj in list(bpy.data.objects):
        if obj.get("textured_hair_glb"):
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


# solid / 内置头发：清空导入材质后新建 Principled；Base Color 来自 hair_color 解析后的 sRGB
_HAIR_PRINCIPLED_METALLIC = 0.3
_HAIR_PRINCIPLED_ROUGHNESS = 0.7


def _new_hair_principled_material(obj_name: str, rgb: tuple[float, float, float]) -> bpy.types.Material:
    """新建仅含 ``Material Output`` + ``Principled BSDF`` 的材质（不复用 OBJ/工程内旧节点树）。"""
    safe = (obj_name or "Hair").replace(".", "_")[:60]
    mat = bpy.data.materials.new(name=f"AntiverseHair_{safe}")
    mat.use_nodes = True
    nt = mat.node_tree
    if nt is None:
        return mat
    nt.nodes.clear()
    nodes = nt.nodes
    links = nt.links
    out = nodes.new(type="ShaderNodeOutputMaterial")
    out.location = (300, 0)
    bsdf = nodes.new(type="ShaderNodeBsdfPrincipled")
    bsdf.location = (0, 0)
    links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    bsdf.inputs["Base Color"].default_value = (rgb[0], rgb[1], rgb[2], 1.0)
    bsdf.inputs["Metallic"].default_value = _HAIR_PRINCIPLED_METALLIC
    bsdf.inputs["Roughness"].default_value = _HAIR_PRINCIPLED_ROUGHNESS
    return mat


def _apply_rgb_to_materials_of_object(obj: bpy.types.Object, rgb: tuple[float, float, float]) -> None:
    """对头发网格：移除全部原有材质槽，再挂单一新建 Principled（Base Color = ``rgb``，Metallic / Roughness 见上常量）。"""
    if obj.type != "MESH" or obj.data is None:
        return
    mesh = obj.data
    mesh.materials.clear()
    mat = _new_hair_principled_material(obj.name, rgb)
    mesh.materials.append(mat)
    for poly in mesh.polygons:
        poly.material_index = 0


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
    *,
    textured_hair_glb_path: Path | None = None,
) -> None:
    """内置头或 real_head_120k（优先 ``mcr_head.glb``）；solid_hair / 内置头发 / 可选贴图头发 GLB。

    若 ``textured_hair_glb_path`` 指向有效文件则导入该 GLB（卡通人偶 Stage8b），不再使用 solid OBJ / 纯色染发。
    """
    head = (head_name or "").strip()
    hair = (hair_name or "").strip()
    hex_s = resolve_hair_hex(hair_color_key, default="#0D0D0D")
    rgb = hex_to_linear_rgb01(hex_s)
    sp = solid_hair_obj_path(repo, hair)

    _tid = normalize_real_head_template_id(head)
    if _tid is not None:
        rh_path = resolve_existing_real_head_mesh(SETTINGS.real_head_120k_root, _tid)
        if rh_path is None:
            tried = "\n  ".join(str(p) for p in candidate_paths_for_template_id(SETTINGS.real_head_120k_root, _tid))
            print(
                f"[ERROR] head_object=template_id {_tid!r}，但在下列路径均未找到头部网格：\n  {tried}\n"
                f"  REAL_HEAD_120K_ROOT={SETTINGS.real_head_120k_root}\n"
                "  可设置 REAL_HEAD_MESH_REL_PATTERN 或补齐数据。",
                file=sys.stderr,
            )
            sys.exit(1)
        _purge_real_head_marked()
        _purge_solid_hair_marked()
        _purge_textured_hair_glb_marked()
        _hide_all_builtin_heads()
        print(f"[RUN] real_head_120k: 导入 {rh_path}（scale=0.1, Metallic=0, Roughness=1）", flush=True)
        _import_real_head_mesh(str(rh_path))
        _apply_real_head_principled_defaults()
        if textured_hair_glb_path is not None and textured_hair_glb_path.is_file():
            _hide_all_builtin_hairs_except("")
            print(f"[RUN] 贴图头发 GLB（Stage8b）: {textured_hair_glb_path}", flush=True)
            _import_textured_hair_glb(str(textured_hair_glb_path.resolve()))
            print(
                "头/发: real_head template_id + 贴图头发 GLB；工程内 female|male_*_hair 已隐藏。",
                flush=True,
            )
            return
        if sp is not None:
            _hide_all_builtin_hairs_except("")
            print(f"[RUN] solid hair: 导入 {sp} 发色={hair_color_key!r} -> {hex_s}", flush=True)
            _import_solid_hair_obj(str(sp.resolve()))
            _apply_solid_hair_color(rgb)
            print(
                "头/发: real_head template_id + solid hair OBJ；工程内 female|male_*_head 已隐藏。",
                flush=True,
            )
        else:
            _hide_all_builtin_hairs_except(hair)
            ho = bpy.data.objects.get(hair)
            if ho is not None:
                _apply_rgb_to_materials_of_object(ho, rgb)
                for ch in ho.children_recursive:
                    if ch.type == "MESH":
                        _apply_rgb_to_materials_of_object(ch, rgb)
                print(f"[RUN] 已为内置头发 {hair!r} 设置 Base Color ≈ {hex_s}", flush=True)
            else:
                print(f"[WARN] 场景中未找到内置头发物体: {hair!r}", flush=True)
            print(
                f"头/发: real_head template_id={head!r} + 内置发 {hair!r}；工程内内置头已隐藏。",
                flush=True,
            )
        return

    if sp is not None:
        _purge_solid_hair_marked()
        _purge_textured_hair_glb_marked()
        _hide_all_template_head_hair()
        _unhide_objects_by_names({head})
        print(f"[RUN] solid hair: 导入 {sp} 发色={hair_color_key!r} -> {hex_s}", flush=True)
        _import_solid_hair_obj(str(sp.resolve()))
        _apply_solid_hair_color(rgb)
        print(
            f"头/发可见性: 头={head!r}；头发为 solid_hair OBJ；模板 female|male_*_hair 已 hide_render。",
            flush=True,
        )
        return

    if is_solid_hair_style_id(hair):
        expected = repo / "resource" / "blender" / "solid_hair" / hair.strip() / "low_poly" / "hair.obj"
        print(
            f"[ERROR] hair_object={hair!r} 为 solid 发型 id，但未找到: {expected}\n"
            f"  请确认 resource/blender/solid_hair/{hair}/low_poly/hair.obj 存在。",
            file=sys.stderr,
        )
        sys.exit(1)

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


def _import_textured_hair_glb(abs_path: str) -> list[bpy.types.Object]:
    """导入 Stage8b 头发 GLB；根级缩放 0.1，并 tweak 材质 Metallic/Roughness。"""
    before_ids = {id(o) for o in bpy.data.objects}
    fp = abs_path.replace("\\", "/")
    bpy.ops.import_scene.gltf(filepath=fp)
    new_objs = [o for o in bpy.data.objects if id(o) not in before_ids]
    for o in new_objs:
        o["textured_hair_glb"] = 1
    new_set = set(new_objs)
    roots = [o for o in new_objs if o.parent is None or o.parent not in new_set]
    for root in roots:
        root.scale = (0.1, 0.1, 0.1)
        tweak_body_materials(root)
    return roots


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


def _maybe_save_debug_blend(output_dir: Path, glb_stem: str, enabled: bool) -> None:
    """``--debug``：将当前 .blend 场景写入 ``output_dir/<stem>_render_debug.blend``。"""
    if not enabled:
        return
    ensure_dir(output_dir)
    out = (output_dir / f"{glb_stem}_render_debug.blend").resolve()
    prev_fp = getattr(bpy.data, "filepath", "")
    try:
        bpy.ops.wm.save_as_mainfile(filepath=str(out), check_existing=False)
        print(f"[DEBUG] 已导出场景: {out}", flush=True)
    except Exception as exc:
        print(f"[WARN] --debug 导出 .blend 失败 ({out}): {exc}", flush=True)
    finally:
        try:
            bpy.data.filepath = prev_fp
        except AttributeError:
            # Blender 4.x 起 BlendData.filepath 只读，无法还原；调试导出不影响后续同进程渲染。
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
    export_composite: bool = False,
    skip_render: bool = False,
    scene_args: SimpleNamespace | None = None,
) -> None:
    if not glb_path.is_file():
        print(f"文件不存在: {glb_path}")
        return

    debug = bool(scene_args is not None and getattr(scene_args, "debug", False))

    cleanup_head_hair_import_slots()
    imported_objs = import_body_from_stage8_glb(glb_path)
    if not imported_objs:
        return

    head_cfg = ""
    hair_cfg = ""
    if scene_args is not None:
        run_dir = glb_path.parent.parent
        pdata = load_render_prefs_merged(run_dir)
        hair_tex = resolve_textured_hair_glb_path(run_dir, glb_path.stem, pdata)
        head_cfg = str(pdata.get("head_object") or scene_args.head_object or "").strip()
        hair_cfg = str(pdata.get("hair_object") or scene_args.hair_object or "").strip()
        hair_color_key = str(
            pdata.get("hair_color") or getattr(scene_args, "hair_color", None) or "black"
        ).strip()
        configure_head_and_hair(
            head_cfg,
            hair_cfg,
            hair_color_key,
            REPO_ROOT,
            textured_hair_glb_path=hair_tex,
        )

    _canonicalize_composite_object_names(head_cfg, hair_cfg, imported_objs)

    body_obj = bpy.data.objects.get("body")
    if body_obj:
        body_obj.scale = (0.1, 0.1, 0.1)
        set_focus(body_obj)
        tweak_body_materials(body_obj)

    if export_composite:
        export_composite_glb(composite_glb_path(output_dir, glb_path.stem))

    if skip_render:
        _maybe_save_debug_blend(output_dir, glb_path.stem, debug)
        _restore_template_head_hair_names(head_cfg, hair_cfg)
        return

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
            _maybe_save_debug_blend(output_dir, glb_path.stem, debug)
            _restore_template_head_hair_names(head_cfg, hair_cfg)
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

    _maybe_save_debug_blend(output_dir, glb_path.stem, debug)
    _restore_template_head_hair_names(head_cfg, hair_cfg)


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


def _looks_valid_glb(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        if path.stat().st_size < 1024:
            return False
        with path.open("rb") as f:
            magic = f.read(4)
        return magic == b"glTF"
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
    only_export: bool = False,
) -> None:
    if not tasks:
        print("本 worker 无任务，跳过")
        return
    ensure_blend_preset_body_removed()
    export_composite = cover_only
    if only_export and not cover_only:
        print("[ERROR] --only-export 仅适用于 --pass covers", file=sys.stderr)
        raise SystemExit(2)

    if not only_export:
        ensure_cycles_cuda()
        setup_world_environment_hdri(WORLD_HDRI_PATH)

    resume = bool(getattr(args, "resume", False))
    per_random = bool(getattr(args, "random_studio_tint", False))
    raw_hex: str | None = getattr(args, "studio_tint_hex", None)
    tint_resolved: str | None
    if raw_hex and not per_random:
        tint_resolved = _parse_hex_tint(raw_hex)
    else:
        tint_resolved = None

    for glb_path, out_dir in tasks:
        if not only_export:
            rng = random.Random()
            if per_random:
                set_background_tint(hex_explicit=None, per_model_random=True, rng=rng)
            else:
                set_background_tint(hex_explicit=tint_resolved, per_model_random=False, rng=rng)

        if cover_only:
            composite_path = composite_glb_path(out_dir, glb_path.stem)
            need_export = export_composite
            need_opaque = not only_export
            need_rgba = not only_export
            if resume:
                if need_export and _looks_valid_glb(composite_path):
                    need_export = False
                if not only_export:
                    cover_png = out_dir / f"{glb_path.stem}_cover.png"
                    rgba_png = out_dir / f"{glb_path.stem}_cover_rgba.png"
                    if _looks_valid_png(cover_png):
                        need_opaque = False
                    if _looks_valid_png(rgba_png):
                        need_rgba = False
            if only_export:
                if not need_export:
                    print(f"[SKIP] 已有有效合成 GLB: {glb_path.stem}", flush=True)
                    continue
            elif not need_export and not need_opaque and not need_rgba:
                print(f"[SKIP] 已有有效封面(含透明)与合成 GLB: {glb_path.stem}", flush=True)
                continue
            elif not need_opaque and not need_rgba and need_export:
                print(f"[RUN] 封面已齐，补导出合成 GLB: {glb_path.stem}", flush=True)
            render_one_glb(
                glb_path,
                out_dir,
                fps=args.fps,
                seconds=args.seconds,
                cover_only=True,
                write_still=True,
                render_cover_opaque=need_opaque,
                render_cover_rgba=need_rgba,
                export_composite=need_export,
                skip_render=only_export,
                scene_args=args,
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
                scene_args=args,
            )
        print(f"[OK] {glb_path} -> {out_dir}")


def main() -> None:
    worker_id_env = os.environ.get("BLENDER_WORKER_ID")
    if worker_id_env is not None:
        args = _args_from_env()
    else:
        args = parse_cli_args()
        apply_resolved_input_root(args)

    input_roots = [Path(p) for p in getattr(args, "input_roots", None) or [args.input_root]]
    ft_prefs = (getattr(args, "fashion_tag", None) or "").strip()
    if ft_prefs and worker_id_env is None:
        try:
            prefs_root = resolve_fashion_tag_run_dir(SETTINGS.output_root, ft_prefs)
        except FileNotFoundError as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            raise SystemExit(2) from exc
        prefs_written = sync_pipeline_render_prefs_at_start(prefs_root, args)
        print(f"[RUN] 已同步 pipeline_render_prefs.yml: {prefs_written}", flush=True)
    elif not ft_prefs:
        ho = (getattr(args, "head_object", None) or "").strip()
        ha = (getattr(args, "hair_object", None) or "").strip()
        if not ho or not ha:
            print(
                "[ERROR] 未指定 --fashion-tag 时，必须在命令行指定 "
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
    roots_label = ", ".join(str(p) for p in input_roots)
    print(
        f"[RUN] 扫描根目录: {roots_label}  pass={render_pass}  output_mode={mode}",
        flush=True,
    )
    all_tasks = collect_tasks(input_roots, output_root, args.model_name, mode)

    if mode == "videos" and not all_glbs:
        stems = resolve_stems_from_selected_covers(input_roots, sub_sel)
        if not stems:
            print(
                f"[ERROR] --pass videos 且未加 --all-glbs 时，需要在「本 run 根」下（含各服装模板子目录）"
                f"建立「{sub_sel}」并放入所选的 <模型名>_cover.png（如从 stage9 复制）。"
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
    only_export = bool(getattr(args, "only_export", False))
    if only_export and render_pass != "covers":
        print("[ERROR] --only-export 仅适用于 --pass covers", file=sys.stderr)
        raise SystemExit(2)

    if cover_only and ft_prefs and worker_id_env is None and not only_export:
        _sync_real_head_reference_for_covers(fashion_tag=ft_prefs, all_tasks=all_tasks)

    workers = int(os.environ.get("BLENDER_WORKERS", str(args.workers)))
    if worker_id_env is not None:
        from common.blender_render_pool_lease import acquire_render_slot, release_render_slot

        wid = int(worker_id_env)
        chunk = tasks_for_worker(all_tasks, wid, workers)
        print(f"Worker {wid}/{workers}，任务数 {len(chunk)}", flush=True)
        acquire_render_slot()
        try:
            process_tasks(
                chunk, args, cover_only=cover_only, write_still=write_still, only_export=only_export
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
        process_tasks(all_tasks, args, cover_only=cover_only, write_still=write_still, only_export=only_export)
    finally:
        release_render_slot()


if __name__ == "__main__":
    main()
