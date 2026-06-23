# Stage 3a（可选：每模板默认 10 条 user_requirement_zh + 7～9 字 video_title_zh；须 --run-subdir；默认联网）

python stage3a_body_template_theme_fit/analyze_theme_fit.py --run-subdir 选题_示例命名
python stage3a_body_template_theme_fit/analyze_theme_fit.py --resume --run-subdir 选题_示例命名

# 从本 run 的 Stage3a CSV 为「很合适」行生成手办线主题根 YAML（不调用模型；默认 output/手办服装IP/stage4_10/）

python stage3a_body_template_theme_fit/analyze_theme_fit.py --run-subdir 选题_示例命名 --auto-gen-yml

# -----------------------------------------------------------------------------

# 卡通人偶定制（PIPELINE_LINE=卡通人偶定制；Stage3b 与 Stage1 预览均在 OUTPUT_ROOT 下不按产品线分子目录）

# -----------------------------------------------------------------------------

# 下列 `output/…` 默认相对仓库根，与 `common.settings` 的 `OUTPUT_ROOT` 一致；若 .env 改了输出根，请自行替换路径。

# --- Stage 3b：真人 × 服装预览 × 发型预览 → CSV（默认 --themes-per-face 5、--style-branches-per-theme 1）---

# 已有 CSV 时须 --resume 续跑或 --overwrite 删目录重跑；每张照片处理完即落盘

python stage3b_body_and_hair_template_theme_fit/analyze_body_hair_theme_fit.py --run-subdir 20260511
python stage3b_body_and_hair_template_theme_fit/analyze_body_hair_theme_fit.py --run-subdir 20260511 --resume
python stage3b_body_and_hair_template_theme_fit/analyze_body_hair_theme_fit.py --run-subdir 20260511 --overwrite
# 示例：每人脸 5 行选题，但每条 user_requirement_zh 内允许 2 个同母题短分句（非 5 个子主题）：
# python stage3b_body_and_hair_template_theme_fit/analyze_body_hair_theme_fit.py --run-subdir 20260511 --themes-per-face 5 --style-branches-per-theme 2

# --- 紧接着：从本 run 的 CSV 为所有「很合适」行生成 YAML（不调用模型）---

# 直接写入 `output/卡通人偶定制/stage4_10/<目录名>/pipeline_render_prefs.yml`；目录名与 YAML 内 `fashion_tag` 一致。

# 卡通人偶线默认 `prompt_count=1`（每主题仅扩展 1 条身体新纹理 prompt，与 Stage3b 已写细的母题一致）；若要手办式多扩展，加 `--pref-prompt-count 20` 等。

# 若需覆盖已生成的 YAML，加 `--overwrite-yml`；产品线目录可用 Stage3b 脚本的 `--pipeline-line` 改。

# 若你本机仍留有历史目录 `output/卡通人偶定制/stage4_12/`，可一次性迁到 `stage4_10`：`rsync -a output/卡通人偶定制/stage4_12/ output/卡通人偶定制/stage4_10/` 后自行删除空目录。

python stage3b_body_and_hair_template_theme_fit/analyze_body_hair_theme_fit.py --run-subdir 20260511 --auto-gen-yml
python stage3b_body_and_hair_template_theme_fit/analyze_body_hair_theme_fit.py --run-subdir 20260511 --auto-gen-yml --overwrite-yml

# --- 批量跑身体「新纹理」链路：Stage4 → Stage5 → Stage6（智能跳过 / 清理后补跑）---

# 对每个含 `pipeline_render_prefs.yml` 的**主题**子目录（`stage4_10/<目录名>/`，目录名即 `--fashion-tag`），脚本会：

# - **整主题身体 Stage6 已全部通过校验**（条数、`label_zh` 对应预览文件为可读 PNG 或 JPEG、最小字节数）→ **跳过**；

# - 否则按模板判断缺哪一段：只坏 Stage6 则删该模板 `stage6_new_texture_generation` 后只跑 Stage6（带 `--resume`）；Stage5 坏则删 5+6 再跑 5→6；Stage4 坏则删 4+5+6 再跑 4→5→6。

# Stage6 输出：`output/卡通人偶定制/stage4_10/<fashion-tag>/<body_template>/stage6_new_texture_generation/*.png`。

# 在**仓库根**执行（需已 `conda activate antiversestudio`）：

```bash
python scripts/batch_doll_texture_stages.py --mode body --pipeline 卡通人偶定制
```

# 省 Stage4 Token：`python scripts/batch_doll_texture_stages.py --mode body --pipeline 卡通人偶定制 --stage4-disable-search`

