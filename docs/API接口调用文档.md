# media2api 接口调用文档

本文面向下游调用方和平台运维人员，说明 media2api 对外暴露的主要接口、认证方式、常见调用链路，以及如何通过本系统调用 `gpt-image-2` 生图。

> 文档基于当前代码实现整理，核心路由来自 `media2api/main.py`。OpenAI 图像模型能力说明参考官方文档：`gpt-image-2` 是 GPT Image 系列的图像生成与编辑模型，支持文本输入、图像输入和图像输出；官方 Image API 可通过 `/v1/images/generations` 和 `/v1/images/edits` 调用。官方 GPT Image 模型返回 base64 图片；本系统额外提供 `response_format=url`，把结果落到本地资产系统后返回可下载 URL。

## 1. 基础信息

### 1.1 服务地址

当前服务器部署地址：

```text
http://192.168.31.26:18082
```

本地开发默认地址：

```text
http://127.0.0.1:8080
```

下文用环境变量表示：

```bash
export MEDIA2API_BASE_URL="http://192.168.31.26:18082"
export MEDIA2API_API_KEY="<你的下游调用 API Key>"
```

Windows PowerShell：

```powershell
$env:MEDIA2API_BASE_URL = "http://192.168.31.26:18082"
$env:MEDIA2API_API_KEY = "<你的下游调用 API Key>"
```

### 1.2 认证方式

所有 `/v1/*` 接口都建议携带 API Key。

支持两种请求头：

```http
Authorization: Bearer <API_KEY>
```

或：

```http
x-api-key: <API_KEY>
```

管理员接口 `/v1/admin/*` 需要管理员 API Key。普通用户 API Key 只能访问自己的任务、资产、账单、告警、安全事件和请求日志等用户侧接口。

### 1.3 通用响应与错误

成功响应一般是 JSON。常见对象类型：

| object | 含义 |
| --- | --- |
| `list` | 列表响应 |
| `media.job` | 媒体任务 |
| `media.asset` | 媒体资产 |
| `image` | OpenAI-compatible 图片响应项 |
| `video.generation` | OpenAI-compatible 视频任务 |

错误响应格式：

```json
{
  "code": "INVALID_INPUT",
  "message": "错误说明",
  "retryable": false
}
```

常见错误：

| code | 场景 |
| --- | --- |
| `API_KEY_REQUIRED` | 未携带 API Key |
| `INVALID_API_KEY` | API Key 不存在或已失效 |
| `ADMIN_REQUIRED` | 普通用户调用管理员接口 |
| `INVALID_INPUT` | 请求体或查询参数不合法 |
| `UNSUPPORTED_MODEL_OPERATION` | 模型不支持当前操作 |
| `NO_PROVIDER_AVAILABLE` | 没有可用 provider/account |
| `INSUFFICIENT_BALANCE` | 用户余额或计费 hold 不足 |
| `SAFETY_REJECTED` | 命中安全策略 |
| `PROVIDER_FAILED` | 上游 provider 执行失败 |

所有响应会带 `x-request-id`，排查问题时请保留该值。

## 2. 推荐调用链路

### 2.1 图片生成

1. `GET /v1/models` 查看可用模型。
2. `POST /v1/images/generations` 创建文生图任务。
3. 如果返回 `url`，直接下载图片。
4. 如果需要统一资产管理，使用返回里的 `asset_id` 继续查询 `/v1/assets/{asset_id}`。

### 2.2 图片编辑

1. `POST /v1/assets` 上传参考图或蒙版，拿到 `asset_id`。
2. `POST /v1/images/edits`，将 `image` 或 `mask` 填为资产 ID。
3. 读取返回的图片 `url` 或 `b64_json`。

### 2.3 视频生成

1. 文生视频：直接 `POST /v1/videos/generations`。
2. 图生视频：先 `POST /v1/assets` 上传首帧，再 `POST /v1/videos/generations`。
3. 返回的是异步任务，轮询 `GET /v1/videos/generations/{job_id}` 或 `GET /v1/media-jobs/{job_id}`。
4. 完成后从 `outputs` 里拿视频资产 `url`。

### 2.4 原生媒体任务

如果你希望统一调用图片、视频、编辑、扩展等能力，建议直接使用：

```text
POST /v1/media-jobs
GET  /v1/media-jobs/{job_id}
```

原生接口比 OpenAI-compatible 接口暴露更多路由参数、资产参数和任务状态。

## 3. 模型与操作

### 3.1 逻辑模型

系统默认逻辑模型：

