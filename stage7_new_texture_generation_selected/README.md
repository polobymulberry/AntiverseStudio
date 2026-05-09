# Stage7 手工筛图

从对应流水线的 `output/stage4_10/<模板名>/<需求截断>/stage6_new_texture_generation/` 中：对 **20 组**（每组同一 `label_zh` 的 `_1`～`_4`）**每组先留 1 张**（共 20 张），再从中选出 **10 张** 复制到本目录，供阶段8 贴图。

建议目录结构（与阶段8 解析一致）：

`stage4_10/<template_name>/<路径段>/<label_zh>_<idx>.png`

（`<路径段>` 为 `truncate_for_path(fashion_tag)` 或 `truncate_for_path(user_requirement)`，与阶段4～6 一致。）
