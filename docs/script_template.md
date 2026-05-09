# Stage 4
python stage4_fashion_prompt/generate_fashion_prompts.py \
--template "body_08_lover_520" \
--fashion-tag "赛博月老强制锁死260508"

python stage4_fashion_prompt/generate_fashion_prompts.py \
--template "body_31_casual_retro" \
--fashion-tag "复仇者联盟主题260508"

python stage4_fashion_prompt/generate_fashion_prompts.py \
--template "body_65" \
--fashion-tag "中国博物馆主题260508"

python stage4_fashion_prompt/generate_fashion_prompts.py \
--template "body_80_female" \
--fashion-tag "随机掉落全场最高亮260508"

# Stage 5
python stage5_new_texture_prompt/build_texture_prompts.py \
  --template "body_08_lover_520" \
  --fashion-tag "赛博月老强制锁死260508"

python stage5_new_texture_prompt/build_texture_prompts.py \
  --template "body_31_casual_retro" \
  --fashion-tag "复仇者联盟主题260508"

python stage5_new_texture_prompt/build_texture_prompts.py \
  --template "body_65" \
  --fashion-tag "中国博物馆主题260508"

python stage5_new_texture_prompt/build_texture_prompts.py \
  --template "body_80_female" \
  --fashion-tag "随机掉落全场最高亮260508"

# Stage 6
python stage6_new_texture_generation/generate_seedream_images.py \
  --template "body_08_lover_520" \
  --fashion-tag "赛博月老强制锁死260508"

python stage6_new_texture_generation/generate_seedream_images.py \
  --template "body_31_casual_retro" \
  --fashion-tag "复仇者联盟主题260508"

python stage6_new_texture_generation/generate_seedream_images.py \
  --template "body_65" \
  --fashion-tag "中国博物馆主题260508"

python stage6_new_texture_generation/generate_seedream_images.py \
  --template "body_80_female" \
  --fashion-tag "随机掉落全场最高亮260508"

# Stage 8
python stage8_new_texture_model_generation/generate_textured_models.py \
  --template "body_08_lover_520" \
  --fashion-tag "赛博月老强制锁死260508"

python stage8_new_texture_model_generation/generate_textured_models.py \
  --template "body_31_casual_retro" \
  --fashion-tag "复仇者联盟主题260508"

python stage8_new_texture_model_generation/generate_textured_models.py \
  --template "body_65" \
  --fashion-tag "中国博物馆主题260508"

python stage8_new_texture_model_generation/generate_textured_models.py \
  --template "body_80_female" \
  --fashion-tag "随机掉落全场最高亮260508"

# Stage 9（多终端共享池：默认最多 7 槽「权重」；可调 BLENDER_POOL_MAX）
# Stage11：blender_render_pool 外层每任务槽权重恒为 1；多 --workers 时渲片并发由 common/blender_render_pool_lease（sqlite 租约）限制在 BLENDER_POOL_MAX
# 状态与 ETA 粗估在 var/blender_render_pool/<BLENDER_POOL_NAME|default>/state.sqlite
# 无历史时 ETA 用 BLENDER_POOL_EST_SECONDS_COVERS 等环境变量（见 scripts/blender_render_pool.py 文档字符串）
# 池子日志：默认 BLENDER_POOL_LOG=minimal（起止打印完整可复跑指令+run_id，中间 ETA 至多每 120s）；quiet=仅起止；full=恢复频繁 ETA
python scripts/blender_render_pool.py -- blender -b --python-use-system-env resource/blender/blender_render_videos.blend \
  -P stage11_render_videos/blender_render_videos.py -- \
  --pass covers \
  --template "body_08_lover_520" \
  --fashion-tag "赛博月老强制锁死260508"

python scripts/blender_render_pool.py -- blender -b --python-use-system-env resource/blender/blender_render_videos.blend \
  -P stage11_render_videos/blender_render_videos.py -- \
  --pass covers \
  --template "body_31_casual_retro" \
  --fashion-tag "复仇者联盟主题260508"

python scripts/blender_render_pool.py -- blender -b --python-use-system-env resource/blender/blender_render_videos.blend \
  -P stage11_render_videos/blender_render_videos.py -- \
  --pass covers \
  --template "body_65" \
  --fashion-tag "中国博物馆主题260508"

python scripts/blender_render_pool.py -- blender -b --python-use-system-env resource/blender/blender_render_videos.blend \
  -P stage11_render_videos/blender_render_videos.py -- \
  --pass covers \
  --template "body_80_female" \
  --fashion-tag "随机掉落全场最高亮260508"

# Stage 11（同上；BLENDER_WORKERS 供子进程读；外层池每任务 1 槽，渲片并发见 blender_render_pool_lease）
BLENDER_WORKERS=6 python scripts/blender_render_pool.py -- blender -b --python-use-system-env resource/blender/blender_render_videos.blend \
  -P stage11_render_videos/blender_render_videos.py -- \
  --pass videos \
  --template "body_08_lover_520" \
  --fashion-tag "赛博月老强制锁死260508" \
  --workers 6

BLENDER_WORKERS=6 python scripts/blender_render_pool.py -- blender -b --python-use-system-env resource/blender/blender_render_videos.blend \
  -P stage11_render_videos/blender_render_videos.py -- \
  --pass videos \
  --template "body_31_casual_retro" \
  --fashion-tag "复仇者联盟主题260508" \
  --workers 6

BLENDER_WORKERS=6 python scripts/blender_render_pool.py -- blender -b --python-use-system-env resource/blender/blender_render_videos.blend \
  -P stage11_render_videos/blender_render_videos.py -- \
  --pass videos \
  --template "body_65" \
  --fashion-tag "中国博物馆主题260508" \
  --workers 6

BLENDER_WORKERS=6 python scripts/blender_render_pool.py -- blender -b --python-use-system-env resource/blender/blender_render_videos.blend \
  -P stage11_render_videos/blender_render_videos.py -- \
  --pass videos \
  --template "body_80_female" \
  --fashion-tag "随机掉落全场最高亮260508" \
  --workers 6

# Stage 12（与 Stage 9 / 11 共用同一并发池；`--pass white_mesh` 仅占位供池子 ETA 分桶，Stage12 脚本不依赖其语义）
python scripts/blender_render_pool.py -- blender -b --python-use-system-env resource/blender/render_around_white_mesh.blend \
  -P stage12_render_white_mesh_videos/blender_render_white_mesh_videos.py -- \
  --pass white_mesh \
  --template "body_08_lover_520" \
  --fashion-tag "赛博月老强制锁死260508"

python scripts/blender_render_pool.py -- blender -b --python-use-system-env resource/blender/render_around_white_mesh.blend \
  -P stage12_render_white_mesh_videos/blender_render_white_mesh_videos.py -- \
  --pass white_mesh \
  --template "body_31_casual_retro" \
  --fashion-tag "复仇者联盟主题260508"

python scripts/blender_render_pool.py -- blender -b --python-use-system-env resource/blender/render_around_white_mesh.blend \
  -P stage12_render_white_mesh_videos/blender_render_white_mesh_videos.py -- \
  --pass white_mesh \
  --template "body_65" \
  --fashion-tag "中国博物馆主题260508"

python scripts/blender_render_pool.py -- blender -b --python-use-system-env resource/blender/render_around_white_mesh.blend \
  -P stage12_render_white_mesh_videos/blender_render_white_mesh_videos.py -- \
  --pass white_mesh \
  --template "body_80_female" \
  --fashion-tag "随机掉落全场最高亮260508"