| 逻辑模型 | 操作 | 用途 |
| --- | --- | --- |
| `t2i-fast` | `text_to_image` | 快速文生图 |
| `t2i-pro` | `text_to_image` | 高质量文生图 |
| `image-edit` | `image_edit`, `image_to_image` | 图片编辑 / 图生图 |
| `image-variation` | `image_to_image` | 图片变体 |
| `t2v-general` | `text_to_video` | 文生视频 |
| `i2v-fast` | `image_to_video` | 快速图生视频 |
| `i2v-pro` | `image_to_video` | 高质量图生视频 |
| `video-extend` | `video_extend` | 视频续写 |

### 3.2 provider 模型

`model` 字段可以传逻辑模型，也可以在已有映射时传 provider 模型，例如 `gpt-image-2`。

推荐做法：

| 场景 | 推荐 `model` | 可选定向 |
| --- | --- | --- |
| 通用文生图 | `t2i-pro` | 无 |
| 指定 OpenAI GPT Image 2 | `gpt-image-2` 或 `t2i-pro` | `providers: ["openai_image"]` |
| 图片编辑 | `image-edit` | `provider_models: ["gpt-image-2"]` |
| 图生视频 | `i2v-pro` | 指定视频 provider |

如果生产环境中还没有启用真实的 OpenAI 图片账号或 connector，`gpt-image-2` 请求会因为没有可用 provider/account 而失败。当前系统的 mock provider 可以验证接口链路，但不代表真实 OpenAI 图片生成已接通。

### 3.3 路由参数

图片、视频和原生任务都支持以下路由参数：

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `route_policy` | string | 路由策略，例如平衡、低成本、最快或高质量，实际策略由后端实现解释 |
| `provider_preference` / `providers` | string 或 string[] | 优先使用的 provider，例如 `openai_image` |
| `provider_model` / `provider_models` | string 或 string[] | 优先使用的 provider 侧模型，例如 `gpt-image-2` |
| `excluded_providers` | string 或 string[] | 排除某些 provider |
| `preferred_account_id` | string | 指定账号池中的某个账号 |

## 4. OpenAI-compatible 接口

这些接口的路径和形态接近 OpenAI Image API / Video API，适合迁移已有 OpenAI 风格客户端。

### 4.1 查看模型

```bash
curl "$MEDIA2API_BASE_URL/v1/models" \
  -H "Authorization: Bearer $MEDIA2API_API_KEY"
```

响应示例：

```json
{
  "object": "list",
  "data": [
    {
      "id": "t2i-pro",
      "object": "model",
      "owned_by": "media2api",
      "operations": ["text_to_image"],
      "enabled": true
    }
  ]
}
```

### 4.2 调用 `gpt-image-2` 生图

用途：文生图。

接口：

```text
POST /v1/images/generations
```

最小请求：

```bash
curl -X POST "$MEDIA2API_BASE_URL/v1/images/generations" \
  -H "Authorization: Bearer $MEDIA2API_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-image-2",
    "prompt": "一张高端机械键盘的产品摄影图，透明外壳，白色桌面，柔和棚拍光，细节清晰",
    "size": "1024x1024",
    "n": 1,
    "quality": "high",
    "response_format": "url",
    "providers": ["openai_image"]
  }'
```

如果你希望走系统逻辑模型，由路由层映射到 OpenAI provider 模型：

```bash
curl -X POST "$MEDIA2API_BASE_URL/v1/images/generations" \
  -H "Authorization: Bearer $MEDIA2API_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "t2i-pro",
    "prompt": "一张高端机械键盘的产品摄影图，透明外壳，白色桌面，柔和棚拍光，细节清晰",
    "size": "1024x1024",
    "quality": "high",
    "response_format": "url",
    "providers": ["openai_image"],
    "provider_models": ["gpt-image-2"]
  }'
```

请求字段：

| 字段 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `model` | 否 | `t2i-fast` | 逻辑模型或 provider 模型 |
| `prompt` | 是 | 无 | 图片提示词 |
| `size` | 否 | `1024x1024` | 输出尺寸；`gpt-image-2` 支持灵活尺寸，实际可用范围取决于上游 provider |
| `n` | 否 | `1` | 生成数量 |
| `quality` | 否 | `standard` | 质量档位，常见值 `standard`、`high`、`medium`、`low`，最终由 provider 支持情况决定 |
| `seed` | 否 | 无 | 随机种子，provider 支持时生效 |
| `negative_prompt` | 否 | 无 | 负向提示词，provider 支持时生效 |
| `response_format` | 否 | `url` | `url` 或 `b64_json` |
| `providers` | 否 | 无 | 指定 provider，例如 `["openai_image"]` |
| `provider_models` | 否 | 无 | 指定 provider 模型，例如 `["gpt-image-2"]` |
| `preferred_account_id` | 否 | 无 | 指定某个账号 |

成功响应，`response_format=url`：

