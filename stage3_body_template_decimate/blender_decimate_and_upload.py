"""Stage 3: Decimate body.obj, export OBJ, upload to OSS, save CSV.

Run:
blender -b --python-use-system-env -P stage3_body_template_decimate/blender_decimate_and_upload.py

断点续跑（仅跳过「减面导出成功且 OSS 已上传」的模板：本地 body.obj 有效且 CSV 中 public_url/oss_key 齐全；每更新一行即写回完整 CSV）：

blender -b --python-use-system-env -P stage3_body_template_decimate/blender_decimate_and_upload.py -- --resume

只处理若干套模板（与已有 ``stage3_body_template_decimate.csv`` **合并**写入，其它 ``template_name`` 行保留）：

blender -b --python-use-system-env -P stage3_body_template_decimate/blender_decimate_and_upload.py -- --templates body_05

``--resume`` 与 ``--templates`` 可同用。

注意：「--」不可省略。若写成「-P …py --resume」，Blender 在脚本结束后会把「--resume」当成要打开的 .blend 路径并报错。
"""

from __future__ import annotations

import argparse
import csv
import math
import sys
from pathlib import Path

# Blender 内嵌 Python 默认不包含仓库根目录，须先加入才能 import common
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import bpy

from common.oss_client import upload_file
from common.settings import SETTINGS
from common.utils import ensure_dir

MIN_OBJ_BYTES = 256
FIELDNAMES = [
    "template_name",
    "faces_before",
    "faces_after",
    "local_obj",
    "oss_key",
    "public_url",
]

# 减面：用 40万 / 当前面数，向下取一位小数作初始 ratio；减面后须 < 50万 面，否则降低 ratio（步长 0.1）重试
TARGET_FACE_REF = 400_000
MAX_FACE_AFTER = 500_000
MIN_DECIMATE_RATIO = 0.01


def parse_cli_args() -> argparse.Namespace:
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1 :]
    else:
        if "--resume" in argv:
            print(
                "[ERROR] 使用 --resume 时必须在 -P <脚本.py> 之后插入「 -- 」（空格+两个减号+空格），"
                "再写脚本参数；否则 Blender 会把 --resume 当成要打开的工程文件并在脚本结束后报错。\n"
                "正确示例：\n"
                "  blender -b --python-use-system-env "
                "-P stage3_body_template_decimate/blender_decimate_and_upload.py -- --resume",
                file=sys.stderr,
            )
            sys.exit(2)
        argv = []
    parser = argparse.ArgumentParser(description="Stage3 减面导出并上传 OSS")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="跳过已在 CSV 中且本地 body.obj 有效、且 oss_key/public_url 表明已成功上传 OSS 的模板",
    )
    parser.add_argument(
        "--templates",
        nargs="+",
        default=None,
        metavar="NAME",
        help="只处理这些模板目录名（须为 BODY_TEMPLATE_ROOT 下子目录）；默认处理全部；与已有 CSV 合并",
    )
    return parser.parse_args(argv)


def _csv_row_indicates_oss_done(row: dict) -> bool:
    key = (row.get("oss_key") or "").strip()
    url = (row.get("public_url") or "").strip()
    if not key or not url:
        return False
    return url.startswith("http://") or url.startswith("https://")


def load_completed_templates(csv_path: Path, output_root: Path) -> dict[str, dict]:
    """从已有 CSV 读取已成功模板：本地导出有效且 CSV 记录表明 OSS 上传已完成。"""
    if not csv_path.is_file():
        return {}
    out: dict[str, dict] = {}
    try:
        with csv_path.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                name = (row.get("template_name") or "").strip()
                if not name:
                    continue
                local = output_root / name / "body.obj"
                if not local.is_file() or local.stat().st_size < MIN_OBJ_BYTES:
                    continue
                if not _csv_row_indicates_oss_done(row):
                    continue
                out[name] = {
                    "template_name": name,
                    "faces_before": (row.get("faces_before") or "").strip(),
                    "faces_after": (row.get("faces_after") or "").strip(),
                    "local_obj": str(local),
                    "oss_key": (row.get("oss_key") or "").strip(),
                    "public_url": (row.get("public_url") or "").strip(),
                }
    except OSError as exc:
        print(f"[WARN] 读取已有 CSV 失败，将不按 --resume 跳过: {exc}")
    return out


