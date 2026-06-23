"""卡通人偶线：根据 ``head_object``（数字 real_head_id）解析真人参考照片路径，供 Stage9 侧写比对。"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from common.pipeline_render_prefs import load_render_prefs_dict, pipeline_render_prefs_path
from common.real_head_assets import normalize_real_head_template_id
from common.utils import fashion_tag_run_dir, read_csv


def load_head_object_from_theme_prefs(output_root: Path, fashion_tag: str) -> str:
    """读取主题根 ``pipeline_render_prefs.yml`` 的 ``head_object`` 字符串。"""
    root = fashion_tag_run_dir(output_root, fashion_tag)
    p = pipeline_render_prefs_path(root)
    if not p.is_file():
        return ""
    data: dict[str, Any] = load_render_prefs_dict(p)
    return str(data.get("head_object") or "").strip()


def resolve_photo_path_for_numeric_head(
    *,
    output_root: Path,
    repo_root: Path,
    template_id_6: str,
) -> Path | None:
    """在 Stage3b 全仓库 CSV 的 ``photo_path`` 中查找 ``real_head_id`` 匹配项；否则回退 ``resource/real_head_120k_selected``。"""
    s3b_root = Path(output_root).resolve() / "stage3b_body_and_hair_template_theme_fit"
    if s3b_root.is_dir():
        for csv_path in sorted(s3b_root.rglob("stage3b_body_and_hair_template_theme_fit.csv")):
            for row in read_csv(csv_path):
                raw = (row.get("real_head_id") or "").strip()
                tid_row = normalize_real_head_template_id(raw)
                if tid_row != template_id_6:
                    continue
                rel = (row.get("photo_path") or "").strip()
                if not rel:
                    continue
                p = Path(rel).expanduser()
                if p.is_file():
                    return p.resolve()
    sel = Path(repo_root).resolve() / "resource" / "real_head_120k_selected"
    if sel.is_dir():
        for pat in ("*.png", "*.jpg", "*.jpeg"):
            for p in sorted(sel.glob(pat)):
                if not p.is_file():
                    continue
                if template_id_6 in p.stem or template_id_6 in p.name:
                    return p.resolve()
    return None


def unique_stage9_output_dirs(
    tasks: list[tuple[Path, Path]],
    *,
    covers_subdir: str,
) -> list[Path]:
    """从 ``(glb, out_dir)`` 任务列表中去重 ``stage9_render_covers`` 目录。"""
    seen: set[str] = set()
    out: list[Path] = []
    for _, od in tasks:
        if od.name != covers_subdir:
            continue
        key = str(od.resolve())
        if key in seen:
            continue
        seen.add(key)
        out.append(od)
    return sorted(out, key=str)


def copy_real_head_reference_into_stage9_dirs(
    *,
    output_root: Path,
    repo_root: Path,
    head_object: str,
    stage9_dirs: list[Path],
) -> tuple[Path | None, str]:
    """将真人照片拷入各 ``stage9_render_covers`` 目录，文件名为 ``real_head_reference.<原后缀>``。

    返回 ``(源路径或 None, 说明字符串)``。
    """
    ho = (head_object or "").strip()
    if not ho:
        return None, "YAML head_object 为空，跳过真人参考图"
    tid = normalize_real_head_template_id(ho)
    if tid is None:
        return None, "head_object 非数字 real_head_id，跳过真人参考图（内置头无 CSV 照片路径）"
    if not stage9_dirs:
        return None, "无 stage9 输出目录"
    src = resolve_photo_path_for_numeric_head(
        output_root=output_root,
        repo_root=repo_root,
        template_id_6=tid,
    )
    if src is None or not src.is_file():
        return None, f"未找到 real_head_id={tid} 的 photo_path（Stage3b CSV 或 resource/real_head_120k_selected）"
    suf = src.suffix.lower() if src.suffix else ".png"
    name = f"real_head_reference{suf}"
    n = 0
    for od in stage9_dirs:
        od.mkdir(parents=True, exist_ok=True)
        dst = od / name
        shutil.copy2(src, dst)
        n += 1
    return src, f"已写入 {n} 个目录: {name}（源 {src.name}）"
