# OpenAI 图片账户绑定教程

本文专门说明如何把本人已授权的 OpenAI / ChatGPT WebAuth 会话绑定到 `openai_image` 账号池，并调度 `gpt-image-2` 完成文生图。本文只覆盖你自己有权使用的账号和浏览器会话，不包含绕过登录、验证码、风控、Cloudflare challenge 或获取他人 cookie 的流程。

## 1. 适用范围

当前源码中，OpenAI 图片能力对应 provider 为 `openai_image`：

| 项目 | 值 |
| --- | --- |
| Provider | `openai_image` |
| 主资源类型 | `web_cookie_provider` |
| 可选资源类型 | `agent_provider` |
| 主鉴权方式 | `cookie_secret` |
| 目标模型 | `gpt-image-2`, `codex-gpt-image-2` |
| 支持操作 | `text_to_image`, `image_to_image`, `image_edit` |
| 推荐逻辑模型 | `t2i-pro -> gpt-image-2`, `image-edit -> gpt-image-2` |

首选路径是导入本人已登录的 ChatGPT / OpenAI Web 会话材料，也就是 WebAuth 相关 cookie、cookie header 或 cookie jar。使用 Codex Agent / CLI profile 时走 `Agent Provider`，但本文重点写 WebAuth 绑定。

## 2. 绑定前准备

你需要准备：

1. 一个能正常访问 ChatGPT 图像功能的 OpenAI / ChatGPT 账号。
2. 一台你能打开浏览器 DevTools 的电脑。
3. media2api 管理后台地址，例如 `http://192.168.31.26:18082/admin`。
4. 管理员密码，当前测试环境为 `dev-admin-key`。
5. 下游调用 API Key。可以在后台“用户与鉴权”里创建调用密钥。

安全要求：

- 只复制你本人账号的会话材料。
- 不要把 cookie、WebAuth token、refresh token 发给别人。
- 不要把真实 cookie 写进文档、Issue、聊天记录或 Git。
- 如果怀疑 cookie 泄露，立刻在 OpenAI / ChatGPT 账号里退出所有设备并重新登录。

## 3. OpenAI WebAuth 去哪里拿

OpenAI WebAuth 不是平台让你填写账号密码，而是使用你已经在浏览器里完成登录后的会话材料。media2api 需要的是浏览器请求里的 Cookie header，或等价的 cookie jar JSON。

推荐用 Chrome / Edge 获取。

### 3.1 从 Network 复制 Cookie Header

1. 打开 Chrome 或 Edge。
2. 访问 `https://chatgpt.com/`，确认你已经登录，并且可以进入图像生成入口。
3. 按 `F12` 打开 DevTools。
4. 进入 `Network` 面板。
5. 勾选 `Preserve log`，方便刷新后保留请求。
6. 刷新页面。
7. 在请求列表里点击一个发往 `chatgpt.com` 或 OpenAI Web 后端的请求。通常可以选择页面主文档请求、`/backend-api/`、`/ces/`、`/conversation`、`/gizmos` 等同域请求。
8. 在右侧 `Headers` -> `Request Headers` 中找到 `cookie:`。
9. 复制 `cookie:` 后面的完整字符串，不要只复制其中一小段。
10. 同一个请求里也复制 `user-agent:`，后续排障时很有用。

得到的 Cookie header 形态类似：

```text
__Secure-next-auth.session-token=...; __Host-next-auth.csrf-token=...; oai-did=...; other_cookie=...
```

实际名称会随 OpenAI 页面变化而变化，不要强行要求某个固定 cookie 名。以当前已登录浏览器发出的请求为准。

### 3.2 从 Application Cookies 拼 Cookie Header

如果 `Network` 面板没有显示 `cookie:`：

1. 在 DevTools 里进入 `Application`。
2. 左侧展开 `Storage` -> `Cookies`。
3. 点击 `https://chatgpt.com`。
4. 选中与登录会话相关的 cookie。
5. 按 `name=value` 拼接，并用分号加空格连接。

示例格式：

```text
name1=value1; name2=value2; name3=value3
```

这种方式更容易漏字段，优先使用 Network 面板复制完整 Cookie header。

### 3.3 cookie jar JSON 形态

如果你使用浏览器插件或内部工具导出 cookie jar，也可以把 cookie jar 包成 JSON。建议至少包含域名、Cookie header 和 User-Agent：

```json
{
  "cookie_header_or_cookie_jar": "name1=value1; name2=value2; name3=value3",
  "user_agent": "Mozilla/5.0 ...",
  "domain": "chatgpt.com",
  "source": "browser_devtools_network_request"
}
```

如果工具导出的是数组，也可以保留数组，但建议同时提供 `cookie_header_or_cookie_jar` 字段，便于后端校验。

