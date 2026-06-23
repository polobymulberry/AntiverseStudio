# Stage Data Contract

本文件定义各阶段输入输出，便于排查和重跑。

**阶段 4～12 的 run 根路径**在 **`output/<PIPELINE_LINE>/`** 下（环境变量 **`PIPELINE_LINE`**，默认 **手办服装IP**；另一产品线可设为 **卡通人偶定制** 等）。下表在涉及 ``stage4_10`` 处等价于 ``output/<PIPELINE_LINE>/stage4_10/...``。

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

## Stage3a（可选：模板题材适配分析）

- **与 Stage3（减面）编号相邻但互不依赖**；供选题参考，不参与 Stage4 必填链路。
- 输入：`output/stage1_body_template_preview/<template>.png`（与 Stage1/2 同源）
- 脚本：`stage3a_body_template_theme_fit/analyze_theme_fit.py`（**默认 DashScope 联网**；`--disable-search` 可关）
- ``--auto-gen-yml``：不调用模型；从该 run 的 CSV 中筛选 ``fit_label=很合适``，写入 ``output/<产品线>/stage4_10/<截断>/pipeline_render_prefs.yml``；默认 ``--pipeline-line`` 为 **手办服装IP**（与 Stage4 手办线一致），可用 ``--pipeline-line`` / ``--pref-prompt-count`` / ``--overwrite-yml`` 调整
- 输出目录须**手动命名**：`--run-subdir <NAME>` → `output/stage3a_body_template_theme_fit/<NAME>/stage3a_body_template_theme_fit.csv`；或 `--output-csv` 指定完整路径（二选一）
- 每套模板候选行数：未传 ``--candidate-count`` 时，有 ``--theme-hint`` 则默认 **1 行**，否则默认 **10 行**（显式 ``--candidate-count N`` 覆盖）。模型输出 JSON，校验后**展开为长表**。每行 **`user_requirement_zh`** 为可直接写入 **`pipeline_render_prefs.yml`** 的 ``user_requirement``：**一条母题应能支撑 Stage4 批量产出多条差异纹理**，勿写成单款细纲；另附合适度便于 Excel 筛选。轮次间通过变化种子 + 温度 + 可选 CLI ``--theme-hint`` 要求**明显换一批联想**（有 theme-hint 时仍以单条定名母题为主轴）。
- 字段（UTF-8，稳定列顺序）：
  - `template_name`
  - `image_path`
  - `variation_seed`
  - `template_summary_zh`（该模板本轮总述，非 YAML 正文；每行重复便于筛选）
  - `candidate_index`（1 起）
  - `video_title_zh`（小红书短视频标题，**7～9 字**，结合母题与服装气质）
  - `fit_score`（1～10）
  - `fit_label`（很合适/较合适/一般/勉强）
  - `category`（英文标签）
  - `user_requirement_zh`（**粘贴即用**的主题需求正文）

## Stage3b（可选：卡通人偶线 · 真人 × 服装 × 发型选题）

- 输入：`resource/real_head_120k_selected/` 下人脸图（文件名或上级目录须含 **6 位** `real_head_id`）；候选服装来自 **`output/stage1_body_template_preview/*.png`**；候选发型来自 `resource/blender/solid_hair_preview/hair_style/*.png`（须先跑发型预览批处理）。
- 脚本：`stage3b_body_and_hair_template_theme_fit/analyze_body_hair_theme_fit.py`，`--run-subdir <NAME>` 必填。**每处理完一张真人图即追加写入 CSV**；`--resume` / `--overwrite` / `--auto-gen-yml` 行为同前版；`--auto-gen-yml` 默认 `PIPELINE_LINE=卡通人偶定制`。**服装纹理母题**的提示词主体与 Stage3a 共用 ``analyze_theme_fit.build_user_prompt``；Stage3b 仅增加真人脸、模板/发型列表、``hair_color`` 与 ``batch_summary_zh``（等同 Stage3a 的 ``summary_zh``）；模型输出经 Stage3a 等价校验 + 列表引用校验，失败则重试。
- 每张人脸：``--themes-per-face``（默认 **5**）控制 JSON ``candidates`` 行数即 CSV 行数；``--style-branches-per-theme``（默认 **1**）仅约束**单条** ``user_requirement_zh`` 内的并列短分句数。**``batch_summary_zh``** 为整脸一轮总述，**不应**写「与行数 N 逐项对齐的 N 大母题」清单（易与条内分支混淆）；总述只写受众与共性气质等。弃用 ``--candidate-count`` 时等同 ``--themes-per-face``。模型返回后若 ``len(candidates)`` 与 ``--themes-per-face`` 不一致则跳过该脸并报错。
- 输出：`output/stage3b_body_and_hair_template_theme_fit/<NAME>/stage3b_body_and_hair_template_theme_fit.csv`（**不按** `PIPELINE_LINE` 分目录）
- 字段（UTF-8，稳定列顺序）：`real_head_id`、`photo_path`、`body_template_name`、`hair_style_id`、**`hair_color`**（须为 `common.hair_assets.HAIR_COLORS` 的英文键，如 `medium_brown`）、`candidate_index`、`video_title_zh`、`fit_score`、`fit_label`、`category`、**`user_requirement_zh`**（整身服装纹理母题，写入 YAML `user_requirement`）、`variation_seed`、`batch_summary_zh`。旧 CSV 若仍含 `body_requirement_zh` / `hair_requirement_zh`，`--auto-gen-yml` 会尽量合并到 `user_requirement_zh`；未知 `hair_color` 回退 `black`。
- **与 Stage3a**：Stage3a 无真人脸、无发型 id，**不能**替代 Stage3b；人偶选题请用 Stage3b。
- 选题提示词要求：多组中**过半**依托可识别母题（风格化、非官方联名式表述），`video_title_zh` 尽量带梗；遵守禁忌组合与列表内模板/发型 id 约束；发色键须与 `HAIR_COLORS` 完全一致。

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