```json
{
  "created": 1760000000,
  "data": [
    {
      "url": "http://192.168.31.26:18082/v1/assets/asset_xxx/content?expires=...",
      "asset_id": "asset_xxx"
    }
  ],
  "job_id": "job_xxx"
}
```

成功响应，`response_format=b64_json`：

```json
{
  "created": 1760000000,
  "data": [
    {
      "b64_json": "iVBORw0KGgo...",
      "asset_id": "asset_xxx"
    }
  ],
  "job_id": "job_xxx"
}
```

说明：

- 官方 OpenAI Image API 中，GPT Image 模型返回 base64 图片；本系统默认 `response_format=url`，便于下游直接下载或展示。
- 无论返回 `url` 还是 `b64_json`，系统都会生成内部资产并返回 `asset_id`。
- `url` 指向 `/v1/assets/{asset_id}/content`，可能包含带过期时间的签名参数。

### 4.3 图片编辑

用途：基于一张或多张输入图进行编辑、重绘、变体生成。

接口：

```text
POST /v1/images/edits
```

先上传输入图：

```bash
BASE64_IMAGE="$(base64 -w 0 ./input.png)"

curl -X POST "$MEDIA2API_BASE_URL/v1/assets" \
  -H "Authorization: Bearer $MEDIA2API_API_KEY" \
  -H "Content-Type: application/json" \
  -d "{
    \"kind\": \"image\",
    \"purpose\": \"reference\",
    \"mime_type\": \"image/png\",
    \"filename\": \"input.png\",
    \"b64_json\": \"$BASE64_IMAGE\"
  }"
```

然后编辑：

```bash
curl -X POST "$MEDIA2API_BASE_URL/v1/images/edits" \
  -H "Authorization: Bearer $MEDIA2API_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "image-edit",
    "prompt": "保持主体不变，把背景替换为极简白色摄影棚，增加柔和阴影",
    "image": "asset_input_xxx",
    "size": "1024x1024",
    "quality": "high",
    "response_format": "url",
    "providers": ["openai_image"],
    "provider_models": ["gpt-image-2"]
  }'
```

请求字段：

| 字段 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `model` | 否 | `image-edit` | 推荐使用 `image-edit` |
| `prompt` | 是 | 无 | 编辑指令 |
| `image` | 否 | 无 | 单个资产 ID 或资产 ID 数组 |
| `mask` | 否 | 无 | 蒙版资产 ID |
| `size` | 否 | `1024x1024` | 输出尺寸 |
| `n` | 否 | `1` | 输出数量 |
| `quality` | 否 | `standard` | 输出质量 |
| `response_format` | 否 | `url` | `url` 或 `b64_json` |

### 4.4 视频生成

用途：文生视频或图生视频。

接口：

```text
POST /v1/videos/generations
```

文生视频：

```bash
curl -X POST "$MEDIA2API_BASE_URL/v1/videos/generations" \
  -H "Authorization: Bearer $MEDIA2API_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "t2v-general",
    "prompt": "夜晚城市街道上的霓虹灯广告牌，镜头缓慢推进，电影感",
    "duration": 5,
    "aspect_ratio": "16:9",
    "quality": "standard"
  }'
```

图生视频：

```bash
curl -X POST "$MEDIA2API_BASE_URL/v1/videos/generations" \
  -H "Authorization: Bearer $MEDIA2API_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "i2v-pro",
    "prompt": "让画面里的产品缓慢旋转，灯光从左侧扫过",
    "image": "asset_input_xxx",
    "duration": 5,
    "aspect_ratio": "16:9",
    "quality": "high"
  }'
```

创建响应：

```json
{
  "id": "job_xxx",
  "object": "video.generation.job",
  "status": "queued",
  "model": "i2v-pro",
  "created": 1760000000
}
```

查询结果：

```bash
curl "$MEDIA2API_BASE_URL/v1/videos/generations/job_xxx" \
  -H "Authorization: Bearer $MEDIA2API_API_KEY"
```

完成响应示例：

```json
{
  "id": "job_xxx",
  "object": "video.generation",
  "status": "completed",
  "outputs": [
    {
      "id": "asset_video_xxx",
      "kind": "video",
      "mime_type": "video/mp4",
      "url": "http://192.168.31.26:18082/v1/assets/asset_video_xxx/content?expires=...",
      "thumbnail_url": "http://192.168.31.26:18082/v1/assets/asset_thumb_xxx/content?expires=..."
    }
  ]
}
```

## 5. 原生媒体任务接口

### 5.1 创建任务

接口：

```text
POST /v1/media-jobs
```

通用请求：

```bash
curl -X POST "$MEDIA2API_BASE_URL/v1/media-jobs" \
  -H "Authorization: Bearer $MEDIA2API_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "operation": "text_to_image",
    "model": "t2i-pro",
    "prompt": "一张适合电商详情页的智能音箱产品图",
    "params": {
      "size": "1024x1024",
      "quality": "high",
      "n": 1
    },
    "providers": ["openai_image"],
    "provider_models": ["gpt-image-2"]
  }'
```

