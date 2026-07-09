"""Pet Stage3a：按订单号从宠物定制网站拉取 3D 浮雕模型到本地。

输出：``output/宠物定制/pet_relief/<order_id>/model/``

API 未配置时使用 ``--local-model-dir`` 手工拷贝 GLB 等文件（开发/联调降级）。
拉模完成后可执行 Blender 360 渲染（见 ``blender_render_relief_360.py``）。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from common.pet_customization_client import PetCustomizationClient, copy_local_model_dir
from common.pet_pipeline_paths import ensure_pet_relief_order_dirs
from common.pipeline_lines import DEFAULT_PET_PIPELINE_LINE
from common.settings import SETTINGS


def main() -> None:
    parser = argparse.ArgumentParser(description="Pet Stage3a：按订单号拉取浮雕 3D 模型。")
    parser.add_argument("--order-id", required=True, help="宠物定制网站订单号。")
    parser.add_argument(
        "--pipeline-line",
        default=DEFAULT_PET_PIPELINE_LINE,
        help=f"产品线目录，默认 {DEFAULT_PET_PIPELINE_LINE!r}",
    )
    parser.add_argument(
        "--local-model-dir",
        default=None,
        help="API 未就绪时：从本地目录拷贝模型文件到订单 model/",
    )
    parser.add_argument("--overwrite", action="store_true", help="覆盖已下载模型。")
    parser.add_argument(
        "--render",
        action="store_true",
        help="拉模成功后立即调用 blender_render_relief_360.py（需已提供 .blend）",
    )
    parser.add_argument(
        "--blend-file",
        default=None,
        help="覆盖 PET_RELIEF_BLEND_FILE",
    )
    args = parser.parse_args()

    _, model_dir, _ = ensure_pet_relief_order_dirs(
        SETTINGS.output_root,
        args.order_id,
        pipeline_line=args.pipeline_line,
    )

    if args.local_model_dir:
        src = Path(args.local_model_dir).resolve()
        saved = copy_local_model_dir(src, model_dir, overwrite=args.overwrite)
        print(f"[OK] 已从本地拷贝 {len(saved)} 个文件 -> {model_dir}", flush=True)
    else:
        client = PetCustomizationClient()
        if not client.is_configured():
            print(
                "[ERROR] 未配置 PET_CUSTOMIZATION_API_BASE_URL，且未指定 --local-model-dir。",
                file=sys.stderr,
            )
            sys.exit(1)
        payload = client.fetch_order(args.order_id)
        print(f"[RUN] 订单 {payload.order_id} status={payload.status!r}", flush=True)
        saved = client.download_model_files(
            payload, model_dir, overwrite=args.overwrite
        )
        print(f"[OK] 已下载 {len(saved)} 个文件 -> {model_dir}", flush=True)
        for p in saved:
            print(f"  - {p.name}", flush=True)

    if args.render:
        blend = Path(args.blend_file or SETTINGS.pet_relief_blend_file)
        script = _REPO_ROOT / "pet_stage3_relief_render" / "blender_render_relief_360.py"
        cmd = [
            "blender",
            "-b",
            "--python-use-system-env",
            str(blend),
            "-P",
            str(script),
            "--",
            "--order-id",
            args.order_id,
            "--pipeline-line",
            args.pipeline_line,
        ]
        print(f"[RUN] 启动 Blender 360 渲染: {' '.join(cmd)}", flush=True)
        subprocess.run(cmd, check=True)


if __name__ == "__main__":
    main()
