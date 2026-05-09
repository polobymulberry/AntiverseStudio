# FigShion3D Pipeline (Python 3.12 + Blender 4.2 LTS)

本仓库按 **Stage1～Stage12**（及若干手工/分支子步骤）组织 3D 卡通服装纹理生成流水线，目录拆分遵循：

- 每个步骤一个独立目录；
- 公共逻辑仅放在 `common/`；
- 全局模板路径配置在 `common/settings.py`。

## 1. 环境要求

- Python: `3.12`（推荐用 **conda** 创建独立环境；Blender 仍按下方单独安装，与 conda 无关）
- Blender: `4.2 LTS`（snap 安装）
  - `sudo snap install blender --channel=4.2lts/stable --classic`

安装 Python 依赖（conda 环境 + pip 安装 `requirements.txt`，与项目约定一致）：

```bash
conda create -n figshion3d python=3.12 -y
conda activate figshion3d
cd /path/to/FigShion3D
pip install -r requirements.txt
cp .env.example .env
```

可选：若你习惯用 `conda-forge`，可将第一行改为  
`conda create -n figshion3d python=3.12 -c conda-forge -y`。

### 在 Blender 自带 Python 中安装 `python-dotenv`

`common/settings.py` 会 `import dotenv`。**conda 里**已通过 `requirements.txt` 安装；**Blender 内嵌 Python 是另一套环境**，需要单独装一次，否则运行 `blender -b ... -P ...` 会报 `ModuleNotFoundError: No module named 'dotenv'`。

1. **查出 Blender 使用的 Python 可执行文件**（路径随安装方式 / 版本变化，以本机输出为准）：

```bash
blender -b --python-expr "import sys; print(sys.executable)" 2>/dev/null | head -1
```

snap 安装的 Blender 4.2 LTS 常见类似：`/snap/blender/<修订号>/4.2/python/bin/python3.11`（小版本号以实际为准）。

2. **用该解释器安装**（snap 下系统目录通常不可写，`pip` 会落到用户目录，见下一步）：

```bash
BLENDER_PY="$(blender -b --python-expr "import sys; print(sys.executable)" 2>/dev/null | head -1)"
"$BLENDER_PY" -m pip install --user --upgrade python-dotenv
```

3. **让 Blender 加载用户级 site-packages**：使用 `pip install --user` 时，需在 `blender -b` 中加 **`--python-use-system-env`**，否则 Blender 可能找不到已安装的包。

下文所有 `blender -b ... -P ...` 示例均已加上该参数；若你改为「可写目录下的非 `--user` 安装」，可视情况去掉。

### 在 Blender 自带 Python 中安装 `oss2`（Stage3）

`stage3_body_template_decimate/blender_decimate_and_upload.py` 会 `import oss2`。与 `python-dotenv` 相同，须装进 **Blender 内嵌解释器**，否则报 `ModuleNotFoundError: No module named 'oss2'`：

```bash
BLENDER_PY="$(blender -b --python-expr "import sys; print(sys.executable)" 2>/dev/null | head -1)"
"$BLENDER_PY" -m pip install --user oss2
```

同样需要 `blender -b` 加 **`--python-use-system-env`**（与上文一致）。

### 在 Blender 自带 Python 中安装 `PyYAML`（Stage9 / Stage11）

`common/pipeline_render_prefs.py` 会 `import yaml`（包名为 **PyYAML**，`pip` 里写 **`pyyaml`**）。**conda 里**已通过 `requirements.txt` 安装；**Blender 内嵌 Python 不会自动带上该包**，否则运行 `blender_render_videos.py`（封面 / 正片）会报 `ModuleNotFoundError: No module named 'yaml'`。

安装方式与 **`python-dotenv`** 相同，仍用 Blender 自带的解释器执行 **`pip install --user`**：

```bash
BLENDER_PY="$(blender -b --python-expr "import sys; print(sys.executable)" 2>/dev/null | head -1)"
"$BLENDER_PY" -m pip install --user pyyaml
```

同样需要 `blender -b` 加 **`--python-use-system-env`**（与上文一致）。

## 2. 目录结构