请求字段：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `operation` | 是 | `text_to_image`、`image_to_image`、`image_edit`、`text_to_video`、`image_to_video`、`video_extend` |
| `model` | 是 | 逻辑模型或 provider 模型 |
| `prompt` | 否 | 提示词；多数生成类任务需要 |
| `assets` | 否 | 输入资产 ID 列表 |
| `image` / `images` | 否 | 图片输入资产 |
| `first_frame` / `last_frame` | 否 | 视频生成首尾帧 |
| `mask` | 否 | 图片编辑蒙版 |
| `video` / `videos` | 否 | 视频续写输入 |
| `params` | 否 | provider 参数，例如 `size`、`quality`、`duration`、`aspect_ratio` |
| `webhook` | 否 | 任务完成后的回调地址 |

### 5.2 查询任务

```bash
curl "$MEDIA2API_BASE_URL/v1/media-jobs/job_xxx" \
  -H "Authorization: Bearer $MEDIA2API_API_KEY"
```

任务状态：

| status | 含义 |
| --- | --- |
| `created` | 已创建 |
| `admitted` | 已通过治理和计费预占 |
| `queued` | 等待执行 |
| `leasing` | 正在获取账号租约 |
| `preparing` | 正在准备输入资产 |
| `submitting` | 正在提交 provider |
| `provider_queued` | provider 已接收 |
| `polling` | 正在轮询 provider |
| `fetching` | 正在拉取结果 |
| `storing` | 正在保存资产 |
| `completed` | 完成 |
| `failed` | 失败 |
| `cancelled` | 已取消 |
| `expired` | 已过期 |

### 5.3 查询任务尝试与事件

```bash
curl "$MEDIA2API_BASE_URL/v1/media-jobs/job_xxx/attempts" \
  -H "Authorization: Bearer $MEDIA2API_API_KEY"

curl "$MEDIA2API_BASE_URL/v1/media-jobs/job_xxx/events" \
  -H "Authorization: Bearer $MEDIA2API_API_KEY"
```

### 5.4 重试与取消

```bash
curl -X POST "$MEDIA2API_BASE_URL/v1/media-jobs/job_xxx/retry" \
  -H "Authorization: Bearer $MEDIA2API_API_KEY"

curl -X POST "$MEDIA2API_BASE_URL/v1/media-jobs/job_xxx/cancel" \
  -H "Authorization: Bearer $MEDIA2API_API_KEY"
```

## 6. 资产接口

### 6.1 上传资产

接口：

```text
POST /v1/assets
```

JSON base64 上传：

```bash
curl -X POST "$MEDIA2API_BASE_URL/v1/assets" \
  -H "Authorization: Bearer $MEDIA2API_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "kind": "image",
    "purpose": "reference",
    "mime_type": "image/png",
    "filename": "reference.png",
    "b64_json": "iVBORw0KGgo..."
  }'
```

请求字段：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `kind` | 否 | `image`、`video`、`thumbnail` 等 |
| `purpose` | 否 | `reference`、`input`、`output` 等 |
| `mime_type` | 否 | 例如 `image/png`、`video/mp4` |
| `filename` | 否 | 原始文件名 |
| `b64_json` | 二选一 | base64 内容 |
| `url` | 二选一 | 远程文件地址，后端拉取并入库 |

### 6.2 查询资产

```bash
curl "$MEDIA2API_BASE_URL/v1/assets?kind=image&limit=20" \
  -H "Authorization: Bearer $MEDIA2API_API_KEY"

curl "$MEDIA2API_BASE_URL/v1/assets/asset_xxx" \
  -H "Authorization: Bearer $MEDIA2API_API_KEY"
```

### 6.3 下载资产

```bash
curl -L "$MEDIA2API_BASE_URL/v1/assets/asset_xxx/content" \
  -H "Authorization: Bearer $MEDIA2API_API_KEY" \
  -o output.png
```

如果响应里的 `url` 已包含 `expires` 和 `signature`，可以直接下载该 URL，不需要额外认证头。

### 6.4 删除资产

```bash
curl -X DELETE "$MEDIA2API_BASE_URL/v1/assets/asset_xxx" \
  -H "Authorization: Bearer $MEDIA2API_API_KEY"
```

## 7. 用户侧查询接口

### 7.1 任务列表

```bash
curl "$MEDIA2API_BASE_URL/v1/jobs?status=completed&limit=20" \
  -H "Authorization: Bearer $MEDIA2API_API_KEY"
```

### 7.2 计费与用量

