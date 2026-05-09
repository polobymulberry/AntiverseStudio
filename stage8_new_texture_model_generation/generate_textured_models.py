"""Stage 8: 贴图 3D 模型产物目录；本脚本为「API 补跑」分支。

流水线**默认**在混元 3D **网页**用积分完成贴图，将 ``<中文风格>.glb`` 放入
``…/stage8_new_texture_model_generation/``。**仅当网页积分不足**或需脚本批量提交时，
再运行本模块：对 stage7 筛图 PNG 调用 Tencent 云 API，写出 GLB（及若返回则附带 ``_result`` 图）。
无预览图不影响后续阶段；Blender 侧只依赖 ``*.glb``。

**与本脚本无关**：场景里 Studio 背景墙材质 ``Studio_Fabric_1.001`` 的 **Tint 颜色** 在
**阶段9/11** 的 ``stage11_render_videos/blender_render_videos.py`` 中设置；可选预设见
``common/studio_render_constants.py`` 的 ``STUDIO_TINT_HEX_PRESETS``，请传
``--studio-tint-hex`` 固定同一次批量颜色；旧行为「每套随机一色」为 ``--random-studio-tint``。
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import requests

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from common.settings import SETTINGS
from common.tencent_hunyuan_client import (
    describe_texture_job,
    extract_texture_glb_and_image_urls,
    submit_texture_job,
    texture_job_error,
    texture_job_json_body,
    texture_job_status,
)
from common.utils import (
    ensure_dir,
    file_to_base64,
    output_template_user_dir,
    read_csv,
)


def wait_done(
    job_id: str,
    interval_sec: int = 15,
    timeout_sec: int = 1800,
    *,
    progress_label: str = "",
    done_asset_poll_sec: int = 5,
    done_asset_timeout_sec: int = 180,
) -> dict:
    """轮询 DescribeTextureTo3DJob：直到 Status=DONE 且解析到 GLB URL（DONE 后文件列表可能晚于状态）。"""
    start = time.time()
    prefix = f"{progress_label} " if progress_label else ""
    done_without_glb_since: float | None = None
    while True:
        raw = describe_texture_job(job_id)
        status = texture_job_status(raw)
        err_code, err_msg = texture_job_error(raw)
        elapsed = int(time.time() - start)

        if status in {"FAIL", "FAILED", "ERROR"}:
            raise RuntimeError(f"任务失败 job={job_id} status={status} {err_code} {err_msg} {raw}")

        if status == "DONE":
            if err_code:
                raise RuntimeError(
                    f"任务失败 job={job_id} ErrorCode={err_code} ErrorMessage={err_msg}"
                )
            glb_url, _ = extract_texture_glb_and_image_urls(raw)
            if glb_url:
                print(
                    f"{prefix}[Stage8] 任务完成 job={job_id}，轮询耗时约 {elapsed}s（已解析 GLB）",
                    flush=True,
                )
                return raw
            if done_without_glb_since is None:
                done_without_glb_since = time.time()
                print(
                    f"{prefix}[Stage8] Status=DONE 尚未在 ResultFile3Ds 中看到 GLB，"
                    f"每 {done_asset_poll_sec}s 继续查询（最长 {done_asset_timeout_sec}s）…",
                    flush=True,
                )
            elif time.time() - done_without_glb_since > done_asset_timeout_sec:
                body = texture_job_json_body(raw)
                r3 = body.get("ResultFile3Ds")
                raise RuntimeError(
                    f"DONE 后超过 {done_asset_timeout_sec}s 仍无 GLB URL: job={job_id} "
                    f"ResultFile3Ds={r3!r}"
                )
            time.sleep(done_asset_poll_sec)
            continue

        done_without_glb_since = None

        if time.time() - start > timeout_sec:
            raise TimeoutError(f"任务超时: {job_id}")
        print(
            f"{prefix}[Stage8] 任务轮询 job={job_id} status={status or '?'} 已等待 {elapsed}s "
            f"（每 {interval_sec}s 查询一次）",
            flush=True,
        )
        time.sleep(interval_sec)


def _image_suffix_from_url(url: str) -> str:
    u = url.split("?", 1)[0].lower()
    if u.endswith(".jpg") or u.endswith(".jpeg"):
        return ".jpg"
    if u.endswith(".webp"):
        return ".webp"
    return ".png"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "【备选】网页积分不足时：用腾讯云混元 3D 贴图 API 批处理 stage7 筛图，"
            "写出 GLB 到 output/stage4_10/<模板>/<需求截断>/stage8_new_texture_model_generation/。"
            "默认流程请在网页完成贴图后手放 GLB，无需运行本脚本；后续渲染只扫描 *.glb。"
        ),
    )
    parser.add_argument(
        "--template",
        required=True,
        metavar="NAME",
        help="与阶段4～6 所用模板名一致",
    )
    parser.add_argument(
        "--user-requirement",
        default=None,
        help="与阶段4～6 所用需求全文一致；与 --fashion-tag 二选一或同传（同传时目录以 tag 为准）。",
    )
    parser.add_argument(
        "--fashion-tag",
        default=None,
        metavar="TAG",
        help="与阶段4 一致；仅定位 run 目录，不参与贴图侧描述文本。",
    )
    parser.add_argument(
        "--selected-dir",
        default=None,
        help=(
            "第七步人工筛选 PNG 目录（递归 *.png）；省略则为 "
            "output/stage4_10/<template>/<需求截断>/stage7_new_texture_generation_selected/。"
            "目录内图片均按本 run（由 --template 与 --user-requirement 或 --fashion-tag 指定）处理。"
        ),
    )
    parser.add_argument(
        "--stage3-csv",
        default=str(SETTINGS.output_root / "stage3_body_template_decimate.csv"),
    )
    args = parser.parse_args()

    req = (args.user_requirement or "").strip()
    ft = (args.fashion_tag or "").strip()
    if not req and not ft:
        parser.error("须指定 --user-requirement 或 --fashion-tag（与阶段4～6 定位该 run 一致）。")

    print(
        "[Stage8] 当前为「API 批处理」模式（云 API 计费）。"
        "默认流程为网页积分贴图后手放 .glb；仅当网页积分不够或需补跑时再使用本命令。",
        flush=True,
    )

    model_url_map = {row["template_name"]: row["public_url"] for row in read_csv(Path(args.stage3_csv))}
    template_name = args.template.strip()
    run_dir = output_template_user_dir(
        SETTINGS.output_root,
        template_name,
        req,
        fashion_tag=ft or None,
    )
    default_selected = run_dir / "stage7_new_texture_generation_selected"
    selected_dir = (
        Path(args.selected_dir).resolve()
        if args.selected_dir
        else default_selected.resolve()
    )
    if not selected_dir.is_dir():
        print(f"[ERROR] 筛图目录不存在: {selected_dir}", file=sys.stderr)
        sys.exit(1)

    png_paths = sorted(p.resolve() for p in selected_dir.rglob("*.png"))
    total = len(png_paths)
    print(f"[RUN] run_dir={run_dir}", flush=True)
    print(f"[RUN] selected_dir={selected_dir}", flush=True)
    print(f"[RUN] 共 {total} 张 PNG 待提交混元贴图", flush=True)

    model_url = model_url_map.get(template_name)
    if not model_url:
        print(f"[ERROR] stage3 CSV 中无模板「{template_name}」的 public_url", file=sys.stderr)
        sys.exit(1)

    for idx, image_path in enumerate(png_paths, start=1):
        label_zh = image_path.stem.rsplit("_", 1)[0]
        print(
            f"[Stage8] ({idx}/{total}) {image_path.name}（label={label_zh}）提交混元贴图 …",
            flush=True,
        )
        submit_resp = submit_texture_job(model_url, file_to_base64(image_path))
        job_id = submit_resp.get("JobId") or submit_resp.get("Result", {}).get("JobId")
        if not job_id:
            print(f"[SKIP] {image_path.name} 无法获取 JobId", flush=True)
            continue
        done_resp = wait_done(job_id, progress_label=f"({idx}/{total})")
        glb_url, image_url = extract_texture_glb_and_image_urls(done_resp)
        if not glb_url:
            print(f"[SKIP] {job_id} 未返回 glb URL（ResultFile3Ds 解析为空）", flush=True)
            continue

        out_dir = ensure_dir(run_dir / "stage8_new_texture_model_generation")
        dst = out_dir / f"{label_zh}.glb"
        print(f"[Stage8] ({idx}/{total}) 下载 GLB …", flush=True)
        file_resp = requests.get(glb_url, timeout=300)
        file_resp.raise_for_status()
        dst.write_bytes(file_resp.content)
        if image_url:
            img_dst = out_dir / f"{label_zh}_result{_image_suffix_from_url(image_url)}"
            print(f"[Stage8] ({idx}/{total}) 下载贴图预览 …", flush=True)
            img_resp = requests.get(image_url, timeout=300)
            img_resp.raise_for_status()
            img_dst.write_bytes(img_resp.content)
            print(
                f"[OK] ({idx}/{total}) {template_name}/{label_zh} -> {dst} + {img_dst.name}",
                flush=True,
            )
        else:
            print(f"[OK] ({idx}/{total}) {template_name}/{label_zh} -> {dst}（无 IMAGE/TEXTURE_IMAGE）", flush=True)

    print(f"[DONE] 已处理 {total} 张筛图。", flush=True)


if __name__ == "__main__":
    main()

