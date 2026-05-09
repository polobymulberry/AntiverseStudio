"""Shared helper functions."""

from __future__ import annotations

import base64
import csv
import json
import re
from pathlib import Path
from typing import Iterable


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


# 阶段 4～10：与「模板 + 用户需求」相关的产物统一在 output/stage4_10/<template>/<需求截断>/ 下
PIPELINE_TEMPLATE_USER_SUBDIR = "stage4_10"


def output_template_user_dir(
    output_root: Path,
    template_name: str,
    user_requirement: str,
    *,
    fashion_tag: str | None = None,
) -> Path:
    """同一 run 目录：output_root/stage4_10/<template>/<路径段>/。

    若 ``fashion_tag`` 非空，路径段为 ``truncate_for_path(fashion_tag)``（与阶段4～8 的
    ``--fashion-tag`` 一致）；否则为 ``truncate_for_path(user_requirement)``（旧版行为）。
    ``fashion_tag`` 仅用于磁盘路径与 CSV 索引列，不参与任何文生图或 LLM 的 prompt 拼接。
    """
    tag = (fashion_tag or "").strip()
    segment = truncate_for_path(tag) if tag else truncate_for_path(user_requirement)
    return (
        output_root
        / PIPELINE_TEMPLATE_USER_SUBDIR
        / template_name.strip()
        / segment
    )


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

