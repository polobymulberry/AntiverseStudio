"""卡通人偶线：身体/头发显式配对（CSV）与路径解析。"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from common.pipeline_render_prefs import _str_field
from common.utils import hair_style_run_dir_from_theme_dir

PIPELINE_BODY_HAIR_MERGE_CSV = "pipeline_body_hair_merge.csv"

MERGE_FIELDNAMES: list[str] = [
    "template_name",
    "fashion_tag",
    "real_head_id",
    "hair_style_id",
    "body_textured_glb",
    "hair_textured_glb",
]


def merge_csv_path(run_dir: Path) -> Path:
    """单套模板 run 目录下的合并表路径。"""
    return run_dir.resolve() / PIPELINE_BODY_HAIR_MERGE_CSV


def read_merge_csv(run_dir: Path) -> list[dict[str, str]]:
    p = merge_csv_path(run_dir)
    if not p.is_file():
        return []
    with p.open("r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_merge_csv(run_dir: Path, rows: list[dict[str, str]]) -> Path:
    """写入 UTF-8、稳定列顺序。"""
    p = merge_csv_path(run_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=MERGE_FIELDNAMES)
        w.writeheader()
        for row in rows:
            w.writerow({k: (row.get(k) or "").strip() for k in MERGE_FIELDNAMES})
    return p


def resolve_path_under_run(run_dir: Path, rel: str) -> Path:
    """相对 run 目录的路径解析（禁止 … 逃逸）。"""
    r = (rel or "").strip().replace("\\", "/")
    if not r or ".." in r.split("/"):
        return Path()
    return (run_dir / r).resolve()


def resolve_textured_hair_glb_path(
    body_template_run_dir: Path,
    stem: str,
    prefs_data: dict[str, Any],
) -> Path | None:
    """解析贴图头发 GLB：YAML ``hair_textured_glb``（可用 ``{stem}``）；若未配置或文件不存在则返回 None（渲染使用 solid 发型 + ``hair_color``）。"""
    rel = _str_field(prefs_data.get("hair_textured_glb"))
    hair_id = _str_field(prefs_data.get("hair_object"))
    if not hair_id:
        return None

    hair_run = hair_style_run_dir_from_theme_dir(body_template_run_dir.parent, hair_id)
    if rel:
        path_str = rel.replace("{stem}", stem)
        p = resolve_path_under_run(hair_run, path_str)
        if p.is_file():
            return p
        p2 = resolve_path_under_run(body_template_run_dir, path_str)
        if p2.is_file():
            return p2
    return None


def resolve_textured_body_glb_path(
    run_dir: Path,
    stem: str,
    prefs_data: dict[str, Any],
) -> Path | None:
    """可选覆盖身体 GLB（默认使用扫描到的 stage8 下 ``{stem}.glb``）。"""
    rel = _str_field(prefs_data.get("body_textured_glb"))
    if not rel:
        default = run_dir / "stage8_new_texture_model_generation" / f"{stem}.glb"
        return default if default.is_file() else None
    path_str = rel.replace("{stem}", stem)
    p = resolve_path_under_run(run_dir, path_str)
    return p if p.is_file() else None