```bash
curl "$MEDIA2API_BASE_URL/v1/billing/summary" \
  -H "Authorization: Bearer $MEDIA2API_API_KEY"

curl "$MEDIA2API_BASE_URL/v1/billing/usage?limit=100" \
  -H "Authorization: Bearer $MEDIA2API_API_KEY"

curl "$MEDIA2API_BASE_URL/v1/billing/pricing-rules" \
  -H "Authorization: Bearer $MEDIA2API_API_KEY"

curl "$MEDIA2API_BASE_URL/v1/billing/invoice?format=json" \
  -H "Authorization: Bearer $MEDIA2API_API_KEY"
```

### 7.3 Webhook 投递记录

```bash
curl "$MEDIA2API_BASE_URL/v1/webhooks?limit=50" \
  -H "Authorization: Bearer $MEDIA2API_API_KEY"

curl -X POST "$MEDIA2API_BASE_URL/v1/webhooks/dlv_xxx/retry" \
  -H "Authorization: Bearer $MEDIA2API_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"attempts": 1}'
```

### 7.4 告警、安全事件、请求日志、治理限制

```bash
curl "$MEDIA2API_BASE_URL/v1/alerts?status=open" \
  -H "Authorization: Bearer $MEDIA2API_API_KEY"

curl "$MEDIA2API_BASE_URL/v1/safety-events?limit=50" \
  -H "Authorization: Bearer $MEDIA2API_API_KEY"

curl "$MEDIA2API_BASE_URL/v1/request-logs?limit=50" \
  -H "Authorization: Bearer $MEDIA2API_API_KEY"

curl "$MEDIA2API_BASE_URL/v1/governance/limits" \
  -H "Authorization: Bearer $MEDIA2API_API_KEY"
```

## 8. 管理员接口

管理员接口用于配置模型、账号、provider、连接器、验收和运维，不建议暴露给普通下游用户。

### 8.1 运行状态与验收

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/health` | 无鉴权健康检查 |
| `GET` | `/v1/runtime` | 队列、数据库、Redis、资产存储、任务统计 |
| `GET` | `/v1/admin/readiness` | 核心/生产就绪状态 |
| `GET` | `/v1/admin/final-acceptance-matrix` | 最终验收矩阵 |
| `GET` | `/v1/admin/production-go-live-plan` | 生产上线计划与阻塞项 |
| `GET` | `/v1/admin/connector-conformance-report` | 连接器能力覆盖报告 |
| `GET` | `/v1/admin/external-connector-preflight` | 外部连接器预检 |
| `GET` | `/v1/admin/delivery-package` | 交付包摘要 |
| `GET` | `/metrics` | Prometheus 指标 |

### 8.2 Provider 与能力

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/v1/provider-templates` | 查看 provider 模板 |
| `GET` | `/v1/target-platforms` | 查看目标平台表 |
| `GET` | `/v1/providers` | 查看 provider 列表 |
| `POST` | `/v1/admin/providers` | 创建 provider |
| `PATCH` | `/v1/admin/providers/{provider_id}` | 更新 provider |
| `POST` | `/v1/admin/providers/{provider_id}/health-check` | 运行健康检查 |
| `GET` | `/v1/admin/providers/{provider_id}/connector-runtime` | 查看 connector runtime 诊断 |
| `POST` | `/v1/admin/providers/{provider_id}/sync-capabilities` | 同步 provider 能力 |
| `GET` | `/v1/admin/provider-capabilities` | 查看所有 provider 能力 |
| `GET` | `/v1/admin/providers/{provider_id}/capabilities` | 查看单个 provider 能力 |
| `POST` | `/v1/admin/provider-templates/{template_id}/install` | 安装模板 |
| `POST` | `/v1/admin/provider-templates/{template_id}/activate` | 激活模板 |
| `POST` | `/v1/admin/provider-templates/{template_id}/external-acceptance` | 模板外部验收 |

### 8.3 账号接入与 OpenAI 图片账号

查看 OpenAI 图片账号接入要求：

```bash
curl "$MEDIA2API_BASE_URL/v1/admin/account-guides/openai_image" \
  -H "Authorization: Bearer $MEDIA2API_API_KEY"
```

通过账号接入接口登记 OpenAI GPT Image 账号：

```bash
curl -X POST "$MEDIA2API_BASE_URL/v1/admin/account-onboarding" \
  -H "Authorization: Bearer $MEDIA2API_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "provider_id": "openai_image",
    "account_id": "acct_openai_image_01",
    "label": "OpenAI GPT Image 2 account 01",
    "resource_type": "web_cookie_provider",
    "auth_method": "cookie_secret",
    "credential_kind": "cookie",
    "credential_value": {
      "cookie_header_or_cookie_jar": "name1=value1; name2=value2",
      "user_agent": "Mozilla/5.0 ...",
      "domain": "chatgpt.com"
    },
    "supported_operations": ["text_to_image", "image_to_image", "image_edit"],
    "supported_provider_models": ["gpt-image-2"],
    "concurrency_limit": 1,
    "auto_create_mappings": true,
    "sync_capabilities": true,
    "run_health_check": true
  }'
```