```text
common/
stage1_body_template_preview/
stage2_body_template_description/
stage3_body_template_decimate/
stage4_fashion_prompt/
stage5_new_texture_prompt/
stage6_new_texture_generation/
stage7_new_texture_generation_selected/   # 筛图目录名（实际路径见 Stage7：在每 run 的 output/stage4_10/…/ 下）
stage8_new_texture_model_generation/
stage9_render_covers/                    # 说明：同 README Stage9
stage10_render_covers_selected/         # 手工从 Stage9 封面中挑选
stage11_render_videos/                  # Blender 脚本与 Stage11 正片输出
stage12_render_white_mesh_videos/
output/
resource/blender/   # 含 blender_render_videos.blend、render_around_white_mesh.blend、body_template_preview.blend、castel_st_angelo_roof_4k.exr
```

## 3. 关键配置

所有配置集中在 `.env` + `common/settings.py`：

- 模板根目录：`BODY_TEMPLATE_ROOT`（默认 `/mnt/jfs_tikv/panjianxiong/drdoll/data/solid_full_body`）
- Qwen：`DASHSCOPE_API_KEY` / `DASHSCOPE_MODEL=qwen3.6-plus`
- Seedream：`SEEDREAM_API_KEY` / `SEEDREAM_MODEL=doubao-seedream-5-0-260128`
- OSS：`OSS_*`
- 腾讯混元 3D：`TENCENTCLOUD_SECRET_ID` / `TENCENTCLOUD_SECRET_KEY`

> 安全建议：不要把真实密钥提交到 Git。

## 4. 各阶段运行

以下 `blender -b --python-use-system-env ... -P ...` 命令请在 **仓库根目录**（本 README 所在目录）下执行；脚本会把该目录加入 Blender 内嵌 Python 的 `sys.path`，从而正确导入 `common`。请先完成上文 **Blender 自带 Python** 中的 **`python-dotenv`**（通用）、**`oss2`**（Stage3）与 **`pyyaml`**（Stage9 / Stage11，`pipeline_render_prefs.yml`）安装。

Stage3 依赖 `oss2`，须按上文 **「在 Blender 自带 Python 中安装 `oss2`」** 安装；不要只在 conda 里装。Stage9 / Stage11 依赖 **`pyyaml`**，同样须装进 Blender 解释器，不要只在 conda 里装。

各 `python stage*/…py` 脚本会在启动时把**仓库根目录**加入 `sys.path`，因此在仓库根执行 `python stage2_…/generate_descriptions.py` 等命令即可找到 `common`，无需再设 `PYTHONPATH`。

### Stage1 服装模板预览图渲染

输出：`output/stage1_body_template_preview/<模板名>.png`

```bash
blender -b --python-use-system-env resource/blender/body_template_preview.blend \
  -P stage1_body_template_preview/blender_template_preview.py
```

渲染失败或输出 PNG 异常（过小）时会自动重试并打印 `[WARN]`；结束后列出 `[FAIL]` 及原因。可选参数（写在 `--` 之后）：`--max-attempts N`（默认 3）、`--min-output-bytes B`（默认 1024）、`--resume`（已有有效 PNG 则跳过，便于补跑）。若统计为「有效输出少于模板目录数」，常见原因包括：缺少 `high_poly/body.obj`、导入后无 `body` 根物体、GPU/显存或 Cycles 报错、输出文件过小被判无效。

可选：仅检查每个模板在导入 `high_poly/body.obj` 后，场景中是否存在**根物体名**为 `body`（与后续贴图、Blender 渲染脚本约定一致）；**不渲染**，有任一失败则退出码为 1：

```bash
blender -b --python-use-system-env resource/blender/body_template_preview.blend \
  -P stage1_body_template_preview/blender_template_preview.py -- --check-prerequisite
```

可选：若大量模板的 `high_poly/body.obj` 在 Wavefront 里使用了非 `body` 的 `o` 物体名、或存在多个 `o` 导致 Blender 里根物体不叫 `body`，在 **`conda activate figshion3d`** 下运行修复脚本（与 `.cursorrules` 一致；通过 `common.settings` 读取 `.env` / `BODY_TEMPLATE_ROOT`，依赖环境中的 `python-dotenv`）。脚本会把**首条** `o` 改为 `o body`，并**删除后续多余的 `o` 行**（将面合并进同一物体）；同时**删除所有 `g ...` 组行**（如 `g ZBrushPolyMesh3D`）。写回前默认生成 `body.obj.bak`：

```bash
conda activate figshion3d
cd /path/to/FigShion3D
python stage1_body_template_preview/fix_obj_object_name_to_body.py --dry-run   # 先看改动说明
python stage1_body_template_preview/fix_obj_object_name_to_body.py             # 实际写回
```

参数：`--template-root <路径>` 覆盖默认模板根；`--no-backup` 不写备份。

### Stage2 模板介绍文案生成（Qwen）

