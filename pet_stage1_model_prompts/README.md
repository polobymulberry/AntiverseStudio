# Pet Stage1：宠物内置高清模特 Prompt

生成 10 个品种的**摄影棚头部特写** prompt CSV，**确认后再跑 Stage2 出图**。

## 输出

- `output/pet_model_library/<run-subdir>/pet_model_prompts.csv`

## 命令

```bash
conda activate antiversestudio
python pet_stage1_model_prompts/generate_pet_model_prompts.py --run-subdir 20260623_v1
```

审阅 CSV 后可手工编辑 `full_prompt` / `subject_desc`，再执行 Stage2。

## CSV 字段

`species_id`, `label_zh`, `pet_name_en`, `pet_name_zh`, `prompt_base`, `subject_desc`, `full_prompt`, `output_filename`

- `pet_name_en`：宠物英文昵称，**4～6 个字母**
- `pet_name_zh`：宠物中文昵称，**2～4 个汉字**
- `label_zh`：品种名（非宠物昵称）

Prompt 为**头部大特写 + 摄影棚 seamless 背景**，专业柔光布光，非居家/户外场景。

品种与昵称见 `common/pet_model_prompts.py` 的 `DEFAULT_PET_MODEL_SPECS`。
