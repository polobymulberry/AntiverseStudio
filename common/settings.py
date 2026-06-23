"""Global project settings."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent

try:
    from dotenv import load_dotenv
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "缺少 python-dotenv。请在 Blender 自带的 Python 中安装（见 README「在 Blender 自带 Python 中安装 python-dotenv」）；"
        "conda 环境请执行：pip install -r requirements.txt"
    ) from exc

load_dotenv(dotenv_path=_REPO_ROOT / ".env")


@dataclass(frozen=True)
class PipelineSettings:
    """Centralized global settings for all stages."""

    # 3D cartoon clothing templates root directory (required by README).
    template_root: Path = Path(
        os.getenv(
            "BODY_TEMPLATE_ROOT",
            "/mnt/jfs_tikv/panjianxiong/drdoll/data/solid_full_body",
        )
    )
    # real_head_120k：head_object 为纯数字 template_id 时从该根目录下解析 head.obj
    real_head_120k_root: Path = Path(
        os.getenv(
            "REAL_HEAD_120K_ROOT",
            "/mnt/jfs_tikv/drdoll/runtime_data/image2human/templates_3hb/real_head_120k",
        )
    )
    output_root: Path = Path(os.getenv("OUTPUT_ROOT", "output"))

    #: 位于 ``OUTPUT_ROOT`` 下的产品线目录名；默认「手办服装IP」。新作「卡通人偶定制」流水线请设置环境变量 ``PIPELINE_LINE``。
    pipeline_line: str = os.getenv("PIPELINE_LINE", "手办服装IP")

    # Qwen / DashScope (OpenAI-compatible endpoint)
    dashscope_api_key: str = os.getenv("DASHSCOPE_API_KEY", "")
    dashscope_region: str = os.getenv("DASHSCOPE_REGION", "beijing")
    dashscope_model: str = os.getenv("DASHSCOPE_MODEL", "qwen3.6-plus")
    dashscope_base_url: str = os.getenv(
        "DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
    )
    enable_thinking: bool = os.getenv("QWEN_ENABLE_THINKING", "true").lower() == "true"
    thinking_budget: int = int(os.getenv("QWEN_THINKING_BUDGET", "4000"))

    # Doubao Seedream
    seedream_api_key: str = os.getenv("SEEDREAM_API_KEY", "")
    seedream_base_url: str = os.getenv("SEEDREAM_BASE_URL", "https://ark.cn-beijing.volces.com")
    seedream_model: str = os.getenv("SEEDREAM_MODEL", "doubao-seedream-5-0-260128")
    seedream_endpoint: str = os.getenv(
        "SEEDREAM_GENERATION_ENDPOINT", "/api/v3/images/generations"
    )

    # Aliyun OSS
    object_storage_provider: str = os.getenv("OBJECT_STORAGE_PROVIDER", "aliyun")
    oss_access_key_id: str = os.getenv("OSS_ACCESS_KEY_ID", "")
    oss_secret_access_key: str = os.getenv("OSS_SECRET_ACCESS_KEY", "")
    oss_endpoint_url: str = os.getenv("OSS_ENDPOINT_URL", "https://oss-cn-beijing.aliyuncs.com")
    oss_public_url: str = os.getenv(
        "OSS_PUBLIC_URL", "https://drdoll-public.oss-cn-beijing.aliyuncs.com"
    )
    oss_bucket_name: str = os.getenv("OSS_BUCKET_NAME", "drdoll-public")

    # Tencent Hunyuan 3D
    tencent_region: str = os.getenv("TENCENT_REGION", "ap-guangzhou")
    tencent_hunyuan_model: str = os.getenv("TENCENT_TEXTURE_MODEL", "3.1")

    def pipeline_run_root(self) -> Path:
        """阶段 4～12 流水线产物根：``OUTPUT_ROOT / PIPELINE_LINE``（其下有 ``stage4_10``、``stage4_10_finish``）。"""
        line = (self.pipeline_line or "").strip() or "手办服装IP"
        return Path(self.output_root) / line


SETTINGS = PipelineSettings()