- **主题根目录渲染偏好**：`output/<PIPELINE_LINE>/stage4_10/<truncate(fashion_tag)>/pipeline_render_prefs.yml`。键包括 `body_templates`、`user_requirement`、弃用的可选 `body_requirement`（仅旧文件兼容）、`fashion_tag`、`studio_tint_hex`、`head_object`、`hair_object`、`hair_color`、可选 `hair_textured_glb` / `body_textured_glb` 等。**Stage4** 读取服装锚点时 **`user_requirement` 优先**；若旧 YAML 仅有 `body_requirement` 则回退之。Stage4 **必填 `--fashion-tag`**；`generate_fashion_prompts.py` 对每个列出的模板生成对应条数的 prompt（条数来自 YAML，不由代码常量写死）。
- **单套模板输出 CSV**：`output/<PIPELINE_LINE>/stage4_10/<truncate(fashion_tag)>/<template_name>/stage4_fashion_prompt.csv`
- 字段：
  - `template_name`
  - `user_requirement`
  - `fashion_tag`
  - `prompt_zh`
  - `prompt_abstract_zh`
  - `label_zh`
  - `label_en`
  - `reference_image`

## Stage5 -> Stage6

- 输入：同上路径下的 `stage4_fashion_prompt.csv`（`build_texture_prompts.py`：**`--fashion-tag`** 必填；若省略 **`--template`** 则按主题根 **`pipeline_render_prefs.yml`** 的 **`body_templates`** 顺序逐套处理，否则只跑指定模板）
- 输出 CSV：`output/<PIPELINE_LINE>/stage4_10/<truncate(fashion_tag)>/<template_name>/stage5_new_texture_prompt.csv`
- 字段：
  - `template_name`
  - `user_requirement`
  - `fashion_tag`
  - `label_zh`
  - `label_en`
  - `texture_prompt`
  - `full_prompt`

## Stage6 -> Stage7

- 输入：显式 **`--input-csv`**；或 **`--fashion-tag`** 与可选 **`--template`** 解析为单套 `…/stage5_new_texture_prompt.csv`；或仅 **`--fashion-tag`** 时按 prefs 中 **`body_templates`** 逐套处理（跳过尚无 stage5 CSV 的项并 WARN）
- 请求：每条 `full_prompt` 连续调用 Seedream `N` 次、每次 `n=1`（`N` 为 `--num-images`，默认 4）；在 `full_prompt` 前拼接简短风格约束（略卡通、少写实微肌理、贴近参考版型），再送 Seedream
- 输出：`output/<PIPELINE_LINE>/stage4_10/<truncate(fashion_tag)>/<template>/<label_zh>_<idx>.png`（目录为 `stage6_new_texture_generation/`）

## Stage7 -> Stage8

- 筛图目录（与阶段6 同 run）：`output/<PIPELINE_LINE>/stage4_10/<truncate(fashion_tag)>/<template>/stage7_new_texture_generation_selected/<label_zh>_<idx>.png`（源图来自同目录上级 `stage6_new_texture_generation/`）。人工流程：按组筛图后放入本目录供贴图。

## Stage8 -> Stage9

