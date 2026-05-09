# Stage Data Contract

本文件定义各阶段输入输出，便于排查和重跑。

## Stage1 -> Stage2

- 输入：`BODY_TEMPLATE_ROOT/*/high_poly/body.obj`
- 输出：`output/stage1_body_template_preview/<template>.png`
- 可选前提检查（不输出图）：`blender -b --python-use-system-env ... -P ... -- --check-prerequisite`（见 README：Blender 自带 Python 需安装 `python-dotenv`），逐个模板导入后要求 `bpy.data.objects["body"]` 存在，否则记为失败并以退出码 1 结束（便于 CI / 批量排查命名）。
- 可选 OBJ 文本修复（`conda activate figshion3d` 后）：`python stage1_body_template_preview/fix_obj_object_name_to_body.py`，经 `common.settings` 读取模板根与 `.env`；将各模板 `high_poly/body.obj` 中 Wavefront `o` 规范为单一 `o body`（多 `o` 时删除多余行以合并），**并删除所有 `g` 组行**；打印改动痕迹；默认写回前备份 `body.obj.bak`。

## Stage2 -> Stage4

- 输出 CSV：`output/stage2_body_template_description.csv`
- 字段：
  - `template_name`
  - `image_path`
  - `description`

## Stage3 -> Stage8

- 输出 CSV：`output/stage3_body_template_decimate.csv`（每「减面 + OSS 上传」成功一条即落盘；`-- --resume` 仅跳过 CSV 中 OSS 字段齐全且本地 `body.obj` 有效的模板）
- 字段：
  - `template_name`
  - `faces_before`（减面前网格多边形总数）
  - `faces_after`（减面后网格多边形总数）
  - `local_obj`
  - `oss_key`
  - `public_url`

## Stage4 -> Stage5/6

- **同目录渲染偏好（可选但推荐）**：`generate_fashion_prompts.py` 与 Stage9/11 在启动时调用 `common.pipeline_render_prefs.sync_pipeline_render_prefs_at_start`：**立即**创建或更新 `pipeline_render_prefs.yml`（随机 `studio_tint_hex`、默认头/发，或由 CLI/已有文件合并）；CLI 显式传入的项会写回文件。键名亦支持 `studio_tint_color` 作为 `studio_tint_hex` 的别名。
- 输出 CSV：`output/stage4_10/<template_name>/<truncate_for_path(user_requirement)>/stage4_fashion_prompt.csv`（`stage4_10` 见 `common.utils.PIPELINE_TEMPLATE_USER_SUBDIR`；`generate_fashion_prompts.py` 须 `--template` 与 `--user-requirement`；**默认 20 行** prompt，条数由脚本内 `PROMPT_COUNT` 控制；合法模板名以阶段2 CSV 中 `template_name` 为准；需求目录名与 `common.utils.truncate_for_path` 一致，默认最长 48 字符；可选 `--fashion-tag` 见 `common.utils.output_template_user_dir`）
- 字段：
  - `template_name`
  - `user_requirement`
  - `fashion_tag`（可选，与 CLI `--fashion-tag` 一致时非空）
  - `prompt_zh`
  - `prompt_abstract_zh`
  - `label_zh`
  - `label_en`
  - `reference_image`

## Stage5 -> Stage6

- 输入：同上目录下的 `stage4_fashion_prompt.csv`（`build_texture_prompts.py` 须 `--template`、`--user-requirement` 与阶段4 一致）
- 输出 CSV：`output/stage4_10/<template_name>/<truncate_for_path(user_requirement)>/stage5_new_texture_prompt.csv`
- 字段：
  - `template_name`
  - `user_requirement`
  - `fashion_tag`
  - `label_zh`
  - `label_en`
  - `texture_prompt`
  - `full_prompt`

## Stage6 -> Stage7

- 输入：默认由 `--template` 与 `--user-requirement` 解析为 `output/stage4_10/<template>/<requirement截断>/stage5_new_texture_prompt.csv`，或显式 `--input-csv`
- 请求：每条 `full_prompt` 连续调用 Seedream `N` 次、每次 `n=1`（`N` 为 `--num-images`，默认 4），不在 prompt 前拼接额外文案
- 输出：`output/stage4_10/<template>/<requirement截断>/stage6_new_texture_generation/<label_zh>_<idx>.png`

## Stage7 -> Stage8