```json
{
  "cookie_header_or_cookie_jar": "name1=value1; name2=value2",
  "cookies": [
    {"name": "name1", "value": "value1", "domain": ".chatgpt.com", "path": "/"},
    {"name": "name2", "value": "value2", "domain": ".chatgpt.com", "path": "/"}
  ],
  "user_agent": "Mozilla/5.0 ..."
}
```

## 4. 在管理后台绑定 OpenAI 图片账号

1. 打开管理后台：`http://192.168.31.26:18082/admin`。
2. 使用管理员账号登录。
3. 左侧点击“授权资源”。
4. 平台选择 `OpenAI / ChatGPT / Codex image resources (openai_image)`。
5. 先看“对照指南”，确认推荐凭据类型包含 `cookie_secret`。
6. 切到 `Web Cookie` 页签。
7. 填写账号信息：

| 字段 | 建议值 |
| --- | --- |
| 账号 ID | `acct_openai_image_web_01`，也可以留空自动生成 |
| 账号标签 | `OpenAI ChatGPT WebAuth image 01` |
| Cookie 域 / 平台域 | `chatgpt.com` |
| 过期时间 | 不确定可以留空；知道过期时间则填 ISO 时间 |
| 并发 | 初始填 `1` |
| 授权材料 | 粘贴 Cookie header 或 JSON |

推荐授权材料 JSON：

```json
{
  "cookie_header_or_cookie_jar": "__Secure-next-auth.session-token=...; other_cookie=...",
  "user_agent": "Mozilla/5.0 ...",
  "domain": "chatgpt.com",
  "source": "browser_devtools_network_request"
}
```

8. 点击“保存 Web Cookie”。
9. 页面底部“返回结果”出现成功响应后，系统会生成 `secret://...` 凭据引用。
10. 左侧进入“账号池”，确认账号已出现，平台为 `openai_image`。
11. 运行“账号验收套件”，确认凭据可用。

保存成功后的账号资源应类似：

```json
{
  "provider_id": "openai_image",
  "account_id": "acct_openai_image_web_01",
  "resource_type": "web_cookie_provider",
  "auth_method": "cookie_secret",
  "credential_ref": "secret://secret_acct_openai_image_web_01",
  "supported_operations": ["text_to_image", "image_to_image", "image_edit"],
  "supported_provider_models": ["gpt-image-2", "codex-gpt-image-2"]
}
```

## 5. 通过管理接口绑定

如果你不想走页面，可以直接调用账号接入接口。下面示例中的 cookie 必须替换为你自己的真实会话材料。

```bash
curl -X POST "http://192.168.31.26:18082/v1/admin/account-onboarding" \
  -H "Authorization: Bearer dev-admin-key" \
  -H "Content-Type: application/json" \
  -d '{
    "provider_id": "openai_image",
    "account_id": "acct_openai_image_web_01",
    "label": "OpenAI ChatGPT WebAuth image 01",
    "resource_type": "web_cookie_provider",
    "resource_profile": {
      "cookie_domain_scope": "chatgpt.com",
      "input_requirements": [
        "ChatGPT Web cookie/header 或 cookie jar"
      ]
    },
    "auth_method": "cookie_secret",
    "credential_kind": "cookie",
    "credential_value": {
      "cookie_header_or_cookie_jar": "__Secure-next-auth.session-token=...; other_cookie=...",
      "user_agent": "Mozilla/5.0 ...",
      "domain": "chatgpt.com"
    },
    "supported_operations": ["text_to_image", "image_to_image", "image_edit"],
    "supported_provider_models": ["gpt-image-2", "codex-gpt-image-2"],
    "concurrency_limit": 1,
    "sync_capabilities": true,
    "run_health_check": true
  }'
```

注意：

- 不要把 `provider_base_url` 当作必填项。
- 只有你实际部署了 `chatgpt2api`、`codex-proxy` 这类 sidecar，并且该 sidecar 要求服务地址时，才填写执行器地址。
- WebAuth cookie 本身属于账号资源，不是下游调用 API Key。

## 6. 调度 gpt-image-2 生图

绑定成功后，下游用户可以通过两种接口生成图片。

### 6.1 OpenAI-compatible 图片接口

适合已有 OpenAI 图片调用代码的客户端。

```bash
curl -X POST "http://192.168.31.26:18082/v1/images/generations" \
  -H "Authorization: Bearer <你的下游调用API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-image-2",
    "prompt": "A clean product photo of a translucent mechanical keyboard on a white desk, soft studio lighting",
    "size": "1024x1024",
    "n": 1,
    "response_format": "url"
  }'
```

返回成功时会包含：

```json
{
  "created": 1780000000,
  "job_id": "job_xxx",
  "data": [
    {
      "url": "http://.../v1/assets/asset_xxx/content"
    }
  ]
}
```

如果需要 base64：

```json
{
  "model": "gpt-image-2",
  "prompt": "A cinematic image of a glass greenhouse at sunrise",
  "size": "1024x1024",
  "n": 1,
  "response_format": "b64_json"
}
```

