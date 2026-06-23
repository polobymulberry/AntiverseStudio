"""批量补跑卡通人偶「身体 Stage4～6」新纹理链路。

- **产品线须 CLI 显式指定**：必须通过 ``--pipeline`` 传入 ``output/<产品线>/`` 子目录名；**不**从环境变量或 ``SETTINGS`` 隐式推断，避免漏设 ``PIPELINE_LINE`` 导致路径与已齐判定错位。
- 仅扫描 ``output/<产品线>/stage4_10/`` 下**直接含** ``pipeline_render_prefs.yml`` 的主题目录（不会把 ``body_*`` / 发型子目录误当成主题）。
- **未加 ``--overwrite``**：先按主题判断是否**整线已齐**——每个身体模板须同时满足：存在 ``stage4*_…prompt.csv``、存在 ``stage5*_…prompt.csv``（仅以**文件存在**为准）；Stage6 须按 stage5 CSV 中每条 prompt 在 ``stage6*_…`` 目录下存在 ``--num-images`` 张**可读栅格图**（PNG 或 JPEG：魔数 + 最小字节数 + JPEG 须含结束标记；若已安装 Pillow 则再 ``verify()``）。**任一模板不齐** → **清空该主题下全部** stage4/5/6 后自 Stage4 **整主题**重跑。
- **整主题已齐**且未加 ``--overwrite`` → **跳过**。
- **``--overwrite``**：即使已齐也**强制**删光该主题全部 stage4/5/6 后完整重跑。
- Stage6 调用带 ``--resume``，便于断点续跑单条内多图。
- **并发（默认 ``--workers=4``）**：多主题并行；**每个主题**在单个 worker 内**顺序**跑完 Stage4→5→6，且子进程全部成功后**再**用与「已齐」相同的规则校验磁盘（各模板 CSV + Stage6 预览张数）；**仅当该校验通过**（或本主题被判定为跳过已齐）后，该 worker 才领取下一主题。

用法（仓库根、已 ``conda activate antiversestudio``）::

    python scripts/batch_doll_texture_stages.py --pipeline 卡通人偶定制

可选：``--workers``、``--num-images``、``--stage4-disable-search``、
``--fashion-tag <TAG>``（与 ``--only-tag`` 等价）、
``--dry-run``、``--overwrite``、``--stage4-10-root``。
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from common.doll_stage4_10_theme_dirs import filter_theme_dirs
from common.pipeline_render_prefs import (
    load_render_prefs_dict,
    parse_body_templates_from_prefs,
    pipeline_render_prefs_path,
)
from common.settings import SETTINGS
from common.utils import (
    PIPELINE_TEMPLATE_USER_SUBDIR,
    body_template_run_dir,
    pipeline_line_run_root,
    read_csv,
    truncate_for_path,
)

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_MIN_RASTER_BYTES = 512


def _try_pil_verify(path: Path) -> bool:
    """若已安装 Pillow，则解码校验；否则视为通过（已由魔数等粗检）。"""
    try:
        from PIL import Image  # type: ignore[import-not-found]
    except ImportError:
        return True
    try:
        with Image.open(path) as im:
            im.verify()
    except Exception:
        return False
    return True


def _is_readable_raster_image(path: Path) -> bool:
    """Stage6 产物：内容须为 PNG 或 JPEG（不以后缀为准）；可选 Pillow 完整校验。"""
    if not path.is_file():
        return False
    try:
        size = path.stat().st_size
    except OSError:
        return False
    if size < _MIN_RASTER_BYTES:
        return False
    try:
        head = path.read_bytes()[:24]
    except OSError:
        return False

    if head[:8] == _PNG_MAGIC:
        if size < 24 or head[12:16] != b"IHDR":
            return False
        return _try_pil_verify(path)

    if len(head) >= 3 and head[0:3] == b"\xff\xd8\xff":
        try:
            with path.open("rb") as f:
                f.seek(max(0, size - 2))
                end = f.read(2)
        except OSError:
            return False
        if end != b"\xff\xd9":
            return False
        return _try_pil_verify(path)

    return False


def _run_py(script_rel: str, argv: list[str], *, dry_run: bool) -> int:
    cmd = [sys.executable, str(_REPO_ROOT / script_rel), *argv]
    print(f"[CMD] {' '.join(cmd)}", flush=True)
    if dry_run:
        return 0
    env = os.environ.copy()
    return subprocess.call(cmd, cwd=str(_REPO_ROOT), env=env)


def _wipe_body_theme_templates(
    *,
    out_root: Path,
    fashion_tag: str,
    pairs: list[tuple[str, int]],
    dry_run: bool,
    detail: str,
    pipeline_line: str,
) -> None:
    print(f"[WIPE] {detail}", flush=True)
    for tmpl, _ in pairs:
        rd = body_template_run_dir(out_root, fashion_tag, tmpl, pipeline_line=pipeline_line)
        for sub in ("stage4_fashion_prompt.csv", "stage5_new_texture_prompt.csv"):
            p = rd / sub
            if p.is_file():
                print(f"[CLEAN] unlink {p}", flush=True)
                if not dry_run:
                    p.unlink()
        s6 = rd / "stage6_new_texture_generation"
        if s6.is_dir():
            print(f"[CLEAN] rmtree {s6}", flush=True)
            if not dry_run:
                shutil.rmtree(s6, ignore_errors=True)


def _body_theme_pipeline_done(
    *,
    fashion_tag: str,
    pairs: list[tuple[str, int]],
    num_images: int,
    pipeline_line: str,
) -> bool:
    out_root = Path(SETTINGS.output_root).resolve()
    for tmpl, _ in pairs:
        run_dir = body_template_run_dir(out_root, fashion_tag, tmpl, pipeline_line=pipeline_line)
        p4 = run_dir / "stage4_fashion_prompt.csv"
        p5 = run_dir / "stage5_new_texture_prompt.csv"
        if not p4.is_file() or not p5.is_file():
            return False
        if not _body_stage6_complete(run_dir=run_dir, stage5_csv=p5, num_images=num_images):
            return False
    return True


def _body_stage6_complete(
    *,
    run_dir: Path,
    stage5_csv: Path,
    num_images: int,
) -> bool:
    if not stage5_csv.is_file():
        return False
    rows = read_csv(stage5_csv)
    if not rows:
        return False
    out_dir = run_dir / "stage6_new_texture_generation"
    for row in rows:
        label = truncate_for_path((row.get("label_zh") or "").strip())
        if not label:
            return False
        for shot in range(1, num_images + 1):
            p = out_dir / f"{label}_{shot}.png"
            if not _is_readable_raster_image(p):
                return False
    return True


def _process_one_theme_job(
    theme_dir: Path,
    *,
    list_index: int,
    total_themes: int,
    out_root: Path,
    pipeline_line: str,
    num_images: int,
    stage4_disable_search: bool,
    dry_run: bool,
    overwrite: bool,
    state_lock: threading.Lock,
    counter: list[int],
    failed: list[str],
) -> None:
    """单主题：已齐则跳过；否则 wipe → Stage4→5→6 顺序跑完，再校验 CSV 与预览图后线程才结束。"""
    tag = theme_dir.name
    detail = "异常退出"
    try:
        prefs_path = pipeline_render_prefs_path(theme_dir)
        prefs_data = load_render_prefs_dict(prefs_path)
        try:
            pairs = parse_body_templates_from_prefs(prefs_data)
        except (TypeError, ValueError) as e:
            detail = f"body_templates 解析失败: {e}"
            with state_lock:
                failed.append(f"{tag}:prefs")
            return
        if not pairs:
            detail = "无 body_templates"
            with state_lock:
                failed.append(f"{tag}:no_templates")
            return

        done = _body_theme_pipeline_done(
            fashion_tag=tag,
            pairs=pairs,
            num_images=num_images,
            pipeline_line=pipeline_line,
        )
        if not overwrite and done:
            detail = "跳过（整主题已齐：各模板 stage4/5 CSV 且 Stage6 预览齐）"
            return

        print(
            f"\n[RUN] ========== [{list_index}/{total_themes}] fashion-tag={tag} ==========",
            flush=True,
        )
        if overwrite:
            wipe_reason = "--overwrite：强制整主题重跑"
            print("[OVERWRITE] 删除本主题全部身体模板的 stage4/5/6 后自 Stage4 完整重跑。", flush=True)
        else:
            wipe_reason = (
                "扫描未齐：缺 stage4/5 CSV 或 Stage6 预览缺失/数量不足/非有效 PNG·JPEG，整主题清空后重跑"
            )
        _wipe_body_theme_templates(
            out_root=out_root,
            fashion_tag=tag,
            pairs=pairs,
            dry_run=dry_run,
            detail=wipe_reason,
            pipeline_line=pipeline_line,
        )

        extra4: list[str] = []
        if stage4_disable_search:
            extra4.append("--disable-search")

        code = _run_py(
            "stage4_fashion_prompt/generate_fashion_prompts.py",
            ["--fashion-tag", tag, "--pipeline-line", pipeline_line, *extra4],
            dry_run=dry_run,
        )
        if code != 0:
            detail = f"Stage4 失败 exit={code}"
            with state_lock:
                failed.append(f"{tag}:stage4")
            return

        code = _run_py(
            "stage5_new_texture_prompt/build_texture_prompts.py",
            ["--fashion-tag", tag, "--pipeline-line", pipeline_line],
            dry_run=dry_run,
        )
        if code != 0:
            detail = f"Stage5 失败 exit={code}"
            with state_lock:
                failed.append(f"{tag}:stage5")
            return

        code = _run_py(
            "stage6_new_texture_generation/generate_seedream_images.py",
            [
                "--fashion-tag",
                tag,
                "--pipeline-line",
                pipeline_line,
                "--num-images",
                str(num_images),
                "--resume",
            ],
            dry_run=dry_run,
        )
        if code != 0:
            detail = f"Stage6 失败 exit={code}"
            with state_lock:
                failed.append(f"{tag}:stage6")
            return

        if not _body_theme_pipeline_done(
            fashion_tag=tag,
            pairs=pairs,
            num_images=num_images,
            pipeline_line=pipeline_line,
        ):
            detail = "子进程成功但磁盘未齐（缺 CSV 或 Stage6 预览未达张数/非有效图）"
            with state_lock:
                failed.append(f"{tag}:verify")
            return

        detail = "完成（Stage4→5→6 已跑完且 CSV+预览校验通过）"
    except Exception as exc:  # noqa: BLE001
        detail = f"未捕获异常: {type(exc).__name__}: {exc}"
        with state_lock:
            failed.append(f"{tag}:exception")
    finally:
        with state_lock:
            counter[0] += 1
            cur = counter[0]
        print(f"[PROGRESS] {cur}/{total_themes} tag={tag} {detail}", flush=True)


def run_body_batch(
    *,
    stage4_10: Path,
    pipeline_line: str,
    num_images: int,
    stage4_disable_search: bool,
    fashion_tag: str | None,
    dry_run: bool,
    overwrite: bool,
    workers: int,
) -> int:
    out_root = Path(SETTINGS.output_root).resolve()
    themes = filter_theme_dirs(stage4_10, fashion_tag)
    total = len(themes)
    ft_note = f"（--fashion-tag={fashion_tag!r}）" if fashion_tag else ""
    print(f"[INFO] 待处理主题目录数={total}" + ft_note, flush=True)
    if total == 0:
        if fashion_tag:
            print(
                f"[WARN] 无匹配主题：--fashion-tag={fashion_tag!r} 与任一主题目录名或 YAML 内 fashion_tag 均不一致",
                flush=True,
            )
        else:
            print("[WARN] 无匹配目录（须 stage4_10 下直接子目录含 pipeline_render_prefs.yml）", flush=True)
        return 0

    if overwrite:
        print(f"[INFO] --overwrite：将对本批 {total} 个主题逐一清空 stage4/5/6 后完整重跑。", flush=True)
    else:
        n_skip = n_run = 0
        for theme_dir in themes:
            tag = theme_dir.name
            prefs_data = load_render_prefs_dict(pipeline_render_prefs_path(theme_dir))
            try:
                pairs = parse_body_templates_from_prefs(prefs_data)
            except (TypeError, ValueError):
                continue
            if not pairs:
                continue
            if _body_theme_pipeline_done(
                fashion_tag=tag,
                pairs=pairs,
                num_images=num_images,
                pipeline_line=pipeline_line,
            ):
                n_skip += 1
            else:
                n_run += 1
        print(
            f"[INFO] 首轮扫描（无 --overwrite）：已齐跳过 {n_skip} 个主题，不齐将整主题清空重跑 {n_run} 个主题",
            flush=True,
        )

    n_workers = max(1, int(workers))
    print(
        f"[INFO] workers={n_workers}：至多 {n_workers} 个主题并行；"
        "每个主题内 Stage4→5→6 顺序执行，且输出校验通过后该槽位才接下一主题。",
        flush=True,
    )

    state_lock = threading.Lock()
    counter: list[int] = [0]
    failed: list[str] = []

    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        futures = {
            pool.submit(
                _process_one_theme_job,
                theme_dir,
                list_index=i,
                total_themes=total,
                out_root=out_root,
                pipeline_line=pipeline_line,
                num_images=num_images,
                stage4_disable_search=stage4_disable_search,
                dry_run=dry_run,
                overwrite=overwrite,
                state_lock=state_lock,
                counter=counter,
                failed=failed,
            ): theme_dir.name
            for i, theme_dir in enumerate(themes, start=1)
        }
        for fut in as_completed(futures):
            fut.result()

    print(f"[DONE] 已遍历 {total} 个主题目录。", flush=True)
    if failed:
        print(f"[WARN] 未完全成功: {' '.join(failed)}", flush=True)
        return 1
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pipeline",
        required=True,
        metavar="LINE",
        help=(
            "必填：output 下产品线子目录名，须与磁盘上 output/<LINE>/stage4_10 一致；"
            "不从环境变量推断，避免漏设 PIPELINE_LINE。"
        ),
    )
    parser.add_argument(
        "--stage4-10-root",
        default=None,
        metavar="DIR",
        help=f"覆盖 stage4_10 根路径（默认 OUTPUT_ROOT/<产品线>/{PIPELINE_TEMPLATE_USER_SUBDIR}）",
    )
    parser.add_argument("--num-images", type=int, default=4, metavar="N", help="Stage6 每条 prompt 期望张数（默认 4）")
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        metavar="N",
        help="并行处理主题数上限；每主题须顺序跑完 Stage4→6 且磁盘校验通过后才释放槽位（默认 4）",
    )
    parser.add_argument(
        "--stage4-disable-search",
        action="store_true",
        help="传给 Stage4 的 --disable-search（省 Token）",
    )
    parser.add_argument(
        "--fashion-tag",
        "--only-tag",
        dest="fashion_tag",
        default=None,
        metavar="TAG",
        help=(
            "只处理该主题：与 stage4_10 下主题目录 basename 一致，或与 YAML 中 fashion_tag / 其截断名一致。"
            "未加 --overwrite 且该主题身体链路已齐则跳过；加 --overwrite 则强制删产物后重跑。"
        ),
    )
    parser.add_argument("--dry-run", action="store_true", help="只打印将执行的命令与清理动作，不调用 API")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="跳过「已完整」判断：对该主题删光 stage4/5/6 后完整重跑；默认关闭",
    )
    args = parser.parse_args()

    line = (args.pipeline or "").strip()
    if not line:
        parser.error("--pipeline 不能为空，请传入 output 下的产品线目录名。")
    if args.stage4_10_root:
        stage4_10 = Path(args.stage4_10_root).expanduser().resolve()
    else:
        stage4_10 = pipeline_line_run_root(Path(SETTINGS.output_root).resolve(), pipeline_line=line) / PIPELINE_TEMPLATE_USER_SUBDIR

    print(f"[INFO] stage4_10 根: {stage4_10}", flush=True)
    print(f"[INFO] 产品线(--pipeline) 用于路径与已齐判定: {line!r}", flush=True)
    num_images = max(1, int(args.num_images))
    ow = bool(args.overwrite)
    if ow:
        print("[INFO] --overwrite 已开启：已完整主题也会删产物后重跑。", flush=True)

    fashion = (args.fashion_tag or "").strip() or None
    n_workers = max(1, int(args.workers))
    rc = run_body_batch(
        stage4_10=stage4_10,
        pipeline_line=line,
        num_images=num_images,
        stage4_disable_search=bool(args.stage4_disable_search),
        fashion_tag=fashion,
        dry_run=bool(args.dry_run),
        overwrite=ow,
        workers=n_workers,
    )
    sys.exit(rc)


if __name__ == "__main__":
    main()