def load_all_csv_rows(csv_path: Path) -> dict[str, dict[str, str]]:
    """读取 CSV 全部数据行，按 template_name 索引（用于 --templates 合并）。"""
    if not csv_path.is_file():
        return {}
    out: dict[str, dict[str, str]] = {}
    try:
        with csv_path.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                name = (row.get("template_name") or "").strip()
                if not name:
                    continue
                out[name] = {k: str(row.get(k) or "").strip() for k in FIELDNAMES}
    except OSError as exc:
        print(f"[WARN] 读取 CSV 合并失败，将仅从空表开始: {exc}")
        return {}
    return out


def list_template_dirs(*, only_names: frozenset[str] | None) -> tuple[list[Path], frozenset[str]]:
    all_dirs = sorted(p for p in SETTINGS.template_root.iterdir() if p.is_dir())
    if only_names is None:
        return all_dirs, frozenset()
    by_name = {p.name: p for p in all_dirs}
    ordered = [by_name[n] for n in sorted(only_names) if n in by_name]
    missing = frozenset(n for n in only_names if n not in by_name)
    return ordered, missing


def write_merged_csv(csv_path: Path, merged_rows: dict[str, dict[str, str]]) -> None:
    """按 template_name 排序写回完整 CSV（每成功 / 每 --resume 跳过后调用，便于断点）。"""
    ensure_dir(csv_path.parent)
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        for name in sorted(merged_rows):
            writer.writerow(merged_rows[name])


def cleanup_objects() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()


def import_obj(path: Path):
    bpy.ops.wm.obj_import(filepath=str(path))
    selected = list(bpy.context.selected_objects)
    if not selected:
        raise RuntimeError(f"导入失败: {path}")
    return selected


def mesh_polygon_count(objects: list) -> int:
    """导入物体上所有网格的多边形数（与 Blender 面片统计一致）。"""
    total = 0
    for obj in objects:
        if obj.type != "MESH" or obj.data is None:
            continue
        total += len(obj.data.polygons)
    return total


def initial_decimate_ratio(face_count: int) -> float:
    """40万 / 面数，向下取一位小数；不超过 1.0，不低于 MIN_DECIMATE_RATIO。"""
    if face_count <= 0:
        return 1.0
    raw = min(1.0, TARGET_FACE_REF / face_count)
    ratio = math.floor(raw * 10 + 1e-12) / 10.0
    if ratio < MIN_DECIMATE_RATIO:
        return MIN_DECIMATE_RATIO
    return ratio


def decimate_meshes(objects: list, ratio: float) -> None:
    for obj in objects:
        if obj.type != "MESH":
            continue
        bpy.context.view_layer.objects.active = obj
        modifier = obj.modifiers.new(name="Decimate", type="DECIMATE")
        modifier.decimate_type = "COLLAPSE"
        modifier.ratio = ratio
        modifier.use_collapse_triangulate = True
        bpy.ops.object.modifier_apply(modifier=modifier.name)


def adaptive_decimate_from_src(src_obj: Path, log_label: str) -> tuple[list, int, int]:
    """自磁盘导入、按自适应 ratio 减面；减面后多边形数须 < MAX_FACE_AFTER，否则降低 ratio 重新导入再试。

    返回 (导入并减面后的物体列表, 减面前多边形总数, 减面后多边形总数)。
    """
    cleanup_objects()
    probe = import_obj(src_obj)
    faces_before = mesh_polygon_count(probe)
    if faces_before <= 0:
        cleanup_objects()
        raise RuntimeError(f"{log_label} 导入后无多边形面片")

    ratio = initial_decimate_ratio(faces_before)

    while True:
        cleanup_objects()
        imported = import_obj(src_obj)
        decimate_meshes(imported, ratio)
        faces_after = mesh_polygon_count(imported)

        if faces_after < MAX_FACE_AFTER:
            print(
                f"[DECIMATE] {log_label} 面片 {faces_before} -> {faces_after}, ratio={ratio}"
            )
            return imported, faces_before, faces_after

        if ratio <= MIN_DECIMATE_RATIO:
            print(
                f"[WARN] {log_label} 减面后仍 {faces_after} 面片（>= {MAX_FACE_AFTER}），"
                f"ratio 已为下限 {MIN_DECIMATE_RATIO}，仍导出"
            )
            return imported, faces_before, faces_after

        next_ratio = max(MIN_DECIMATE_RATIO, round(ratio - 0.1, 1))
        print(
            f"[DECIMATE] {log_label} 减面后 {faces_after} 面片（>= {MAX_FACE_AFTER}），"
            f"ratio {ratio} -> {next_ratio} 重试"
        )
        ratio = next_ratio


