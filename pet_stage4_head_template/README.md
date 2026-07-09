# Pet Stage4：宠物头套模板制作（预留）

**尚未实现。** 后续可能包括：

- 头套模板 mesh 预览 / 减面
- 与用户上传真实宠物图 + 头套模板的合成流程对接

路径预留：`output/宠物定制/pet_head_template/<run-subdir>/`（见 `common/pet_pipeline_paths.py`）。

当前宠物定制核心链路：

1. `pet_stage1_model_prompts` — 内置模特 prompt
2. `pet_stage2_model_images` — 模特出图
3. `pet_stage3_relief_render` — 订单浮雕拉模 + 360 渲染

与人偶定制（`stage1`～`stage12` + `PIPELINE_LINE=卡通人偶定制`）**产品线分离**，共享层见 `common/pipeline_lines.py`、`common/llm_clients.py`、`common/blender_cycles_gpu.py` 等。
