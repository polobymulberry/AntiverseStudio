# Stage7 手工筛图

从对应流水线的 `output/stage4_10/<truncate(fashion_tag)>/<模板名>/stage6_new_texture_generation/` 中：按组（每组同一 `label_zh` 的多张 `_1`～`_N`）筛图，复制选中 PNG 到本目录（`stage7_new_texture_generation_selected/`），供阶段8 贴图。

建议路径（与阶段6 输出一致）：

`stage4_10/<truncate(fashion_tag)>/<template_name>/<label_zh>_<idx>.png`