输出：`output/stage2_body_template_description.csv`

```bash
python stage2_body_template_description/generate_descriptions.py
```

### Stage3 模型减面 + 上传 OSS

输出：
- `output/stage3_body_template_decimate/<模板名>/body.obj`
- `output/stage3_body_template_decimate.csv`（含 `faces_before` / `faces_after`：减面前、后网格多边形总数，与 Blender 统计口径一致）

减面策略（`blender_decimate_and_upload.py`）：按导入后多边形总数算 `40万 / 面数`，**向下取一位小数**为 Collapse 的初始 `ratio`（例如 120 万面 → 0.3）；若减面后仍 **≥ 50 万面**，则将 `ratio` 每次减 `0.1` 并重新导入再减，直至**小于 50 万面**或 `ratio` 已达下限 `0.01`（此时打印 `[WARN]` 仍导出）。

```bash
blender -b --python-use-system-env -P stage3_body_template_decimate/blender_decimate_and_upload.py
```

减面或上传中途失败时，单条会打印 `[FAIL]` 并继续；CSV **仅在减面导出且 OSS 上传均成功后**写入该行并 `flush`。断点续跑（`--resume`）只跳过「本地 `body.obj` 有效且 CSV 中该行的 `oss_key` / `public_url` 完整」的模板；仅有本地 obj 或上传失败留下的不完整行会重跑：

```bash
blender -b --python-use-system-env -P stage3_body_template_decimate/blender_decimate_and_upload.py -- --resume
```

**必须**在 `-P …/blender_decimate_and_upload.py` 之后写 **` -- `**（空格、双减号、空格），再写 `--resume`。若写成 `-P …py --resume` 而漏掉 ` -- `，脚本可能跑完，但 Blender 结束后会把 `--resume` 当成要打开的 `.blend` 路径，出现 `unknown argument, loading as file: --resume`。

### Stage4 纹理 / 主题图案 Prompt 生成（单模板，每次 20 条）

须用 **`--template`** 指定一个服装模板名（与 `BODY_TEMPLATE_ROOT` 下子目录名、以及 `output/stage2_body_template_description.csv` 里的 `template_name` 一致）。**仅**为该模板调用大模型生成 **20** 条 prompt（条数见 `stage4_fashion_prompt/generate_fashion_prompts.py` 中 `PROMPT_COUNT`）；若名称不在阶段2 CSV 已有记录中，脚本会打印 `[ERROR]`、列出已有 `template_name` 并以非零退出码结束，请改正后重跑。

输出路径（每个模板 × 每个需求一份 CSV；固定子目录 **`stage4_10`**，见 `common.utils.PIPELINE_TEMPLATE_USER_SUBDIR`；需求目录名由 `truncate_for_path` 截断）：

`output/stage4_10/<template_name>/<需求截断>/stage4_fashion_prompt.csv`

同目录下 **`pipeline_render_prefs.yml`** 在 Stage4 **启动时**即同步：无则建、有则按规则合并（随机 Tint、默认头/发，可手改）。Stage9/11 在相同 **`--template`** / **`--user-requirement`** 下**启动时**也会再次同步该文件；命令行传入的 Tint/头/发会**覆盖并写回** YAML（命令行优先）。

```bash
python stage4_fashion_prompt/generate_fashion_prompts.py \
  --template "body_24_overall_set" \
  --user-requirement "2026年服装纹理趋势"
```

### Stage5 组合最终图像生成 Prompt

输出：`output/stage4_10/<template_name>/<需求截断>/stage5_new_texture_prompt.csv`（与阶段4 同目录，读同目录下的 `stage4_fashion_prompt.csv`）

阶段5 也要传 **`--user-requirement`**，是因为子目录名由 `common.utils.truncate_for_path(需求全文)` 生成，脚本必须用与**阶段4 完全相同**的那句需求字符串才能拼出同一路径；同一模板下往往会有**多个**需求子目录，仅凭 `--template` 无法唯一对应到某一个 `stage4_fashion_prompt.csv`。

```bash
python stage5_new_texture_prompt/build_texture_prompts.py \
  --template "body_24_overall_set" \
  --user-requirement "2026年服装纹理趋势"
```

### Stage6 Seedream 出图（每条默认 4 张）

对每条 CSV 的 `full_prompt` **不做前缀拼接**；对 Seedream **连续请求 N 次**，每次 **`n=1`**，累计保存 N 张图（默认 `N=4`，可用 `--num-images` 修改）。当前为 **20 条 prompt × 4 张 = 80 张候选**；后续人工在阶段7 **每组 4 张留 1 张**得 20 张，再收窄为 **10 张**进贴图与后续渲染。