安全注意：

- 只登记你有权使用的账号资源。
- 不要把真实 cookie、OAuth token、API key 写入 Git 文档、Issue 或聊天记录。
- 如果已有 `secret://...` 或 `env://...`，优先传 `credential_ref`，避免直接传 `credential_value`。
- `openai_image` 也可以通过 sidecar/agent provider 接入，是否需要 `provider_base_url` 取决于实际 connector。

账号相关管理员接口：

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/v1/accounts` | 查看账号池 |
| `POST` | `/v1/admin/accounts` | 创建账号 |
| `PATCH` | `/v1/admin/accounts/{account_id}` | 更新账号 |
| `POST` | `/v1/admin/accounts/bulk-upsert` | 批量 upsert 账号 |
| `GET` | `/v1/admin/accounts/{account_id}/diagnostics` | 账号诊断 |
| `POST` | `/v1/admin/accounts/{account_id}/sync-quota` | 同步账号配额 |
| `POST` | `/v1/admin/accounts/{account_id}/external-acceptance` | 单账号外部验收 |
| `POST` | `/v1/admin/account-acceptance-suite` | 账号验收套件 |
| `POST` | `/v1/admin/account-onboarding/plan` | 接入计划预览 |
| `POST` | `/v1/admin/account-onboarding` | 单账号接入 |
| `POST` | `/v1/admin/account-onboarding/bulk` | 批量账号接入 |
| `POST` | `/v1/admin/account-setup-quickstart` | 快速接入工作流 |

### 8.4 模型与映射

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/v1/admin/logical-models` | 查看逻辑模型 |
| `POST` | `/v1/admin/logical-models` | 创建逻辑模型 |
| `PATCH` | `/v1/admin/logical-models/{model_id}` | 更新逻辑模型 |
| `GET` | `/v1/model-mappings` | 查看模型映射 |
| `POST` | `/v1/admin/model-mappings` | 创建映射 |
| `PATCH` | `/v1/admin/model-mappings/{mapping_id}` | 更新映射 |
| `POST` | `/v1/router/preview` | 路由预览 |

创建 `t2i-pro -> openai_image/gpt-image-2` 映射示例：

```bash
curl -X POST "$MEDIA2API_BASE_URL/v1/admin/model-mappings" \
  -H "Authorization: Bearer $MEDIA2API_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "logical_model": "t2i-pro",
    "provider_id": "openai_image",
    "provider_model": "gpt-image-2",
    "operations": ["text_to_image"],
    "priority": 10,
    "weight": 1,
    "cost_score": 0.5,
    "speed_score": 0.6,
    "quality_score": 0.95,
    "reliability_score": 0.8,
    "enabled": true
  }'
```

### 8.5 用户、API Key 与凭据

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/v1/admin/users` | 用户列表 |
| `POST` | `/v1/admin/users` | 创建用户 |
| `PATCH` | `/v1/admin/users/{user_id}` | 更新用户 |
| `GET` | `/v1/admin/api-keys` | API Key 列表 |
| `POST` | `/v1/admin/api-keys` | 创建 API Key |
| `PATCH` | `/v1/admin/api-keys/{api_key_id}` | 更新 API Key |
| `DELETE` | `/v1/admin/api-keys/{api_key_id}` | 删除 API Key |
| `GET` | `/v1/admin/credential-secrets` | 凭据 secret 列表 |
| `POST` | `/v1/admin/credential-secrets` | 创建 secret |
| `PATCH` | `/v1/admin/credential-secrets/{secret_id}` | 更新 secret |
| `DELETE` | `/v1/admin/credential-secrets/{secret_id}` | 删除 secret |

创建下游用户和 API Key：

```bash
curl -X POST "$MEDIA2API_BASE_URL/v1/admin/users" \
  -H "Authorization: Bearer $MEDIA2API_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "client@example.com",
    "tier": "default",
    "wallet_balance": 100000
  }'

curl -X POST "$MEDIA2API_BASE_URL/v1/admin/api-keys" \
  -H "Authorization: Bearer $MEDIA2API_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "usr_xxx",
    "name": "client-production-key"
  }'
