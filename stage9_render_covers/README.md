# Stage9 封面图输出

本阶段由同一 Blender 脚本完成：仓库根下执行

`stage11_render_videos/blender_render_videos.py`

并加 **`--pass covers`**。产物写入**同一 run** 的 `stage9_render_covers/`，为每个 `stage8` GLB 生成 **`<模型名>_cover.png`**（第 18 帧，**不再**生成 `cover.png`）。

脚本会按 **`pipeline_render_prefs.yml`**（或 CLI）中的 **`head_object` / `hair_object`** 只打开这一对头/发；其余命名符合 **`female|male_<数字>_head`** / **`_hair`** 的物体一律 **`hide_render`**，不参与出图。导入的 GLB 以本次导入的**顶层根物体**及名为 **`body`** 的物体统一 **`scale = (0.1, 0.1, 0.1)`**（与 Stage11 正片相同逻辑）。

阶段8 目录中通常为 **10** 个 GLB 对应 10 张候选封面；随后在 `stage9_render_covers/` 中再人工挑选 **6** 张 **`<模型名>_cover.png`**（正片目标 5、备损 1）复制到

`output/stage4_10/<模板>/<需求截断>/stage10_render_covers_selected/`

再运行 **`--pass videos`** 生成环绕视频（见仓库 README）。

## 多进程（与 Stage11 共用同一脚本）

`blender_render_videos.py` 支持 **`--workers N`**（未设环境变量时默认 `1`）。若运行时存在 **`BLENDER_WORKERS`**，则以该环境变量为准（优先生效）。`N>1` 时父进程会拉起多个 Blender 子进程按任务分片渲染；**`--pass covers`** 与 **`--pass videos`** 均适用。

子进程通过 **`STAGE11_JSON`**（及兼容的 **`STAGE9_JSON`**）接收完整配置，**不要**假设 `--` 后的 CLI 参数在子进程里仍然有效。

示例（封面阶段 4 路）：

```bash
BLENDER_WORKERS=4 blender -b --python-use-system-env resource/blender/blender_render_videos.blend \
  -P stage11_render_videos/blender_render_videos.py -- \
  --pass covers \
  --workers 4 \
  --studio-tint-hex "#E3D9C6" \
  --template "body_24_overall_set" \
  --user-requirement "从80/90后的流行儿童动漫中提取相应主题的服装颜色纹理logo" \
  --head-object female_00_head \
  --hair-object female_00_hair
```

正片阶段将 **`--pass covers`** 改为 **`--pass videos`**，其余与仓库根目录 README 中 Stage11 说明一致（如 **`--all-glbs`**、**`--resume`** 等）。