输出：`output/stage4_10/<模板名>/<需求截断>/stage6_new_texture_generation/<中文风格>_1~N.png`

```bash
python stage6_new_texture_generation/generate_seedream_images.py \
  --template "body_24_overall_set" \
  --user-requirement "2026年服装纹理趋势"
```

也可显式传入阶段5 CSV：`--input-csv output/stage4_10/<模板>/<需求截断>/stage5_new_texture_prompt.csv`。

### Stage7 人工筛图（手工）

从对应 `output/stage4_10/<模板>/<需求截断>/stage6_new_texture_generation/` 中：先对 **20 组**（每组对应同一 `label_zh` 的 `_1`～`_4`）**每组保留 1 张**（共 **20** 张），再从中选出 **10 张** 放入**同一 run 目录**下的筛图文件夹（与阶段6 输出并列），供阶段8 贴图：

`output/stage4_10/<模板>/<需求截断>/stage7_new_texture_generation_selected/`

### Stage8 混元 3D 贴图模型生成

产物目录（与阶段6、7 同一 run）：

`output/stage4_10/<模板名>/<需求截断>/stage8_new_texture_model_generation/`

**默认推荐**：在混元 3D **网页控制台**用积分完成纹理生成，再把 **`.glb`** 放进上述目录（见下方「方式 A」）。**仅当网页积分不够**、或仍需批量补跑时，再使用「方式 B」脚本走 **腾讯云 API**（按云侧计费，与网页积分无关）。两种方式可混用（部分风格网页、部分 API）。后续封面与正片渲染**只**依赖该目录下的 **`*.glb`**，**不依赖** `_result.png` 等贴图预览文件。

#### 方式 A（默认）：网页手工贴图并下载

1. 在官方网页用积分完成纹理生成，将得到的 **`.glb`** 下载到本机。
2. 放入对应 run 的 **`stage8_new_texture_model_generation/`** 目录。
3. **文件名**建议与阶段7 筛图的中文 label 一致，便于对照后续阶段：`<中文风格>.glb`（例如 `灌篮高手.glb`）。若下载文件名不同，**重命名**即可。
4. 无需 `_result.png`；阶段9/11 照常渲染。

#### 方式 B（备选）：脚本调用混元 3D **API**（网页积分不足时）

**必须**传入与阶段4～6 **完全相同**的 **`--template`** 与 **`--user-requirement`**。从 **`…/stage7_new_texture_generation_selected/`** 递归读取 `*.png` 提交贴图任务；筛图目录可用 **`--selected-dir`** 覆盖。

- 输出：`…/stage8_new_texture_model_generation/<中文风格>.glb`（必选）
- 若接口返回图 URL，脚本会额外写入：`…/<中文风格>_result.png`（或 `.jpg` / `.webp`）；**没有也不影响后续渲染**。

```bash
python stage8_new_texture_model_generation/generate_textured_models.py \
  --template "body_24_overall_set" \
  --user-requirement "2026年服装纹理趋势"
```

### Stage9 仅候选封面图（`stage9_render_covers`）

**脚本**：`stage11_render_videos/blender_render_videos.py`（`--pass covers`）  
**工程**：`resource/blender/blender_render_videos.blend`

输出 `output/stage4_10/<模板>/<需求截断>/stage9_render_covers/<模型名>_cover.png`（第 18 帧），**不**再生成 `cover.png`；每个 stage8 的 `*.glb` 一图。  
仅 **`pipeline_render_prefs.yml` / CLI** 中的 **`head_object` 与 `hair_object`** 参与渲染；其余 **`female|male_<数字>_head` / `_hair`** 一律不参与（`hide_render`）。每次导入的 GLB **顶层根**与 **`body`** 均设为 **`scale = 0.1`**。  
同一次批量建议固定 **Studio 背景墙**与环境一致：脚本中材质 `Studio_Fabric_1.001` 的 **Tint** 色默认使用预设表 **首色**；可用 **`--studio-tint-hex '#8E9775'`** 指定（完整预设见下）；需要旧版「每套随机一色」时用 **`--random-studio-tint`**。

