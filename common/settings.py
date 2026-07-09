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

    #: 位于 ``OUTPUT_ROOT`` 下的产品线目录名；默认「手办服装IP」。人偶线 ``卡通人偶定制``、宠物线 ``宠物定制`` 见 ``common.pipeline_lines``。
    pipeline_line: str = os.getenv("PIPELINE_LINE", "手办服装IP")

    # 宠物定制网站 API（拉取浮雕模型；endpoint 契约随外部仓库演进）
    pet_customization_api_base_url: str = os.getenv("PET_CUSTOMIZATION_API_BASE_URL", "")
    pet_customization_api_key: str = os.getenv("PET_CUSTOMIZATION_API_KEY", "")
    pet_customization_order_path: str = os.getenv(
        "PET_CUSTOMIZATION_ORDER_PATH", "api/v1/orders/{order_id}/model"
    )
    pet_customization_api_timeout: int = int(os.getenv("PET_CUSTOMIZATION_API_TIMEOUT", "60"))
    pet_customization_download_timeout: int = int(
        os.getenv("PET_CUSTOMIZATION_DOWNLOAD_TIMEOUT", "300")
    )
    pet_customization_max_retries: int = int(os.getenv("PET_CUSTOMIZATION_MAX_RETRIES", "3"))

    # 宠物浮雕 Blender 360 渲染工程（尚未提供时可留空，脚本会报错并提示）
    pet_relief_blend_file: Path = Path(
        os.getenv(
            "PET_RELIEF_BLEND_FILE",
            str(_REPO_ROOT / "resource" / "blender" / "pet_relief_360.blend"),
        )
    )
    # 内置宠物高清模特图归档根（Stage2 出图后可手工挑选复制到此）
    pet_model_reference_root: Path = Path(
        os.getenv(
            "PET_MODEL_REFERENCE_ROOT",
            str(_REPO_ROOT / "resource" / "pet_model_reference"),
        )
    )

    # Qwen / DashScope (OpenAI-compatible endpoint)
    dashscope_api_key: str = os.getenv("DASHSCOPE_API_KEY", "")
    dashscope_region: str = os.getenv("DASHSCOPE_REGION", "beijing")
    dashscope_model: str = os.getenv("DASHSCOPE_MODEL", "qwen3.6-plus")
    dashscope_base_url: str = os.getenv(
        "DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
    )
    enable_thinking: bool = os.getenv("QWEN_ENABLE_THINKING", "true").lower() == "true"
    thinking_budget: int = int(os.getenv("QWEN_THINKING_BUDGET", "4000"))

    # Qwen-Image-2512 本地 diffusers 推理（Pet Stage2 等；参考 drdoll ``tool/qwen_image_local``）
    qwen_image_model_path: Path = Path(
        os.getenv(
            "QWEN_IMAGE_MODEL_PATH",
            "/mnt/jfs_tikv/panjianxiong/gpustack_data/cache/model_scope/Qwen/Qwen-Image-2512",
        )
    )
    qwen_image_width: int = int(os.getenv("QWEN_IMAGE_WIDTH", "1024"))
    qwen_image_height: int = int(os.getenv("QWEN_IMAGE_HEIGHT", "1024"))
    qwen_image_true_cfg_scale: float = float(os.getenv("QWEN_IMAGE_TRUE_CFG_SCALE", "4.0"))
    qwen_image_num_inference_steps: int = int(os.getenv("QWEN_IMAGE_NUM_INFERENCE_STEPS", "28"))
    qwen_image_base_seed: int = int(os.getenv("QWEN_IMAGE_BASE_SEED", "1472666871"))
    qwen_image_negative_prompt: str = os.getenv(
        "QWEN_IMAGE_NEGATIVE_PROMPT",
        "模糊，低质量，变形，水印，文字，丑陋，多余肢体，畸变，"
        "面部暗斑，雀斑，闪电纹，半脸分界，异瞳，全身照，"
        "客厅，卧室，户外，家居家具，绿植，街景，抠图感，过度曝光",
    )
    num_gpus_to_use: int = int(os.getenv("NUM_GPUS_TO_USE", "8"))
    gpus_per_instance: int = int(os.getenv("GPUS_PER_INSTANCE", "2"))

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
