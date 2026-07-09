# Pet Stage3：宠物浮雕拉模与 360° 渲染

用户在**宠物定制网站**手工生成浮雕后，本仓库按订单号拉取 3D 模型并渲染旋转展示视频。

## 目录约定

```text
output/宠物定制/pet_relief/<order_id>/
├── model/                 # 拉取的 GLB 等
└── pet_relief_360/        # <order_id>_360.mp4
```

## Stage3a：拉取模型

```bash
# 远程 API（需配置 PET_CUSTOMIZATION_API_BASE_URL）
python pet_stage3_relief_render/fetch_relief_model.py --order-id YOUR_ORDER_ID

# 开发降级：从本地目录拷贝
python pet_stage3_relief_render/fetch_relief_model.py \
  --order-id YOUR_ORDER_ID \
  --local-model-dir /path/to/downloaded/glb
```

## Stage3b：Blender 360 渲染

工程文件：`resource/blender/pet_relief_360.blend`（或 env `PET_RELIEF_BLEND_FILE`，**尚未提供时可先用空 blend 占位**）。

```bash
blender -b --python-use-system-env resource/blender/pet_relief_360.blend \
  -P pet_stage3_relief_render/blender_render_relief_360.py -- \
  --order-id YOUR_ORDER_ID
```

拉模 + 渲染一步：

```bash
python pet_stage3_relief_render/fetch_relief_model.py \
  --order-id YOUR_ORDER_ID \
  --local-model-dir /path/to/glb \
  --render
```

## API 配置（.env）

- `PET_CUSTOMIZATION_API_BASE_URL`
- `PET_CUSTOMIZATION_API_KEY`（可选）
- `PET_CUSTOMIZATION_ORDER_PATH`（默认 `api/v1/orders/{order_id}/model`）

响应 JSON 需含 `model_files` / `model_url` 等可下载字段，详见 `common/pet_customization_client.py`。