- 筛图目录（与阶段6 同 run）：`output/stage4_10/<template>/<requirement截断>/stage7_new_texture_generation_selected/<label_zh>_<idx>.png`（源图来自同目录上级 `stage6_new_texture_generation/`）。人工流程：20 组 × 每组 4 张 Seedream 图先**每组留 1**（20 张），再从中选 **10 张** 放入本目录供贴图。

## Stage8 -> Stage9

- 输出目录：`output/stage4_10/<template>/<requirement>/stage8_new_texture_model_generation/`
- 每个风格至少一个 **`<label_zh>.glb`**：**默认**在混元 3D **网页**用积分生成后下载放入；**网页积分不足**时用 `generate_textured_models.py` 走 **API** 补跑。手工/网页流程可无 `_result` 等预览图
- 后续（封面/正片）输入：扫描 `**/stage8_new_texture_model_generation/*.glb`，与是否同目录存在 PNG 预览无关
- **说明**：`generate_textured_models.py` **不**设置 Blender 里 Studio 背景墙 Tint；该参数在 **Stage9/11** 的 `blender_render_videos.py` 中通过 `--studio-tint-hex` 或 `--random-studio-tint` 控制，预设见 `common/studio_render_constants.py`。与 **Stage4** 同目录的 **`pipeline_render_prefs.yml`** 可替代上述 CLI（见 Stage4 契约）。

## Stage9（仅封面，候选池）

- **Blender 工程**：`resource/blender/blender_render_videos.blend`。
- **渲染脚本**：`stage11_render_videos/blender_render_videos.py`（`--pass covers`）
- **输出**：`output/stage4_10/<template>/<requirement>/stage9_render_covers/<label_zh>_cover.png`（第 18 帧，**不**再写 `cover.png`；将父目录 `stage8_new_texture_model_generation` 换为 `stage9_render_covers`）。
- **Studio 背景墙 Tint / 头模物体名**：`--template`+`--user-requirement` 时启动即同步 **`pipeline_render_prefs.yml`**（见 Stage4）；与 `--studio-tint-hex` / `--random-studio-tint`、头/发 CLI 合并规则同上。

## Stage9 -> Stage10

- 手工从 `.../stage9_render_covers/` 中挑选 **6** 个 `<label_zh>_cover.png`（正片目标 5、备损 1），复制到**同一 run** 下 `.../stage10_render_covers_selected/`。文件名须保持 `<label_zh>_cover.png` 以与 GLB 主文件名一致。

## Stage11（5 秒环绕正片，仅已选或全部）

- **渲染脚本**：同上 `stage11_render_videos/blender_render_videos.py`（`--pass videos`）
- **默认**（无 `--all-glbs`）：只渲染 `stage10_render_covers_selected/*_cover.png` 中出现的 `label` 在 `stage8` 有对应 **`.glb`** 的条目标记；输出 **`stage11_render_videos/<label_zh>.mp4`**（不重复写封面图；封面在 Stage9/10 已定稿）。
- **`--only-glb-stems 'A,B,...'`**：在上述任务集上再过滤为指定 **GLB 主名**（逗号分隔，与 `*.glb`  basename 一致）；**`--pass covers`** 时同样可用。与 **`--workers`** 多进程兼容（随 `STAGE11_JSON` 下发）。
- **`--all-glbs`**：对 run 下全部 stage8 **GLB** 渲正片，等同旧版「不筛选」的批量视频。
- **多进程**：父进程经 `STAGE11_JSON`（及兼容的 `STAGE9_JSON`）向子进程下发表配置。
- **临时输出**：`--render-output-dir <DIR>` 时本批 mp4/封面 PNG 均写入该目录（默认不传，仍用 run 下 `stage11_render_videos` / `stage9_render_covers`）。

## Stage12（白模透明视频）

- **Blender 工程**：`resource/blender/render_around_white_mesh.blend`
- **渲染脚本**：`stage12_render_white_mesh_videos/blender_render_white_mesh_videos.py`
- **输入**：与 Stage9/11 类似，推荐 `--template` + `--user-requirement` 限定单一 run；扫描 `stage8_new_texture_model_generation/*.glb`
- **处理逻辑**：删除工程内 `body`，导入 GLB 后将 `body` 缩放为 `0.1`，并把 body 及子网格材质改为纯白 Diffuse BSDF（Roughness=1.0）
- **输出**：`output/stage4_10/<template>/<requirement>/stage12_render_white_mesh_videos/white_model.mov`（QuickTime + **PNG** 编码 / **RGBA** 透明；帧范围 1-180）