- 输出目录：`output/<PIPELINE_LINE>/stage4_10/<truncate(fashion_tag)>/<template>/stage8_new_texture_model_generation/`
- 每个风格至少一个 **`<label_zh>.glb`**：**默认**在混元 3D **网页**用积分生成后下载放入；**网页积分不足**时用 `generate_textured_models.py` 走 **API** 补跑。手工/网页流程可无 `_result` 等预览图
- 后续（封面/正片）输入：扫描 `**/stage8_new_texture_model_generation/*.glb`，与是否同目录存在 PNG 预览无关
- **说明**：`generate_textured_models.py` **不**设置 Blender 里 Studio 背景墙 Tint；该参数在 **Stage9/11** 的 `blender_render_videos.py` 中通过 `--studio-tint-hex` 或 `--random-studio-tint` 控制，预设见 `common/studio_render_constants.py`。主题根目录 **`pipeline_render_prefs.yml`** 可替代上述 CLI（见 Stage4 契约）。仅 **`--fashion-tag`** 时按 prefs 的 **`body_templates`** 逐套跑 API 贴图；**`--selected-dir`** 仅在与 **`--template`** 单套联用时有效。

## Stage9（仅封面，候选池）

- **Blender 工程**：`resource/blender/blender_render_videos.blend`。
- **渲染脚本**：`stage11_render_videos/blender_render_videos.py`（`--pass covers`）
- **输出**：`output/<PIPELINE_LINE>/stage4_10/<truncate(fashion_tag)>/<template>/stage9_render_covers/<label_zh>_cover.png`（第 18 帧，**不**再写 `cover.png`；将父目录 `stage8_new_texture_model_generation` 换为 `stage9_render_covers`）。
- **Studio 背景墙 Tint / 头模物体名**：传入 **`--fashion-tag`** 时在主题根同步 **`pipeline_render_prefs.yml`**；与 `--studio-tint-hex` / `--random-studio-tint`、头/发 CLI 合并规则同上。

## Stage10（手工筛封面）

- **目录**：`output/<PIPELINE_LINE>/stage4_10/<truncate(fashion_tag)>/<template>/stage10_render_covers_selected/`（从 `stage9_render_covers/` 复制所选 `<模型名>_cover.png`）

## Stage11（正片）

- **输出**：`output/<PIPELINE_LINE>/stage4_10/<truncate(fashion_tag)>/<template>/stage11_render_videos/<模型名>.mp4`

## Stage12（白模透明视频）

- **输出**：`output/<PIPELINE_LINE>/stage4_10/<truncate(fashion_tag)>/<template>/stage12_render_white_mesh_videos/white_model.mov`

## 卡通人偶线 · 头发（无独立纹理阶段）

- 主题根 YAML 的 **`hair_object`**（solid 子目录名）与 **`hair_color`**（`HAIR_COLORS` 键）由 **Stage3b** 或人工填写；**Stage9～12 / 12b** 使用 **`resource/blender/solid_hair/<hair_object>/low_poly/hair.obj`** + 发色渲染，**不再**维护 Stage4b～8b 目录或贴图头发 GLB 流水线。
- 可选 **`hair_textured_glb`**：若需显式使用自定义贴图头发 GLB，可在 YAML 中写相对路径（`{stem}` 占位）；未配置时 Stage11 使用 solid 发型。

## Stage12b（卡通人偶 · 身体 + solid 发型 + 真人头白模）

- **脚本**：`stage12b_body_head_hair_render_white_mesh_videos/blender_render_composite_white_mesh.py`，工程 **`resource/blender/render_around_white_mesh.blend`**。
- **输出**：`…/<body_template>/stage12b_body_head_hair_render_white_mesh_videos/<label_zh>/white_model.mov`（每套 Stage8 stem 子目录）。须存在对应身体 GLB；`pipeline_render_prefs.yml` 含 **数字** `head_object` 与 **`hair_object`**（solid 发型 id）。

**显式配对**：可在**身体模板 run 目录**放置 **`pipeline_body_hair_merge.csv`**（字段见 `common.pipeline_doll_merge.MERGE_FIELDNAMES`），便于记录 `body_textured_glb` / `hair_textured_glb` 与真人 id；`hair_textured_glb` 仅在为少数主题显式覆盖时使用。

## 目录约定（历史布局）

当前约定：`output/<PIPELINE_LINE>/stage4_10/<truncate(fashion_tag)>/<body_template>/`。旧式 `stage4_10/<template>/<segment>/` 或 **`output/stage4_10`** 顶层落盘已废弃；若仍有遗留树，请按当前层级手工整理（本仓库不再附带一次性迁移脚本）。
