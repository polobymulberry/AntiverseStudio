"""Qwen-Image-2512 本地 diffusers 推理（参考 drdoll_backend ``tool/qwen_image_local/batch_runner.py``）。

职责：
    加载本地 ``QwenImagePipeline``，按 prompt 生成 PNG；支持单进程顺序出图与多 GPU 队列批量出图。
业务作用：
    Pet Stage2 等脚本在 GPU 机器上本地出图，不调用 DashScope Qwen-Image Web API。
系统定位：
    AntiverseStudio 与 drdoll 本地生图逻辑对齐的共享层；模型路径由 env ``QWEN_IMAGE_MODEL_PATH`` 指定。

模型加载 / 内存：
    Pipeline 在 worker 子进程或单进程 Generator 内加载一次并复用；启用 ``enable_vae_slicing`` 降低显存峰值。
"""

from __future__ import annotations

import atexit
import os
import queue
import signal
import sys
import threading
import time
from dataclasses import dataclass
from multiprocessing import Event, Process, Queue
from pathlib import Path
from typing import Iterator

import torch

from common.settings import SETTINGS

try:
    import torch.multiprocessing as mp

    mp.set_start_method("spawn", force=True)
except RuntimeError:
    pass

# 与 drdoll ``tool/qwen_image_local/batch_runner.py`` 默认一致
TRUE_CFG_SCALE = 4.0
NUM_INFERENCE_STEPS = 28
TASK_QUEUE_SIZE = 100
TASK_TIMEOUT = 300


@dataclass(frozen=True)
class LocalImageRunConfig:
    """单次本地 Qwen-Image 运行参数（可覆盖 SETTINGS 默认值）。"""

    model_path: str
    width: int
    height: int
    true_cfg_scale: float
    num_inference_steps: int
    negative_prompt: str
    num_gpus: int
    gpus_per_instance: int

    @classmethod
    def from_settings(
        cls,
        *,
        model_path: str | None = None,
        width: int | None = None,
        height: int | None = None,
        negative_prompt: str | None = None,
    ) -> LocalImageRunConfig:
        return cls(
            model_path=(model_path or str(SETTINGS.qwen_image_model_path)).strip(),
            width=width if width is not None else SETTINGS.qwen_image_width,
            height=height if height is not None else SETTINGS.qwen_image_height,
            true_cfg_scale=SETTINGS.qwen_image_true_cfg_scale,
            num_inference_steps=SETTINGS.qwen_image_num_inference_steps,
            negative_prompt=negative_prompt or SETTINGS.qwen_image_negative_prompt,
            num_gpus=SETTINGS.num_gpus_to_use,
            gpus_per_instance=SETTINGS.gpus_per_instance,
        )


@dataclass(frozen=True)
class LocalImageTask:
    """单张本地生图任务。

    Attributes:
        task_id: 队列内唯一标识（如 species_id）。
        prompt: 正向 prompt。
        output_path: PNG 落盘路径。
        seed: 随机种子。
    """

    task_id: str
    prompt: str
    output_path: Path
    seed: int


def parse_qwen_image_wh(size: str | None = None) -> tuple[int, int]:
    """解析 ``1024*1024`` / ``1024x1024`` 为 (width, height)。"""
    raw = (size or f"{SETTINGS.qwen_image_width}*{SETTINGS.qwen_image_height}").strip()
    text = raw.replace("×", "*").replace("x", "*").replace("X", "*")
    if "*" not in text:
        raise ValueError(f"尺寸须为 宽*高，例如 1024*1024，当前: {raw!r}")
    w_str, h_str = text.split("*", 1)
    return int(w_str.strip()), int(h_str.strip())


def is_valid_png_file(path: Path) -> bool:
    """校验 PNG 是否可完整解码。"""
    try:
        from PIL import Image

        with Image.open(path) as img:
            if img.format != "PNG":
                return False
            img.load()
        return True
    except Exception:
        return False