```

### 8.6 运维、账单、审计

| 分类 | 主要接口 |
| --- | --- |
| 作业运维 | `/v1/admin/jobs`、`/v1/admin/media-jobs/{job_id}/diagnostics`、`/v1/admin/media-jobs/{job_id}/events`、`/v1/admin/media-jobs/{job_id}/retry`、`/v1/admin/media-jobs/{job_id}/cancel` |
| 租约 | `/v1/admin/account-leases`、`/v1/admin/account-leases/release-expired`、`/v1/admin/account-leases/reconcile` |
| 计费 | `/v1/admin/pricing-rules`、`/v1/admin/provider-costs`、`/v1/admin/billing-holds`、`/v1/admin/billing-invoices`、`/v1/admin/analytics` |
| 治理 | `/v1/admin/user-limit-policies`、`/v1/admin/circuit-breakers` |
| 告警 | `/v1/admin/alert-rules`、`/v1/admin/alerts`、`/v1/admin/anomaly-scan` |
| 安全 | `/v1/admin/safety-policies`、`/v1/admin/safety-events` |
| 审计 | `/v1/admin/request-logs`、`/v1/admin/provider-contracts`、`/v1/admin/provider-contract-matrix` |
| Webhook | `/v1/admin/webhooks`、`/v1/admin/webhooks/retry-failed`、`/v1/admin/webhooks/{delivery_id}/retry` |
| 配置迁移 | `/v1/admin/config-export`、`/v1/admin/config-import` |

## 9. Python 调用示例

### 9.1 文生图

```python
from __future__ import annotations

import base64
import os
import requests

base_url = os.environ["MEDIA2API_BASE_URL"].rstrip("/")
api_key = os.environ["MEDIA2API_API_KEY"]

resp = requests.post(
    f"{base_url}/v1/images/generations",
    headers={"Authorization": f"Bearer {api_key}"},
    json={
        "model": "gpt-image-2",
        "prompt": "一张白色背景上的透明机械键盘产品图，商业摄影，细节清晰",
        "size": "1024x1024",
        "quality": "high",
        "response_format": "b64_json",
        "providers": ["openai_image"],
    },
    timeout=180,
)
resp.raise_for_status()
payload = resp.json()

image_base64 = payload["data"][0]["b64_json"]
with open("output.png", "wb") as f:
    f.write(base64.b64decode(image_base64))

print(payload["job_id"], payload["data"][0]["asset_id"])
```

### 9.2 视频轮询

```python
from __future__ import annotations

import os
import time
import requests

base_url = os.environ["MEDIA2API_BASE_URL"].rstrip("/")
api_key = os.environ["MEDIA2API_API_KEY"]
headers = {"Authorization": f"Bearer {api_key}"}

created = requests.post(
    f"{base_url}/v1/videos/generations",
    headers=headers,
    json={
        "model": "t2v-general",
        "prompt": "清晨海边咖啡店，镜头缓慢推进，暖色调",
        "duration": 5,
        "aspect_ratio": "16:9",
    },
    timeout=60,
)
created.raise_for_status()
job_id = created.json()["id"]

while True:
    job = requests.get(f"{base_url}/v1/media-jobs/{job_id}", headers=headers, timeout=30).json()
    if job["status"] in {"completed", "failed", "cancelled", "expired"}:
        break
    time.sleep(2)

if job["status"] != "completed":
    raise RuntimeError(job)

print(job["outputs"][0]["url"])
```

## 10. OpenAI 官方 Image API 与本系统差异

| 项目 | OpenAI 官方 Image API | media2api |
| --- | --- | --- |
| 基础地址 | `https://api.openai.com` | 自部署地址，例如 `http://192.168.31.26:18082` |
| 认证 | OpenAI API Key | media2api API Key |
| 生图接口 | `/v1/images/generations` | `/v1/images/generations` |
| 编辑接口 | `/v1/images/edits` | `/v1/images/edits` |
| 默认返回 | GPT Image 模型返回 base64 图片 | 默认 `url`，也支持 `b64_json` |
| 资产系统 | 无本地资产 ID | 每次输出都会落资产并返回 `asset_id` |
| 路由 | 直接指定 OpenAI 模型 | 可经过逻辑模型、provider、账号池、fallback |
| 运维 | OpenAI 平台侧 | 本系统提供任务、账单、审计、验收、告警 |

迁移已有 OpenAI 图片调用时，通常只需要改：

1. `base_url` 改为 media2api 服务地址。
2. API Key 改为 media2api 下游 API Key。
3. 如需强制 OpenAI 图片资源，增加 `providers: ["openai_image"]` 和 `provider_models: ["gpt-image-2"]`。

官方参考：

- OpenAI Image generation guide: https://developers.openai.com/api/docs/guides/image-generation
- OpenAI Images API reference: https://developers.openai.com/api/reference/resources/images/methods/generate/
- OpenAI GPT Image 2 model page: https://developers.openai.com/api/docs/models/gpt-image-2

## 11. 生产可用性检查

调用真实外部 provider 前，建议管理员先检查：

