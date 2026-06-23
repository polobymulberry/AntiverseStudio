"""Shared helper functions."""

from __future__ import annotations

import base64
import csv
import json
import re
from pathlib import Path
from typing import Iterable

from common.settings import SETTINGS


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def truncate_for_path(text: str, max_len: int = 48) -> str:
    """需求字符串 -> 磁盘子目录名：非法字符变下划线、空白变下划线、截断。

    会先去掉**相邻汉字之间**的空白，避免终端换行/误输入在词中间插入空格后
    得到「颜_色」等与阶段4 已生成目录「颜色」不一致的情况。
    """
    text = text.strip()
    text = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", text)
    cleaned = re.sub(r"[^\w\u4e00-\u9fff\- ]+", "_", text).strip()
    cleaned = re.sub(r"\s+", "_", cleaned)
    return cleaned[:max_len] if cleaned else "default"


# 阶段 4～12：同一 fashion-tag 下身体产物在
# ``OUTPUT_ROOT/<PIPELINE_LINE>/stage4_10/<fashion_tag截断>/<body_template>/``；卡通人偶在主题根 YAML 写 ``hair_object`` / ``hair_color``，
# 渲染用 solid 发型 mesh；与 body 平级的 ``<hair_object>/`` 目录可能仅为历史产物。
PIPELINE_TEMPLATE_USER_SUBDIR = "stage4_10"
# 手工归档 / 备选副本目录（与 stage4_10 同步迁移）
PIPELINE_FINISH_SUBDIR = "stage4_10_finish"


def pipeline_line_run_root(output_root: Path, *, pipeline_line: str | None = None) -> Path:
    """``output_root / <产品线>``；``pipeline_line`` 缺省时用 ``SETTINGS.pipeline_line``。"""
    root = Path(output_root)
    line = (pipeline_line if pipeline_line is not None else SETTINGS.pipeline_line).strip() or "手办服装IP"
    return root / line


def fashion_tag_run_dir(output_root: Path, fashion_tag: str, *, pipeline_line: str | None = None) -> Path:
    """同一主题（fashion-tag）根目录：``…/<PIPELINE_LINE>/stage4_10/<truncate(fashion_tag)>/``。

    ``pipeline_render_prefs.yml`` 与此目录同级（不按 body 模板分副本）。
    """
    tag = (fashion_tag or "").strip()
    if not tag:
        raise ValueError("fashion_tag 不能为空。")
    return (
        pipeline_line_run_root(output_root, pipeline_line=pipeline_line)
        / PIPELINE_TEMPLATE_USER_SUBDIR
        / truncate_for_path(tag)
    )


def fashion_tag_finish_run_dir(
    output_root: Path, fashion_tag: str, *, pipeline_line: str | None = None
) -> Path:
    """归档主题根：``…/<PIPELINE_LINE>/stage4_10_finish/<truncate(fashion_tag)>/``。"""
    tag = (fashion_tag or "").strip()
    if not tag:
        raise ValueError("fashion_tag 不能为空。")
    return (
        pipeline_line_run_root(output_root, pipeline_line=pipeline_line)
        / PIPELINE_FINISH_SUBDIR
        / truncate_for_path(tag)
    )


def fashion_tag_run_dir_candidates(
    output_root: Path, fashion_tag: str, *, pipeline_line: str | None = None
) -> tuple[Path, Path]:
    """返回 ``(stage4_10/…, stage4_10_finish/…)`` 两个候选主题根（不要求目录已存在）。"""
    return (
        fashion_tag_run_dir(output_root, fashion_tag, pipeline_line=pipeline_line),
        fashion_tag_finish_run_dir(output_root, fashion_tag, pipeline_line=pipeline_line),
    )


def existing_fashion_tag_run_dirs(
    output_root: Path, fashion_tag: str, *, pipeline_line: str | None = None
) -> list[Path]:
    """已存在的主题根目录列表（先 ``stage4_10``，再 ``stage4_10_finish``）。"""
    return [p for p in fashion_tag_run_dir_candidates(output_root, fashion_tag, pipeline_line=pipeline_line) if p.is_dir()]


def resolve_fashion_tag_run_dir(
    output_root: Path, fashion_tag: str, *, pipeline_line: str | None = None
) -> Path:
    """解析唯一主题根：在 ``stage4_10`` 与 ``stage4_10_finish`` 中查找。

    仅一侧存在则返回该侧；两侧皆存在时优先 ``stage4_10_finish``（已完成归档）；
    皆不存在则 ``FileNotFoundError``。
    """
    active, finish = fashion_tag_run_dir_candidates(output_root, fashion_tag, pipeline_line=pipeline_line)
    has_active = active.is_dir()
    has_finish = finish.is_dir()
    if has_finish:
        return finish.resolve()
    if has_active:
        return active.resolve()
    raise FileNotFoundError(
        f"fashion_tag={fashion_tag!r} 在下列路径均未找到主题目录:\n"
        f"  {active}\n"
        f"  {finish}"
    )