def _gpu_worker_process(
    worker_id: int,
    model_path: str,
    task_queue: Queue,
    result_queue: Queue,
    stop_event: Event,
    gpu_ids: tuple[int, ...],
    *,
    width: int,
    height: int,
    true_cfg_scale: float,
    num_inference_steps: int,
) -> None:
    """子进程 GPU Worker：加载 QwenImagePipeline 并消费任务队列。"""
    from diffusers import QwenImagePipeline

    torch_dtype = torch.bfloat16 if torch.cuda.is_available() else torch.float32
    n_devices = torch.cuda.device_count()
    if n_devices < 1:
        print(f"[Worker {worker_id} GPU {gpu_ids}] 无可用 GPU", file=sys.stderr)
        return

    try:
        if n_devices >= 2:
            pipe = QwenImagePipeline.from_pretrained(
                model_path,
                torch_dtype=torch_dtype,
                local_files_only=True,
                device_map="balanced",
            )
        else:
            pipe = QwenImagePipeline.from_pretrained(
                model_path,
                torch_dtype=torch_dtype,
                local_files_only=True,
            )
            pipe = pipe.to("cuda:0")
        pipe.enable_vae_slicing()
    except Exception as exc:
        print(f"[Worker {worker_id} GPU {gpu_ids}] 模型加载失败: {exc}", file=sys.stderr)
        return

    device_first = "cuda:0"
    print(f"[Worker {worker_id} GPU {gpu_ids}] 已启动（可见 {n_devices} 张卡）", flush=True)

    while not stop_event.is_set():
        try:
            task = task_queue.get(timeout=1)
            if task is None:
                break
            task_id = task["task_id"]
            prompt = task["prompt"]
            negative_prompt = task["negative_prompt"]
            seed = task["seed"]
            task_width = task.get("width", width)
            task_height = task.get("height", height)
            task_cfg = task.get("true_cfg_scale", true_cfg_scale)
            task_steps = task.get("num_inference_steps", num_inference_steps)

            try:
                generator = torch.Generator(device=device_first).manual_seed(seed)
                image = pipe(
                    prompt=prompt,
                    negative_prompt=negative_prompt,
                    true_cfg_scale=task_cfg,
                    width=task_width,
                    height=task_height,
                    num_inference_steps=task_steps,
                    generator=generator,
                ).images[0]
                result_queue.put(
                    {
                        "task_id": task_id,
                        "image": image,
                        "success": True,
                        "gpu_id": worker_id,
                    }
                )
            except Exception as exc:
                result_queue.put(
                    {
                        "task_id": task_id,
                        "success": False,
                        "error": str(exc),
                        "gpu_id": worker_id,
                    }
                )
        except queue.Empty:
            continue
        except Exception as exc:
            print(f"[Worker {worker_id} GPU {gpu_ids}] 异常: {exc}", file=sys.stderr)
            continue

    print(f"[Worker {worker_id} GPU {gpu_ids}] 已退出", flush=True)