```bash
curl "$MEDIA2API_BASE_URL/v1/admin/readiness" \
  -H "Authorization: Bearer $MEDIA2API_API_KEY"

curl "$MEDIA2API_BASE_URL/v1/admin/connector-conformance-report" \
  -H "Authorization: Bearer $MEDIA2API_API_KEY"

curl "$MEDIA2API_BASE_URL/v1/admin/final-acceptance-matrix" \
  -H "Authorization: Bearer $MEDIA2API_API_KEY"
```

关键判断：

| 字段 | 期望 |
| --- | --- |
| `core_ready` | `true` |
| `production_ready` | 真实生产前应为 `true` |
| `authorized_external_connector_accounts` | 至少有覆盖目标操作的非 mock 账号 |
| connector conformance | 目标 provider 的 required operations 应全部满足 |

如果 `core_ready=true` 但 `production_ready=false`，说明系统框架、队列、资产、账单、审计等核心链路可用，但真实外部生成账号或 connector 尚未覆盖生产要求。

## 12. 接口速查表

### 12.1 公开/用户侧

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/health` | 健康检查 |
| `GET` | `/v1/runtime` | 运行状态 |
| `GET` | `/v1/models` | 模型列表 |
| `POST` | `/v1/images/generations` | 文生图 |
| `POST` | `/v1/images/edits` | 图片编辑 |
| `POST` | `/v1/videos/generations` | 文生视频 / 图生视频 |
| `GET` | `/v1/videos/generations/{job_id}` | 查询视频生成任务 |
| `POST` | `/v1/media-jobs` | 创建原生媒体任务 |
| `GET` | `/v1/media-jobs/{job_id}` | 查询媒体任务 |
| `GET` | `/v1/media-jobs/{job_id}/attempts` | 查询任务尝试 |
| `GET` | `/v1/media-jobs/{job_id}/events` | 查询任务事件 |
| `POST` | `/v1/media-jobs/{job_id}/retry` | 重试任务 |
| `POST` | `/v1/media-jobs/{job_id}/cancel` | 取消任务 |
| `POST` | `/v1/assets` | 创建资产 |
| `GET` | `/v1/assets` | 资产列表 |
| `GET` | `/v1/assets/{asset_id}` | 资产详情 |
| `GET` | `/v1/assets/{asset_id}/content` | 下载资产 |
| `DELETE` | `/v1/assets/{asset_id}` | 删除资产 |
| `GET` | `/v1/jobs` | 当前用户任务列表 |
| `GET` | `/v1/billing/usage` | 用量记录 |
| `GET` | `/v1/billing/pricing-rules` | 价格规则 |
| `GET` | `/v1/billing/summary` | 账单摘要 |
| `GET` | `/v1/billing/invoice` | 账单明细 |
| `GET` | `/v1/webhooks` | Webhook 投递 |
| `POST` | `/v1/webhooks/{delivery_id}/retry` | 重试 Webhook |
| `GET` | `/v1/alerts` | 告警 |
| `GET` | `/v1/safety-events` | 安全事件 |
| `GET` | `/v1/request-logs` | 请求日志 |
| `GET` | `/v1/governance/limits` | 治理限制 |

### 12.2 管理员侧

管理员侧接口较多，按模块使用：

| 模块 | 代表接口 |
| --- | --- |
| Dashboard | `/v1/admin/dashboard`、`/v1/admin/analytics` |
| Readiness | `/v1/admin/readiness`、`/v1/admin/final-acceptance-matrix`、`/v1/admin/delivery-package` |
| Connector | `/v1/admin/connector-registry`、`/v1/admin/external-connector-manifest`、`/v1/admin/connector-conformance-report` |
| Account | `/v1/admin/account-onboarding`、`/v1/admin/account-setup-quickstart`、`/v1/admin/accounts/*` |
| Provider | `/v1/admin/providers/*`、`/v1/admin/provider-templates/*`、`/v1/admin/provider-capabilities` |
| Model | `/v1/admin/logical-models`、`/v1/admin/model-mappings` |
| Jobs | `/v1/admin/jobs`、`/v1/admin/media-jobs/*` |
| Assets | `/v1/admin/assets`、`/v1/admin/assets/self-test-storage` |
| Billing | `/v1/admin/pricing-rules`、`/v1/admin/billing-invoices`、`/v1/admin/provider-costs` |
| Governance | `/v1/admin/user-limit-policies`、`/v1/admin/circuit-breakers` |
| Safety | `/v1/admin/safety-policies`、`/v1/admin/safety-events` |
| Audit | `/v1/admin/request-logs`、`/v1/admin/provider-contracts` |
| Webhook | `/v1/admin/webhooks`、`/v1/admin/webhooks/retry-failed` |
| Config | `/v1/admin/config-export`、`/v1/admin/config-import` |
