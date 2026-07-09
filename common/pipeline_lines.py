"""流水线产品线常量与分类辅助。

职责：
    集中定义人偶定制、手办 IP、宠物定制等产品线目录名，避免各 stage 硬编码中文字符串。
业务作用：
    新脚本通过 ``DEFAULT_*_PIPELINE_LINE`` 与 ``is_*_pipeline_line`` 判断当前 run 所属产品线。
系统定位：
    ``common/settings.py`` 与批量脚本、宠物/人偶 stage 共用的产品线枚举层（字符串，非 Python Enum）。
"""

from __future__ import annotations

# 手办服装 IP 线（Stage4～12 默认）
DEFAULT_IP_PIPELINE_LINE = "手办服装IP"

# 卡通人偶定制线（Stage3b、batch_doll_*）
DEFAULT_DOLL_PIPELINE_LINE = "卡通人偶定制"

# 宠物定制线（宠物模特库、浮雕渲染、后续头套模板）
DEFAULT_PET_PIPELINE_LINE = "宠物定制"

# 人偶/手办共享的 Stage4～12 run 子目录
PIPELINE_TEMPLATE_USER_SUBDIR = "stage4_10"
PIPELINE_FINISH_SUBDIR = "stage4_10_finish"

# 宠物线专用 run 子目录（位于 ``OUTPUT_ROOT/<宠物定制>/`` 下）
PET_RELIEF_SUBDIR = "pet_relief"
PET_HEAD_TEMPLATE_SUBDIR = "pet_head_template"  # 预留：头套模板制作

# 宠物内置模特库（全局，不按 PIPELINE_LINE 分目录）
PET_MODEL_LIBRARY_SUBDIR = "pet_model_library"


def normalize_pipeline_line(line: str | None, *, default: str = DEFAULT_IP_PIPELINE_LINE) -> str:
    """规范化产品线字符串；空值回退 ``default``。"""
    text = (line or "").strip()
    return text or default


def is_doll_pipeline_line(line: str | None) -> bool:
    """是否为卡通人偶定制产品线。"""
    return normalize_pipeline_line(line, default="") == DEFAULT_DOLL_PIPELINE_LINE


def is_pet_pipeline_line(line: str | None) -> bool:
    """是否为宠物定制产品线。"""
    return normalize_pipeline_line(line, default="") == DEFAULT_PET_PIPELINE_LINE


def is_ip_pipeline_line(line: str | None) -> bool:
    """是否为手办服装 IP 产品线（默认线）。"""
    return normalize_pipeline_line(line, default=DEFAULT_IP_PIPELINE_LINE) == DEFAULT_IP_PIPELINE_LINE