def body_template_run_dir_candidates(
    output_root: Path,
    fashion_tag: str,
    template_name: str,
    *,
    pipeline_line: str | None = None,
) -> tuple[Path, Path]:
    """返回 ``(stage4_10/…/template, stage4_10_finish/…/template)`` 候选 run 目录。"""
    tpl = template_name.strip()
    active_root, finish_root = fashion_tag_run_dir_candidates(
        output_root, fashion_tag, pipeline_line=pipeline_line
    )
    return active_root / tpl, finish_root / tpl


def resolve_body_template_run_dir(
    output_root: Path,
    fashion_tag: str,
    template_name: str,
    *,
    pipeline_line: str | None = None,
) -> Path:
    """解析单套模板 run 目录：在 ``stage4_10`` 与 ``stage4_10_finish`` 中查找（规则同 ``resolve_fashion_tag_run_dir``）。"""
    active, finish = body_template_run_dir_candidates(
        output_root, fashion_tag, template_name, pipeline_line=pipeline_line
    )
    has_active = active.is_dir()
    has_finish = finish.is_dir()
    if has_finish:
        return finish.resolve()
    if has_active:
        return active.resolve()
    raise FileNotFoundError(
        f"fashion_tag={fashion_tag!r} template={template_name!r} 在下列路径均未找到 run 目录:\n"
        f"  {active}\n"
        f"  {finish}"
    )


def body_template_run_dir(
    output_root: Path,
    fashion_tag: str,
    template_name: str,
    *,
    pipeline_line: str | None = None,
) -> Path:
    """单套服装模板在某主题下的 run 目录：``…/<PIPELINE_LINE>/stage4_10/<tag>/<template_name>/``。"""
    return fashion_tag_run_dir(output_root, fashion_tag, pipeline_line=pipeline_line) / template_name.strip()


def hair_style_run_dir_from_theme_dir(theme_run_dir: Path, hair_style_id: str) -> Path:
    """同一主题根下、按发型 id 分目录：``<fashion_tag_run_dir>/<truncate(hair_style_id)>/``。

    历史流水线曾将头发新纹理产物置于此路径；当前默认以主题 YAML 的 ``hair_object`` + solid mesh 为主，该目录可能为空或仅残留旧文件。
    """
    hid = (hair_style_id or "").strip()
    if not hid:
        raise ValueError("hair_style_id 不能为空。")
    return theme_run_dir.resolve() / truncate_for_path(hid)


def hair_style_run_dir(
    output_root: Path,
    fashion_tag: str,
    hair_style_id: str,
    *,
    pipeline_line: str | None = None,
) -> Path:
    """``…/<PIPELINE_LINE>/stage4_10/<truncate(fashion_tag)>/<truncate(hair_style_id)>/``。"""
    return hair_style_run_dir_from_theme_dir(
        fashion_tag_run_dir(output_root, fashion_tag, pipeline_line=pipeline_line),
        hair_style_id,
    )


def output_template_user_dir(
    output_root: Path,
    template_name: str,
    user_requirement: str,
    *,
    fashion_tag: str | None = None,
) -> Path:
    """兼容旧函数名：路径仅由 ``fashion_tag`` + ``template_name`` 决定（不再使用 user_requirement 拼路径）。

    若未提供 ``fashion_tag``，抛出清晰错误（请先迁移目录结构或传入 ``--fashion-tag``）。
    """
    _ = user_requirement  # 保留签名兼容，不参与路径
    tag = (fashion_tag or "").strip()
    if not tag:
        raise ValueError(
            "定位 run 目录须提供 fashion_tag（output/<产品线>/stage4_10/<标签>/<模板>/）。"
            "请使用 --fashion-tag，或在 pipeline_render_prefs.yml 中填写 fashion_tag。"
        )
    return body_template_run_dir(output_root, tag, template_name)


def write_csv(path: Path, rows: Iterable[dict], fieldnames: list[str]) -> None:
    ensure_dir(path.parent)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def read_csv(path: Path) -> list[dict]:
    with path.open("r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def file_to_data_url(image_path: Path) -> str:
    ext = image_path.suffix.lower().lstrip(".") or "png"
    data = base64.b64encode(image_path.read_bytes()).decode("utf-8")
    return f"data:image/{ext};base64,{data}"


def file_to_base64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("utf-8")


def parse_json_block(text: str) -> list[dict]:
    text = text.strip()
    if text.startswith("```"):
        match = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.DOTALL)
        if match:
            text = match.group(1).strip()
    data = json.loads(text)
    if not isinstance(data, list):
        raise ValueError("模型输出不是 JSON 数组。")
    return data