# 只处理一个主题：`python scripts/batch_doll_texture_stages.py --mode body --pipeline 卡通人偶定制 --fashion-tag 520甜蜜约会装_000463`（`--only-tag` 同义）

# 先看将执行的命令与清理动作：`python scripts/batch_doll_texture_stages.py --mode body --pipeline 卡通人偶定制 --dry-run`

# 已完整主题也强制删 stage4/5/6 后重跑：`python scripts/batch_doll_texture_stages.py --mode body --pipeline 卡通人偶定制 --overwrite`

# 单条主题手工跑（不经过批处理脚本；Stage6 建议加 `--resume` 续跑）：

# export PIPELINE_LINE=卡通人偶定制

# python stage4_fashion_prompt/generate_fashion_prompts.py --fashion-tag "520甜蜜约会装_000463"

# python stage5_new_texture_prompt/build_texture_prompts.py --fashion-tag "520甜蜜约会装_000463"

# python stage6_new_texture_generation/generate_seedream_images.py --fashion-tag "520甜蜜约会装_000463" --num-images 4 --resume

# --- 头发「新纹理」预览：Stage4b → Stage5b → Stage6b（与身体共用同一主题根、同一 `--fashion-tag`）---

# 依赖：主题根 `pipeline_render_prefs.yml` 已写 `hair_object`（solid 发型 id，与 Stage3b/auto-gen 一致）；且存在 `resource/blender/solid_hair_preview/hair_style/<hair_object>.png`（无则先跑下文 **Stage 1 发型预览**）。

# 输出写在 `**<主题>/<YAML hair_object 截断>/`** 下（与身体模板目录平级，不按 body 复制）：`stage4b_hair_fashion_prompt.csv` → `stage5b_hair_new_texture_prompt.csv` → `stage6b_hair_new_texture_generation/<label_zh>_<1..N>.png`。Stage6b 默认每条 prompt 出 4 张，可用 `--num-images` 改；断点续跑加 `--resume`。Stage4b 省 Token 可在命令末尾加 `--disable-search`。

# 可选 `--hair-style-id`（4b/5b/6b/8b）：覆盖 YAML 中的 `hair_object` 作为子目录名；Stage8b 仍支持旧参数 `--template` 作为 `--hair-style-id` 别名。

# 在**仓库根**执行；**批量**请用与身体相同的批处理脚本（`--mode hair`），按 YAML `hair_object`（或 `--hair-style-id`）定位发型子目录，整主题 Stage6b 已齐则跳过，否则按 4b/5b/6b 逐级删产物后补跑；Stage6b 带 `--resume`，避免已齐 PNG 重复请求。

```bash
python scripts/batch_doll_texture_stages.py --mode hair --pipeline 卡通人偶定制
```

# 省 Stage4b Token：`python scripts/batch_doll_texture_stages.py --mode hair --pipeline 卡通人偶定制 --stage4-disable-search`

# 已完整主题也强制删 stage4b/5b/6b 后重跑：`python scripts/batch_doll_texture_stages.py --mode hair --pipeline 卡通人偶定制 --overwrite`

# 单主题（示例；头发目录由 YAML `hair_object` 决定，一般为 `output/卡通人偶定制/stage4_10/<tag>/<hair_object>/`）：

# export PIPELINE_LINE=卡通人偶定制

# python stage4b_hair_prompt/generate_hair_fashion_prompts.py --fashion-tag "北欧童话小雪人_001115"

# python stage5b_hair_new_texture_prompt/build_hair_texture_prompts.py --fashion-tag "北欧童话小雪人_001115"

# python stage6b_hair_new_texture_generation/generate_seedream_hair_images.py --fashion-tag "北欧童话小雪人_001115" --num-images 4 --resume

# 若子目录名与 YAML 不一致：各脚本加 `--hair-style-id <solid子目录名>`

# Stage 1 发型预览（仅发型几何 PNG，供 Stage3b）

# blender -b --python-use-system-env resource/blender/body_template_preview.blend \

# -P stage1_hair_style_preview/render_hair_style_previews.py --

# Stage 7～12（卡通人偶线）：与下手办服装 IP 一节相同，全程 `export PIPELINE_LINE=卡通人偶定制`，`--fashion-tag` 仍用目录 basename。身体新纹理见上 Stage4～6；头发新纹理预览见上 **Stage4b～6b**（再筛图/贴图见 `docs/stage_data_contract.md` 中 Stage7b～8b）。