### 6.2 原生媒体任务接口

适合需要异步状态、任务事件、重试、资产管理的业务系统。

```bash
curl -X POST "http://192.168.31.26:18082/v1/media-jobs" \
  -H "Authorization: Bearer <你的下游调用API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{
    "operation": "text_to_image",
    "model": "gpt-image-2",
    "params": {
      "prompt": "A minimalist poster of an electric sports car driving through neon rain",
      "size": "1024x1024",
      "quality": "high",
      "n": 1
    },
    "wait": false
  }'
```

查询任务：

```bash
curl "http://192.168.31.26:18082/v1/media-jobs/<job_id>" \
  -H "Authorization: Bearer <你的下游调用API_KEY>"
```

查看事件：

```bash
curl "http://192.168.31.26:18082/v1/media-jobs/<job_id>/events" \
  -H "Authorization: Bearer <你的下游调用API_KEY>"
```

查看 provider 尝试记录：

```bash
curl "http://192.168.31.26:18082/v1/media-jobs/<job_id>/attempts" \
  -H "Authorization: Bearer <你的下游调用API_KEY>"
```

## 7. 账号调度逻辑

当下游请求 `model=gpt-image-2` 时，系统会按模型映射和账号池选择可用账号：

1. 逻辑模型或平台模型匹配到 `openai_image`。
2. 账号池筛选 `provider_id=openai_image` 且状态可用的账号。
3. 校验 `credential_ref` 是否可用。
4. 检查并发租约和额度。
5. 将任务交给 provider / connector。
6. 生成结果保存为 media asset。
7. 返回资产 URL、base64 或任务状态。

如果你有多个 OpenAI WebAuth 账号，可以重复添加多个账号，例如：

| 账号 ID | 标签 | 并发 |
| --- | --- | --- |
| `acct_openai_image_web_01` | ChatGPT Plus image 01 | `1` |
| `acct_openai_image_web_02` | ChatGPT Team image 02 | `1` |
| `acct_openai_image_codex_01` | Codex Agent image 01 | `1` |

初期建议每个 WebAuth 账号并发为 `1`，真实稳定后再逐步调高。

## 8. 常见错误

| 错误 | 原因 | 处理 |
| --- | --- | --- |
| `PROVIDER_REQUIRED_INPUT_MISSING` | 没有提交 `cookie_header_or_cookie_jar` | 重新按 Network 面板复制完整 Cookie header |
| `PROVIDER_AUTH_METHOD_NOT_ALLOWED` | 鉴权方式选错 | `openai_image` WebAuth 走 `cookie_secret` |
| `PROVIDER_BASE_URL_NOT_ALLOWED` | 没有 sidecar 却提交了 base URL | 删除执行器地址，只保留 cookie/session |
| `ACCOUNT_CREDENTIAL_REF_RESOURCE_MISMATCH` | `credential_kind` 与 `resource_type` 不匹配 | WebAuth 使用 `resource_type=web_cookie_provider` 和 `credential_kind=cookie` |
| `ACCOUNT_NOT_AVAILABLE` | 账号不可租约 | 检查账号状态、cookie 是否过期、并发是否占满 |
| `PROVIDER_DISABLED` | provider 未启用或模板未激活 | 在后台启用 `openai_image` 模板并同步能力 |
| `PROVIDER_TIMEOUT` | 上游或 sidecar 超时 | 检查 cookie 是否仍有效，必要时重新登录并更新凭据 |
| `JOB_NOT_FOUND` | 查询了不存在或不属于当前用户的任务 | 检查下游 API Key 和 job_id |

## 9. 更新 WebAuth 凭据

WebAuth cookie 会过期。推荐流程：

1. 用原浏览器重新登录 ChatGPT。
2. 重新按 `Network` 面板复制 Cookie header 和 User-Agent。
3. 在后台找到对应账号或凭据。
4. 重新保存 Web Cookie 材料。
5. 运行账号验收套件。
6. 提交一条 `gpt-image-2` 小样本任务确认恢复。

不要把过期 cookie 长期保留在账号池里，否则调度器会反复选中不可用账号，影响任务成功率。

## 10. 最小验收清单

| 检查项 | 通过标准 |
| --- | --- |
| `openai_image` provider | 已启用 |
| WebAuth 账号 | 账号池中存在 `provider_id=openai_image` 账号 |
| 凭据引用 | `credential_ref` 为 `secret://...` |
| 支持模型 | `gpt-image-2` 已在账号或 provider 模型中 |
| 支持操作 | 至少包含 `text_to_image` |
| 验收套件 | 账号验收通过或至少没有凭据缺失错误 |
| 生图请求 | `/v1/images/generations` 或 `/v1/media-jobs` 能生成资产 |
| 安全 | 文档、日志、截图中没有真实 cookie |
