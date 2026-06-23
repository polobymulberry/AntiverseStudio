"""``real_head_120k`` 头部网格路径解析（供 Stage11 等在 ``head_object`` 为数字 template_id 时使用）。"""

from __future__ import annotations

import os
import re
from pathlib import Path

_DIGITS = re.compile(r"^[0-9]+$")

# 默认与 drdoll 数据布局一致；可通过环境变量覆盖。
DEFAULT_REAL_HEAD_120K_ROOT = Path(
    os.getenv(
        "REAL_HEAD_120K_ROOT",
        "/mnt/jfs_tikv/drdoll/runtime_data/image2human/templates_3hb/real_head_120k",
    )
)

MAX_TEMPLATE_ID = 119_999

# 默认相对路径（相对 REAL_HEAD_120K_ROOT）；{id} 为 6 位目录名。可用 REAL_HEAD_MESH_REL_PATTERN 覆盖。
_DEFAULT_PRIMARY_REL = "solid/{id}/akintisan3d/template_aligned/mcr_head.glb"


def _relative_patterns_ordered() -> list[str]:
    return [os.getenv("REAL_HEAD_MESH_REL_PATTERN", _DEFAULT_PRIMARY_REL)]


def normalize_real_head_template_id(head_object: str) -> str | None:
    """若 ``head_object`` 为 0～119999 的纯数字串，返回 6 位补零目录名，否则 ``None``。"""
    s = (head_object or "").strip()
    if not s or not _DIGITS.fullmatch(s):
        return None
    n = int(s)
    if n < 0 or n > MAX_TEMPLATE_ID:
        return None
    return f"{n:06d}"


def candidate_paths_for_template_id(base_root: Path, template_id_6: str) -> list[Path]:
    """按优先级列出可能存在的网格文件绝对路径（用于日志 / 报错）。"""
    root = Path(base_root)
    return [(root / rel.format(id=template_id_6)).resolve() for rel in _relative_patterns_ordered()]


def resolve_existing_real_head_mesh(base_root: Path, template_id_6: str) -> Path | None:
    """在候选路径中返回第一个实际存在的文件；均无则 ``None``。"""
    for p in candidate_paths_for_template_id(base_root, template_id_6):
        if p.is_file():
            return p
    return None


def real_head_mesh_path_if_template_id(base_root: Path, head_object: str) -> Path | None:
    """若 ``head_object`` 为 template_id 且解析到已有文件则返回路径，否则 ``None``。

    注意：当 ``head_object`` 为合法 template_id 但磁盘上无任一候选文件时，本函数仍返回 ``None``；
    调用方须用 ``normalize_real_head_template_id`` 区分「非 template_id」与「缺失文件」。
    """
    tid = normalize_real_head_template_id(head_object)
    if tid is None:
        return None
    return resolve_existing_real_head_mesh(base_root, tid)