# ------------------------------s-----------------------------------------------

# 手办服装 IP（PIPELINE_LINE=手办服装IP 或默认；以下为原 Stage4～12 示例）

# -----------------------------------------------------------------------------

# Stage 4（模板列表来自 `output/<PIPELINE_LINE>/stage4_10/<fashion-tag截断>/pipeline_render_prefs.yml` 的 `body_templates`；

# 可加 `--template body_xxx` 只跑其中一套。

# DashScope 默认开启联网搜索（`extra_body.enable_search`）；若需省 Token 可加 `--disable-search`。

python stage4_fashion_prompt/generate_fashion_prompts.py  
  --fashion-tag "哈利波特毕业袍"

python stage4_fashion_prompt/generate_fashion_prompts.py  
  --fashion-tag "狂欢节足球派对"

python stage4_fashion_prompt/generate_fashion_prompts.py  
  --fashion-tag "热血动漫赛车服"

python stage4_fashion_prompt/generate_fashion_prompts.py  
  --fashion-tag "万圣节僵尸医师"

# Stage 5（按主题根 pipeline_render_prefs.yml 的 body_templates 顺序遍历；也可用 --template 只跑一套）

python stage5_new_texture_prompt/build_texture_prompts.py  
  --fashion-tag "哈利波特毕业袍"

python stage5_new_texture_prompt/build_texture_prompts.py  
  --fashion-tag "狂欢节足球派对"

python stage5_new_texture_prompt/build_texture_prompts.py  
  --fashion-tag "热血动漫赛车服"

python stage5_new_texture_prompt/build_texture_prompts.py  
  --fashion-tag "万圣节僵尸医师"

# Stage 6（同上；仅 --fashion-tag 时跳过尚无 stage5 CSV 的模板并打印 WARN）

python stage6_new_texture_generation/generate_seedream_images.py  
  --fashion-tag "哈利波特毕业袍"

python stage6_new_texture_generation/generate_seedream_images.py  
  --fashion-tag "狂欢节足球派对"

python stage6_new_texture_generation/generate_seedream_images.py  
  --fashion-tag "热血动漫赛车服"

python stage6_new_texture_generation/generate_seedream_images.py  
  --fashion-tag "万圣节僵尸医师"

# Stage 8（API 贴图备选；批量遍历时勿使用 --selected-dir，每套用各自 stage7 筛图目录）

# 批量：``output/<产品线>/stage4_10`` 下所有含 pipeline_render_prefs.yml 的主题（须显式产品线）

python scripts/batch_doll_stage8_textured_models.py --pipeline 卡通人偶定制

# 单主题（与阶段4～7一致须带 ``--pipeline-line``，避免路径落到默认产品线）

python stage8_new_texture_model_generation/generate_textured_models.py  
  --fashion-tag "哈利波特毕业袍" --pipeline-line 卡通人偶定制

python stage8_new_texture_model_generation/generate_textured_models.py  
  --fashion-tag "狂欢节足球派对" --pipeline-line 卡通人偶定制

python stage8_new_texture_model_generation/generate_textured_models.py  
  --fashion-tag "热血动漫赛车服" --pipeline-line 卡通人偶定制

python stage8_new_texture_model_generation/generate_textured_models.py  
  --fashion-tag "万圣节僵尸医师" --pipeline-line 卡通人偶定制

# Stage 9（多终端共享池：默认最多 7 槽「权重」；可调 BLENDER_POOL_MAX）

# 批量 Stage9 封面（内部为 ``--pass covers``；默认每主题顺序、``--theme-workers`` 可并行多主题）

python scripts/batch_doll_stage9_covers.py --pipeline 卡通人偶定制

# 与 ``python scripts/batch_doll_blender_stage9_11.py --pass covers --pipeline …`` 等价

# Stage11：blender_render_pool 外层每任务槽权重恒为 1；多 --workers 时渲片并发由 common/blender_render_pool_lease（sqlite 租约）限制在 BLENDER_POOL_MAX

# 状态与 ETA 粗估在 var/blender_render_pool/<BLENDER_POOL_NAME|default>/state.sqlite

# 无历史时 ETA 用 BLENDER_POOL_EST_SECONDS_COVERS 等环境变量（见 scripts/blender_render_pool.py 文档字符串）

# 池子日志：默认 BLENDER_POOL_LOG=minimal（起止打印完整可复跑指令+run_id，中间 ETA 至多每 120s）；quiet=仅起止；full=恢复频繁 ETA