预设 **Tint（HEX）**（与 `resource/blender/studio_color/<HEX>.png` 对应，文件名无 `#`；均为适合布料/影棚背景的**低饱和**色，共 26 项）：`#E3D9C6`、`#8E9775`、`#5F7A76`、`#B0C4DE`、`#D7C4BB`、`#F5F5DC`、`#E6E6FA`、`#D0C8FF`、`#B7AD99`、`#DEE4E7`、`#D1E9F0`、`#F4E0E0`、`#C9B8A4`、`#A8ADA4`、`#B8A89A`、`#D4C4B0`、`#9EB6B8`、`#C8D4D8`、`#DAD4C8`、`#A39E93`、`#8F9B8A`、`#C6BCB3`、`#E8E4DC`、`#B9C4C9`、`#A89B8C`、`#CCD5DB`

**推荐**与阶段4～8 相同地传入 **`--template`** 与 **`--user-requirement`**。Stage9/11 **启动时**即同步 **`pipeline_render_prefs.yml`**：有则读入缺省项；命令行写了 Tint/头/发则**覆盖并写回**；皆无则用随机 Tint 与默认头/发并**立即创建/更新**文件，因此**不必**等整次渲染结束才有 YAML，也**不必**在无 YAML 时强制手写头/发（仅 `--template`+`--user-requirement` 即可）。未同时给这两项时仍须在命令行指定头/发（旧扫描模式不写 YAML）。`--only-glb-stem` / **`--only-glb-stems`**、**`--render-output-dir`**、**`--resume`** 行为不变。

```bash
blender -b --python-use-system-env resource/blender/blender_render_videos.blend \
  -P stage11_render_videos/blender_render_videos.py -- \
  --pass covers \
  --studio-tint-hex "#E3D9C6" \
  --template "body_24_overall_set" \
  --user-requirement "从80/90后的流行儿童动漫中提取相应主题的服装颜色纹理logo" \
  --head-object female_03_head \
  --hair-object female_03_hair
```

若已存在 **`pipeline_render_prefs.yml`**，可简化为（示例，Tint 与头/发由 YAML 提供）：

```bash
blender -b --python-use-system-env resource/blender/blender_render_videos.blend \
  -P stage11_render_videos/blender_render_videos.py -- \
  --pass covers \
  --template "body_24_overall_set" \
  --user-requirement "从80/90后的流行儿童动漫中提取相应主题的服装颜色纹理logo"
```

多进程时子进程用 **`STAGE11_JSON`（与兼容的 `STAGE9_JSON`）** 收参，父进程会写入全量配置；勿依赖 `--` 后的参数在子进程里自动生效。

```bash
BLENDER_WORKERS=4 blender -b --python-use-system-env resource/blender/blender_render_videos.blend \
  -P stage11_render_videos/blender_render_videos.py -- \
  --pass covers \
  --workers 4 \
  --template "body_24_overall_set" \
  --user-requirement "从80/90后的流行儿童动漫中提取相应主题的服装颜色纹理logo" \
  --head-object female_00_head \
  --hair-object female_00_hair
```

### Stage10 人工筛封面（手工）

从同 run 的 **`stage9_render_covers/`** 里挑选 **6** 张 **`<模型名>_cover.png`** 复制到（正片目标 **5** 套，多 **1** 套备损；与 **`--workers 4`** 等多进程无强制对齐要求）：

`output/stage4_10/<模板>/<需求截断>/stage10_render_covers_selected/`

文件名须保持 `<模型名>_cover.png` 以与 `stage8` 的 GLB 主名一致。无需复制未选中的模型。

### Stage11 5 秒环绕正片（`stage11_render_videos`）

**脚本路径同上**，**`--pass videos`**。默认只渲染在 **`stage10_render_covers_selected/*_cover.png`** 中出现过的、且在 `stage8` 有对应 **`.glb`** 的模型，输出 `stage11_render_videos/<模型名>.mp4`；**不**在 stage11 里再写一遍封面 PNG（以省磁盘与时间）。加 **`--all-glbs`** 时改为对该 run 下**全部** stage8 GLB 出片（不筛）。与 Stage9 相同，**`--template`+`--user-requirement`** 时启动即同步 **`pipeline_render_prefs.yml`**，可省略 **`--studio-tint-hex` / `--head-object` / `--hair-object`**（由文件或默认/随机补齐并落盘）；头/发可见性与 GLB **0.1 缩放**规则亦与 Stage9 一致。**`--only-glb-stems '名称1,名称2'`** 在上述任务集之上再收窄到指定 **GLB 主名**（与 stage8 文件名一致）；可与 **`--workers`** 并发共用（参数写入 **`STAGE11_JSON`**）。**正片**建议与 Stage9 使用**同一** Studio Tint（及同一 HDRI/场景），使封面与成片的背景墙一致。`--resume` 时跳过已有效的 `*.mp4`。

