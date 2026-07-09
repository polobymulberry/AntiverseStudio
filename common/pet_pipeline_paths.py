"""宠物定制流水线路径解析。

职责：
    为宠物模特库、订单浮雕渲染、后续头套模板等阶段提供统一路径 helper。
业务作用：
    与人偶 ``stage4_10`` 树解耦；宠物内置模特为全局资产，订单级产物在 ``OUTPUT_ROOT/宠物定制/`` 下。
系统定位：
    宠物 stage 脚本与 ``common/pipeline_lines.py`` 之间的路径中间层。
"""

from __future__ import annotations

from pathlib import Path

from common.pipeline_lines import (
    DEFAULT_PET_PIPELINE_LINE,
    PET_HEAD_TEMPLATE_SUBDIR,
    PET_MODEL_LIBRARY_SUBDIR,
    PET_RELIEF_SUBDIR,
    normalize_pipeline_line,
)
from common.settings import SETTINGS
from common.utils import ensure_dir, pipeline_line_run_root


def pet_model_library_run_dir(
    output_root: Path,
    run_subdir: str,
) -> Path:
    """宠物内置模特库单次 run 根：``output/pet_model_library/<run-subdir>/``。

    Args:
        output_root: 通常为 ``SETTINGS.output_root``。
        run_subdir: 人工命名批次，如 ``20260623_v1``。

    Returns:
        run 根目录 Path（不要求已存在）。
    """
    name = (run_subdir or "").strip()
    if not name:
        raise ValueError("run_subdir 不能为空。")
    return Path(output_root) / PET_MODEL_LIBRARY_SUBDIR / name


def pet_model_prompts_csv_path(output_root: Path, run_subdir: str) -> Path:
    """模特 prompt CSV 路径：``…/pet_model_prompts.csv``。"""
    return pet_model_library_run_dir(output_root, run_subdir) / "pet_model_prompts.csv"


def pet_model_images_dir(output_root: Path, run_subdir: str) -> Path:
    """模特成片目录：``…/images/``。"""
    return pet_model_library_run_dir(output_root, run_subdir) / "images"


def pet_relief_order_dir(
    output_root: Path,
    order_id: str,
    *,
    pipeline_line: str | None = None,
) -> Path:
    """单订单浮雕 run 根：``output/<宠物定制>/pet_relief/<order_id>/``。

    Args:
        output_root: 通常为 ``SETTINGS.output_root``。
        order_id: 宠物定制网站返回的订单号。
        pipeline_line: 缺省 ``DEFAULT_PET_PIPELINE_LINE``。

    Returns:
        订单 run 根目录 Path。
    """
    oid = (order_id or "").strip()
    if not oid:
        raise ValueError("order_id 不能为空。")
    line = normalize_pipeline_line(
        pipeline_line if pipeline_line is not None else DEFAULT_PET_PIPELINE_LINE,
        default=DEFAULT_PET_PIPELINE_LINE,
    )
    return pipeline_line_run_root(output_root, pipeline_line=line) / PET_RELIEF_SUBDIR / oid


def pet_relief_model_dir(
    output_root: Path,
    order_id: str,
    *,
    pipeline_line: str | None = None,
) -> Path:
    """订单拉取的 3D 模型目录：``…/model/``。"""
    return pet_relief_order_dir(output_root, order_id, pipeline_line=pipeline_line) / "model"


def pet_relief_video_dir(
    output_root: Path,
    order_id: str,
    *,
    pipeline_line: str | None = None,
) -> Path:
    """订单 360 渲染输出目录：``…/pet_relief_360/``。"""
    return pet_relief_order_dir(output_root, order_id, pipeline_line=pipeline_line) / "pet_relief_360"


def pet_head_template_run_dir(
    output_root: Path,
    run_subdir: str,
    *,
    pipeline_line: str | None = None,
) -> Path:
    """预留：宠物头套模板制作 run 根（尚未实现 stage 脚本）。"""
    name = (run_subdir or "").strip()
    if not name:
        raise ValueError("run_subdir 不能为空。")
    line = normalize_pipeline_line(
        pipeline_line if pipeline_line is not None else DEFAULT_PET_PIPELINE_LINE,
        default=DEFAULT_PET_PIPELINE_LINE,
    )
    return (
        pipeline_line_run_root(output_root, pipeline_line=line)
        / PET_HEAD_TEMPLATE_SUBDIR
        / name
    )


def ensure_pet_relief_order_dirs(
    output_root: Path,
    order_id: str,
    *,
    pipeline_line: str | None = None,
) -> tuple[Path, Path, Path]:
    """创建订单 run 下的 model / pet_relief_360 目录并返回三元组。"""
    order_root = ensure_dir(
        pet_relief_order_dir(output_root, order_id, pipeline_line=pipeline_line)
    )
    model_dir = ensure_dir(order_root / "model")
    video_dir = ensure_dir(order_root / "pet_relief_360")
    return order_root, model_dir, video_dir


def default_pet_pipeline_run_root() -> Path:
    """``OUTPUT_ROOT / 宠物定制``。"""
    return pipeline_line_run_root(SETTINGS.output_root, pipeline_line=DEFAULT_PET_PIPELINE_LINE)
