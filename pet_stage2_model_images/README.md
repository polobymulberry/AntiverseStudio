# Pet Stage2：宠物摄影棚头部特写出图（本地 Qwen-Image-2512）

读取 Stage1 CSV，在 GPU 机器上通过 **本地 diffusers** 加载 `Qwen-Image-2512` 权重出图（参考 drdoll `tool/pet_shell/run_qwen_image_local.py`），**不**调用 DashScope Qwen-Image Web API。

## 环境

需在已安装 `torch`、`diffusers`、`Pillow` 且能访问本地权重目录的 conda 环境中运行，例如：

```bash
conda activate qwen-image   # 与 drdoll 本地 Qwen-Image 环境一致
conda activate antiversestudio  # 若该环境已安装上述依赖亦可
```

模型默认路径：`QWEN_IMAGE_MODEL_PATH` → `.../Qwen/Qwen-Image-2512`（`local_files_only=True`）。

## 输入 / 输出

- 输入：`output/pet_model_library/<run-subdir>/pet_model_prompts.csv`
- 输出：`output/pet_model_library/<run-subdir>/images/<species_id>.png`

默认 **1024×1024**；可通过 `QWEN_IMAGE_WIDTH` / `QWEN_IMAGE_HEIGHT` 或 `--size 1104*1472` 覆盖。

## 命令

```bash
python pet_stage2_model_images/generate_pet_model_images.py --run-subdir 20260623_v1
python pet_stage2_model_images/generate_pet_model_images.py --run-subdir 20260623_v1 --resume
python pet_stage2_model_images/generate_pet_model_images.py --run-subdir 20260623_v1 --only-species golden_retriever

# 指定模型路径 / 竖版尺寸 / 多 GPU 队列（大批量 prompt 时）
python pet_stage2_model_images/generate_pet_model_images.py --run-subdir 20260623_v1 \
  --model-path /path/to/Qwen-Image-2512 --size 1104*1472 --multi-gpu
```

## 环境变量

| 变量 | 默认 | 说明 |
|------|------|------|
| `QWEN_IMAGE_MODEL_PATH` | ModelScope 缓存路径 | 本地权重目录 |
| `QWEN_IMAGE_WIDTH` / `HEIGHT` | `1024` | 出图宽高 |
| `QWEN_IMAGE_TRUE_CFG_SCALE` | `4.0` | CFG |
| `QWEN_IMAGE_NUM_INFERENCE_STEPS` | `28` | 推理步数 |
| `QWEN_IMAGE_BASE_SEED` | `1472666871` | 种子基值 + 行序号 |
| `QWEN_IMAGE_NEGATIVE_PROMPT` | 见 `settings.py` | 宠物肖像负向词 |
| `NUM_GPUS_TO_USE` | `8` | `--multi-gpu` 时使用 |
| `GPUS_PER_INSTANCE` | `2` | 每个 worker 占用 GPU 数 |

精选后可复制到 `resource/pet_model_reference/`。