**临时**：**`--render-output-dir <目录>`** 时，本批 **`*.mp4`** / **`*_cover.png`** 全部写入该目录（自动创建）；**默认不传**，仍写入各 run 下 **`stage11_render_videos`** / **`stage9_render_covers`**。与多进程兼容。

**多进程**与 Stage9 封面一致：**`--workers N`**，或运行时 **`BLENDER_WORKERS`**（若设置则优先生效）；子进程经 **`STAGE11_JSON` / `STAGE9_JSON`** 收参，勿依赖子进程里的 `--` 参数（见上文 **Stage9** 中「多进程时子进程用 `STAGE11_JSON`…」一段）。

```bash
blender -b --python-use-system-env resource/blender/blender_render_videos.blend \
  -P stage11_render_videos/blender_render_videos.py -- \
  --pass videos \
  --studio-tint-hex "#E3D9C6" \
  --template "body_24_overall_set" \
  --user-requirement "从80/90后的流行儿童动漫中提取相应主题的服装颜色纹理logo" \
  --head-object female_03_head \
  --hair-object female_03_hair
```

多路并行示例（与 **`--pass covers`** 时相同，仅换 **`videos`**）：

```bash
BLENDER_WORKERS=4 blender -b --python-use-system-env resource/blender/blender_render_videos.blend \
  -P stage11_render_videos/blender_render_videos.py -- \
  --pass videos \
  --workers 4 \
  --studio-tint-hex "#E3D9C6" \
  --template "body_24_overall_set" \
  --user-requirement "从80/90后的流行儿童动漫中提取相应主题的服装颜色纹理logo" \
  --head-object female_03_head \
  --hair-object female_03_hair
```

仅渲列表中的已选模型（逗号分隔），并与 4 路并发同用：

```bash
BLENDER_WORKERS=4 blender -b --python-use-system-env resource/blender/blender_render_videos.blend \
  -P stage11_render_videos/blender_render_videos.py -- \
  --pass videos \
  --workers 4 \
  --only-glb-stems "蜡笔小新,邋遢大王" \
  --studio-tint-hex "#E3D9C6" \
  --template "body_24_overall_set" \
  --user-requirement "从80/90后的流行儿童动漫中提取相应主题的服装颜色纹理logo" \
  --head-object female_03_head \
  --hair-object female_03_hair
```

### Stage12 白模（透明背景）视频

输出：`output/stage4_10/<模板名>/<需求截断>/stage12_render_white_mesh_videos/white_model.mov`（**QuickTime 容器 + FFmpeg `codec = PNG`**，**`color_mode = RGBA`**，透明背景）。**编码器须为 PNG** 时，在 Blender 中需 **`ffmpeg.format = QUICKTIME`**；**MPEG4 + PNG** 不是可用组合，无法用 `.mp4` 同时满足「PNG 编码 + 透明成片」。

使用工程 `resource/blender/render_around_white_mesh.blend`：导入 Stage8 的 `*.glb`，`body` 缩放到 `0.1`，材质全换为白 **Diffuse**（`Roughness=1.0`），渲 **1–180** 帧。脚本对 **`bpy.data.scenes["Scene"]`** 设置 **`film_transparent`**、**`image_settings.color_mode = RGBA`**、**`ffmpeg.format = QUICKTIME`**、**`ffmpeg.codec = PNG`**。

```bash
blender -b --python-use-system-env resource/blender/render_around_white_mesh.blend \
  -P stage12_render_white_mesh_videos/blender_render_white_mesh_videos.py -- \
  --template "body_24_overall_set" \
  --user-requirement "从80/90后的流行儿童动漫中提取相应主题的服装颜色纹理logo"
```

默认在多个 GLB 时只取**首个**出单一 `white_model.mov`；需指定来源时加 `--only-glb-stem`。

## 5. 说明

- `.cursorrules` 已加入 Python 3.12 实践规则（参考公开模板改写）。
- Stage7、Stage10 按需求保留为手工步骤，无自动脚本。
- Stage8 **默认走网页**：用混元 3D 网页积分生成后手放 **`.glb`** 到 `stage8_new_texture_model_generation/`；**网页积分不够**时再运行 **`generate_textured_models.py`** 走腾讯云 API 补跑。后续渲染仅依赖 `*.glb`。
- 若 API 返回字段有变动，优先调整 `common/llm_clients.py` 与 `common/tencent_hunyuan_client.py`。