python scripts/blender_render_pool.py -- blender -b --python-use-system-env resource/blender/blender_render_videos.blend \
  -P stage11_render_videos/blender_render_videos.py -- \
  --pass covers \
  --fashion-tag "哈利波特毕业袍"

# 单主题时须保证 shell 中 ``PIPELINE_LINE``（或 dotenv）与主题所在产品线一致，与批量脚本的 ``--pipeline`` 相同。

python scripts/blender_render_pool.py -- blender -b --python-use-system-env resource/blender/blender_render_videos.blend  
  -P stage11_render_videos/blender_render_videos.py --  
  --pass covers  
  --fashion-tag "狂欢节足球派对"

python scripts/blender_render_pool.py -- blender -b --python-use-system-env resource/blender/blender_render_videos.blend  
  -P stage11_render_videos/blender_render_videos.py --  
  --pass covers  
  --fashion-tag "热血动漫赛车服"

python scripts/blender_render_pool.py -- blender -b --python-use-system-env resource/blender/blender_render_videos.blend  
  -P stage11_render_videos/blender_render_videos.py --  
  --pass covers  
  --fashion-tag "万圣节僵尸医师"

# Stage 11（同上；BLENDER_WORKERS 供子进程读；外层池每任务 1 槽，渲片并发见 blender_render_pool_lease）

# 批量 Stage11 视频（默认整批 ``--theme-workers 6``、每主题 ``--inner-workers 1``；可调；``--studio-tint-hex`` 建议与单主题一致）

python scripts/batch_doll_stage11_videos.py --pipeline 卡通人偶定制 --studio-tint-hex '#E3D9C6'

# 与 ``python scripts/batch_doll_blender_stage9_11.py --pass videos --pipeline …`` 等价

BLENDER_WORKERS=6 python scripts/blender_render_pool.py -- blender -b --python-use-system-env resource/blender/blender_render_videos.blend  
  -P stage11_render_videos/blender_render_videos.py --  
  --pass videos  
  --fashion-tag "哈利波特毕业袍"  
  --workers 6

BLENDER_WORKERS=6 python scripts/blender_render_pool.py -- blender -b --python-use-system-env resource/blender/blender_render_videos.blend  
  -P stage11_render_videos/blender_render_videos.py --  
  --pass videos  
  --fashion-tag "狂欢节足球派对"  
  --workers 6

BLENDER_WORKERS=6 python scripts/blender_render_pool.py -- blender -b --python-use-system-env resource/blender/blender_render_videos.blend  
  -P stage11_render_videos/blender_render_videos.py --  
  --pass videos  
  --fashion-tag "热血动漫赛车服"  
  --workers 6

BLENDER_WORKERS=6 python scripts/blender_render_pool.py -- blender -b --python-use-system-env resource/blender/blender_render_videos.blend  
  -P stage11_render_videos/blender_render_videos.py --  
  --pass videos  
  --fashion-tag "万圣节僵尸医师"  
  --workers 6

BLENDER_WORKERS=1 python scripts/blender_render_pool.py -- blender -b --python-use-system-env resource/blender/blender_render_videos.blend \
  -P stage11_render_videos/blender_render_videos.py -- \
  --pass videos \
  --fashion-tag "霍格沃茨毕业照_004361" \
  --workers 1

# Stage 12（与 Stage 9 / 11 共用同一并发池；`--pass white_mesh` 仅占位供池子 ETA 分桶，Stage12 脚本不依赖其语义）

python scripts/blender_render_pool.py -- blender -b --python-use-system-env resource/blender/render_around_white_mesh.blend  
  -P stage12_render_white_mesh_videos/blender_render_white_mesh_videos.py --  
  --pass white_mesh  
  --fashion-tag "哈利波特毕业袍"

python scripts/blender_render_pool.py -- blender -b --python-use-system-env resource/blender/render_around_white_mesh.blend  
  -P stage12_render_white_mesh_videos/blender_render_white_mesh_videos.py --  
  --pass white_mesh  
  --fashion-tag "狂欢节足球派对"

python scripts/blender_render_pool.py -- blender -b --python-use-system-env resource/blender/render_around_white_mesh.blend  
  -P stage12_render_white_mesh_videos/blender_render_white_mesh_videos.py --  
  --pass white_mesh  
  --fashion-tag "热血动漫赛车服"

python scripts/blender_render_pool.py -- blender -b --python-use-system-env resource/blender/render_around_white_mesh.blend  
  -P stage12_render_white_mesh_videos/blender_render_white_mesh_videos.py --  
  --pass white_mesh  
  --fashion-tag "万圣节僵尸医师"