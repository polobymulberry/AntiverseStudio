"""列出 ``output/<产品线>/stage4_10/`` 下含 ``pipeline_render_prefs.yml`` 的主题 run 目录。

供批量脚本（Stage4～6 身体链、Stage8、Stage9/11 Blender 等）复用，与单主题 CLI 的 ``--fashion-tag``
（主题目录 basename 或 YAML 内 fashion_tag）对齐。
"""

from __future__ import annotations

from pathlib import Path

from common.pipeline_render_prefs import load_render_prefs_dict, pipeline_render_prefs_path
from common.utils import PIPELINE_TEMPLATE_USER_SUBDIR, pipeline_line_run_root, truncate_for_path


def stage4_10_root(output_root: Path, *, pipeline_line: str) -> Path:
    """``<output_root>/<pipeline_line>/stage4_10``。"""
    return pipeline_line_run_root(output_root, pipeline_line=pipeline_line) / PIPELINE_TEMPLATE_USER_SUBDIR


def list_theme_dirs_with_pipeline_prefs(stage4_10: Path) -> list[Path]:
    """``stage4_10`` 下直接子目录中，含 ``pipeline_render_prefs.yml`` 的目录，按名排序。"""
    if not stage4_10.is_dir():
        return []
    out: list[Path] = []
    for p in sorted(stage4_10.iterdir(), key=lambda x: x.name):
        if not p.is_dir():
            continue
        if (p / "pipeline_render_prefs.yml").is_file():
            out.append(p)
    return out


def filter_theme_dirs(stage4_10: Path, fashion_tag: str | None) -> list[Path]:
    """主题列表（已排序）。

    ``fashion_tag`` 非空时：先按主题目录 **basename** 精确匹配；若无命中，再读各目录
    ``pipeline_render_prefs.yml`` 的 ``fashion_tag``（全文或 ``truncate_for_path`` 后与 ``fashion_tag`` 参数比对），
    或参数经 ``truncate_for_path`` 后与目录名一致；仍无则返回空列表。
    """
    all_dirs = list_theme_dirs_with_pipeline_prefs(stage4_10)
    if not fashion_tag or not (ft := fashion_tag.strip()):
        return all_dirs
    by_name = [p for p in all_dirs if p.name == ft]
    if by_name:
        return by_name
    out: list[Path] = []
    for p in all_dirs:
        prefs = pipeline_render_prefs_path(p)
        if not prefs.is_file():
            continue
        data = load_render_prefs_dict(prefs)
        yft = (data.get("fashion_tag") or "").strip()
        if yft == ft or truncate_for_path(yft) == ft or truncate_for_path(ft) == p.name:
            out.append(p)
    return out