def export_obj(path: Path) -> None:
    ensure_dir(path.parent)
    bpy.ops.wm.obj_export(filepath=str(path), export_selected_objects=True)


def main() -> None:
    args = parse_cli_args()
    output_root = SETTINGS.output_root / "stage3_body_template_decimate"
    csv_path = SETTINGS.output_root / "stage3_body_template_decimate.csv"
    ensure_dir(output_root)
    ensure_dir(csv_path.parent)

    only = frozenset(x.strip() for x in (args.templates or []) if x.strip()) or None
    template_dirs, missing = list_template_dirs(only_names=only)
    if missing:
        print(f"[WARN] 以下名称不在 template_root 下，已忽略: {', '.join(sorted(missing))}", flush=True)
    if only:
        print(f"[INFO] template_root={SETTINGS.template_root}", flush=True)
        print(f"[INFO] 仅处理: {', '.join(p.name for p in template_dirs) or '（无匹配目录）'}", flush=True)

    has_src = [p for p in template_dirs if (p / "high_poly" / "body.obj").is_file()]
    if only and not has_src:
        print("[ERROR] 请求的模板均缺少 high_poly/body.obj，无可执行项", flush=True)
        raise SystemExit(1)

    done = load_completed_templates(csv_path, output_root) if args.resume else {}
    if args.resume and done:
        print(f"[--resume] 已载入 {len(done)} 个可跳过的「本地 OBJ + OSS 已完成」模板记录")

    merged_rows: dict[str, dict[str, str]] = load_all_csv_rows(csv_path) if only else {}

    skipped = 0
    failed = 0
    ok_new = 0

    for template_dir in template_dirs:
        name = template_dir.name
        src_obj = template_dir / "high_poly" / "body.obj"
        if not src_obj.exists():
            print(f"[SKIP] {name} 缺少 high_poly/body.obj")
            continue

        dst_obj = output_root / name / "body.obj"

        if args.resume and name in done:
            merged_rows[name] = {k: str(done[name].get(k, "")).strip() for k in FIELDNAMES}
            write_merged_csv(csv_path, merged_rows)
            skipped += 1
            print(f"[SKIP] {name} (--resume 本地 body.obj 有效且 CSV 含 OSS URL)")
            continue

        try:
            imported, faces_before, faces_after = adaptive_decimate_from_src(src_obj, name)

            for obj in imported:
                obj.select_set(True)
            export_obj(dst_obj)

            object_key = f"template/solid_full_body/decimate/{name}/body.obj"
            public_url = upload_file(dst_obj, object_key)
            row = {
                "template_name": name,
                "faces_before": str(faces_before),
                "faces_after": str(faces_after),
                "local_obj": str(dst_obj),
                "oss_key": object_key,
                "public_url": public_url,
            }
            merged_rows[name] = row
            write_merged_csv(csv_path, merged_rows)
            ok_new += 1
            print(f"[OK] {name} -> {public_url}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"[FAIL] {name}: {type(exc).__name__}: {exc}")
            cleanup_objects()

    write_merged_csv(csv_path, merged_rows)

    tail = f"CSV 共 {len(merged_rows)} 行" if only else f"CSV 共 {len(merged_rows)} 行（全量重写）"
    print(
        f"完成: -> {csv_path}（新处理 {ok_new}，--resume 跳过 {skipped}，失败 {failed}；{tail}）"
    )


if __name__ == "__main__":
    main()