class MultiGPULocalImageManager:
    """多 GPU 任务队列管理；每 ``gpus_per_instance`` 张卡一个 worker 实例。"""

    def __init__(
        self,
        *,
        model_path: str,
        num_gpus: int | None = None,
        gpus_per_instance: int | None = None,
        task_queue_size: int = TASK_QUEUE_SIZE,
        width: int = 1024,
        height: int = 1024,
        true_cfg_scale: float = TRUE_CFG_SCALE,
        num_inference_steps: int = NUM_INFERENCE_STEPS,
    ) -> None:
        self.model_path = model_path
        total = torch.cuda.device_count()
        self.num_gpus = min(num_gpus or SETTINGS.num_gpus_to_use, total)
        self.gpus_per_instance = max(
            1,
            min(gpus_per_instance or SETTINGS.gpus_per_instance, self.num_gpus),
        )
        self.num_workers = max(1, self.num_gpus // self.gpus_per_instance)
        self.gpu_id_pairs: list[tuple[int, ...]] = [
            tuple(range(i * self.gpus_per_instance, (i + 1) * self.gpus_per_instance))
            for i in range(self.num_workers)
        ]
        self.task_queue: Queue = Queue(maxsize=task_queue_size)
        self.batch_results: Queue = Queue()
        self.stop_event = Event()
        self.worker_processes: list[Process] = []
        self._width = width
        self._height = height
        self._true_cfg_scale = true_cfg_scale
        self._num_inference_steps = num_inference_steps

    def start_workers(self) -> None:
        """启动各 GPU worker 子进程。"""
        env_orig = os.environ.get("CUDA_VISIBLE_DEVICES")
        for i, gpu_ids in enumerate(self.gpu_id_pairs):
            os.environ["CUDA_VISIBLE_DEVICES"] = ",".join(map(str, gpu_ids))
            proc = Process(
                target=_gpu_worker_process,
                args=(
                    i,
                    self.model_path,
                    self.task_queue,
                    self.batch_results,
                    self.stop_event,
                    gpu_ids,
                ),
                kwargs={
                    "width": self._width,
                    "height": self._height,
                    "true_cfg_scale": self._true_cfg_scale,
                    "num_inference_steps": self._num_inference_steps,
                },
            )
            proc.start()
            self.worker_processes.append(proc)
        if env_orig is not None:
            os.environ["CUDA_VISIBLE_DEVICES"] = env_orig
        else:
            os.environ.pop("CUDA_VISIBLE_DEVICES", None)
        print(
            f"已启动 {self.num_workers} 个 Qwen-Image worker（每实例 {self.gpus_per_instance} GPU）",
            flush=True,
        )

    def submit_task(
        self,
        task_id: str,
        prompt: str,
        *,
        negative_prompt: str,
        seed: int,
    ) -> None:
        """投递任务到队列。"""
        task = {
            "task_id": task_id,
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "seed": seed,
            "width": self._width,
            "height": self._height,
            "true_cfg_scale": self._true_cfg_scale,
            "num_inference_steps": self._num_inference_steps,
        }
        while True:
            try:
                self.task_queue.put(task, timeout=10)
                return
            except queue.Full:
                time.sleep(2)

    def stop(self) -> None:
        """停止所有 worker。"""
        self.stop_event.set()
        for _ in range(self.num_workers):
            try:
                self.task_queue.put(None, timeout=1)
            except queue.Full:
                pass
        for proc in self.worker_processes:
            proc.join(timeout=5)
            if proc.is_alive():
                proc.terminate()
        print("Multi-GPU Qwen-Image Manager 已停止", flush=True)


class QwenImageLocalGenerator:
    """单进程本地 Qwen-Image 生成器（适合少量 CSV 行顺序出图）。"""

    def __init__(
        self,
        *,
        model_path: str | None = None,
        width: int | None = None,
        height: int | None = None,
        true_cfg_scale: float | None = None,
        num_inference_steps: int | None = None,
    ) -> None:
        self.model_path = (model_path or str(SETTINGS.qwen_image_model_path)).strip()
        self.width = width if width is not None else SETTINGS.qwen_image_width
        self.height = height if height is not None else SETTINGS.qwen_image_height
        self.true_cfg_scale = (
            true_cfg_scale if true_cfg_scale is not None else SETTINGS.qwen_image_true_cfg_scale
        )
        self.num_inference_steps = (
            num_inference_steps
            if num_inference_steps is not None
            else SETTINGS.qwen_image_num_inference_steps
        )
        self._pipe = None

    def _ensure_pipeline(self) -> None:
        if self._pipe is not None:
            return
        if not Path(self.model_path).is_dir():
            raise FileNotFoundError(
                f"Qwen-Image 本地模型目录不存在: {self.model_path}\n"
                "请设置环境变量 QWEN_IMAGE_MODEL_PATH 指向 Qwen-Image-2512 权重目录。"
            )
        if not torch.cuda.is_available():
            raise RuntimeError("本地 Qwen-Image 需要 CUDA GPU，当前未检测到可用 GPU。")

        from diffusers import QwenImagePipeline

        torch_dtype = torch.bfloat16
        n_devices = torch.cuda.device_count()
        if n_devices >= 2:
            self._pipe = QwenImagePipeline.from_pretrained(
                self.model_path,
                torch_dtype=torch_dtype,
                local_files_only=True,
                device_map="balanced",
            )
        else:
            self._pipe = QwenImagePipeline.from_pretrained(
                self.model_path,
                torch_dtype=torch_dtype,
                local_files_only=True,
            )
            self._pipe = self._pipe.to("cuda:0")
        self._pipe.enable_vae_slicing()
        print(
            f"[Qwen-Image] 已加载本地模型: {self.model_path} "
            f"({self.width}×{self.height}, {n_devices} GPU)",
            flush=True,
        )

    def generate_pil(
        self,
        prompt: str,
        *,
        negative_prompt: str,
        seed: int,
    ):
        """生成单张 PIL 图像。"""
        self._ensure_pipeline()
        assert self._pipe is not None
        generator = torch.Generator(device="cuda:0").manual_seed(seed)
        return self._pipe(
            prompt=prompt,
            negative_prompt=negative_prompt,
            true_cfg_scale=self.true_cfg_scale,
            width=self.width,
            height=self.height,
            num_inference_steps=self.num_inference_steps,
            generator=generator,
        ).images[0]

    def save_png(
        self,
        prompt: str,
        output_path: Path,
        *,
        negative_prompt: str,
        seed: int,
    ) -> None:
        """生成并保存 PNG。"""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        image = self.generate_pil(prompt, negative_prompt=negative_prompt, seed=seed)
        image.save(output_path)


def run_local_image_tasks(
    tasks: list[LocalImageTask],
    *,
    run_config: LocalImageRunConfig | None = None,
    multi_gpu: bool = False,
) -> tuple[int, int]:
    """执行本地生图任务列表，返回 (成功数, 失败数)。"""
    if not tasks:
        return 0, 0

    cfg = run_config or LocalImageRunConfig.from_settings()
    if not Path(cfg.model_path).is_dir():
        raise FileNotFoundError(f"Qwen-Image 本地模型目录不存在: {cfg.model_path}")

    if multi_gpu:
        return _run_tasks_multi_gpu(tasks, run_config=cfg)
    return _run_tasks_single_process(tasks, run_config=cfg)


def _run_tasks_single_process(
    tasks: list[LocalImageTask],
    *,
    run_config: LocalImageRunConfig,
) -> tuple[int, int]:
    """单进程顺序执行（模型只加载一次）。"""
    gen = QwenImageLocalGenerator(
        model_path=run_config.model_path,
        width=run_config.width,
        height=run_config.height,
        true_cfg_scale=run_config.true_cfg_scale,
        num_inference_steps=run_config.num_inference_steps,
    )
    ok = 0
    failed = 0
    for task in tasks:
        try:
            gen.save_png(
                task.prompt,
                task.output_path,
                negative_prompt=run_config.negative_prompt,
                seed=task.seed,
            )
            print(f"[OK] {task.task_id} -> {task.output_path}", flush=True)
            ok += 1
        except Exception as exc:
            failed += 1
            print(f"[FAIL] {task.task_id}: {exc}", file=sys.stderr)
    return ok, failed


def _run_tasks_multi_gpu(
    tasks: list[LocalImageTask],
    *,
    run_config: LocalImageRunConfig,
) -> tuple[int, int]:
    """多 GPU 队列批量执行。"""
    num_gpus = min(run_config.num_gpus, torch.cuda.device_count())
    if num_gpus <= 0:
        raise RuntimeError("未检测到 GPU，无法使用 --multi-gpu。")

    manager = MultiGPULocalImageManager(
        model_path=run_config.model_path,
        num_gpus=num_gpus,
        gpus_per_instance=run_config.gpus_per_instance,
        width=run_config.width,
        height=run_config.height,
        true_cfg_scale=run_config.true_cfg_scale,
        num_inference_steps=run_config.num_inference_steps,
    )
    manager.start_workers()

    def cleanup() -> None:
        manager.stop()

    atexit.register(cleanup)
    signal.signal(signal.SIGINT, lambda _s, _f: (cleanup(), sys.exit(130)))
    signal.signal(signal.SIGTERM, lambda _s, _f: (cleanup(), sys.exit(143)))

    task_map = {t.task_id: t for t in tasks}

    def producer() -> None:
        for task in tasks:
            manager.submit_task(
                task.task_id,
                task.prompt,
                negative_prompt=run_config.negative_prompt,
                seed=task.seed,
            )
        for _ in range(manager.num_workers):
            try:
                manager.task_queue.put(None, timeout=10)
            except queue.Full:
                pass

    producer_thread = threading.Thread(target=producer, daemon=False)
    producer_thread.start()

    ok = 0
    failed = 0
    total = len(tasks)
    for _ in range(total):
        try:
            result = manager.batch_results.get(timeout=TASK_TIMEOUT * 2 + 120)
        except queue.Empty:
            print(f"[超时] 等待 Qwen-Image 结果超过 {TASK_TIMEOUT * 2 + 120}s", file=sys.stderr)
            failed += total - ok - failed
            break
        tid = str(result["task_id"])
        task = task_map.get(tid)
        if result.get("success") and result.get("image") is not None and task is not None:
            task.output_path.parent.mkdir(parents=True, exist_ok=True)
            result["image"].save(task.output_path)
            print(f"[OK] {tid} -> {task.output_path}", flush=True)
            ok += 1
        else:
            failed += 1
            print(
                f"[FAIL] {tid}: {result.get('error', 'unknown')}",
                file=sys.stderr,
            )

    producer_thread.join(timeout=5)
    cleanup()
    return ok, failed


def iter_pending_tasks_from_rows(
    rows: list[dict[str, str]],
    out_dir: Path,
    *,
    only_species: str = "",
    resume: bool = False,
    base_seed: int | None = None,
) -> Iterator[LocalImageTask]:
    """从 Pet Stage1 CSV 行构造待跑本地任务（跳过已存在有效 PNG）。"""
    only = (only_species or "").strip()
    seed_base = SETTINGS.qwen_image_base_seed if base_seed is None else base_seed
    for i, row in enumerate(rows):
        species_id = (row.get("species_id") or "").strip()
        if only and species_id != only:
            continue
        prompt = (row.get("full_prompt") or "").strip()
        if not prompt:
            continue
        fname = (row.get("output_filename") or f"{species_id}.png").strip()
        out_file = out_dir / fname
        if resume and is_valid_png_file(out_file):
            continue
        yield LocalImageTask(
            task_id=species_id or f"row_{i}",
            prompt=prompt,
            output_path=out_file,
            seed=seed_base + i,
        )
