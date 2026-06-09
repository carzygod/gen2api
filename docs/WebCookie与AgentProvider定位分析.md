# Web Cookie 与 Agent Provider 产品定位分析

编写日期：2026-06-09
适用范围：`gen2api/media2api` 的 Web Cookie 转 API、Agent Provider 转 API、图片/视频生成反代 API。

## 1. 修正后的核心判断

本产品不是普通聚合网关，也不是只接收外部 connector 引用的平台。产品核心应收敛为两类上游资源：

| 核心资源 | 含义 | 产品职责 |
|---|---|---|
| Web Cookie Provider | 用户已授权的浏览器 cookie、session、Web storage、Discord/MJ 任务通道 session、网页侧登录态 | 原生导入、加密托管、脱敏展示、过期检测、健康检查、账号池、并发限制、任务轮询、资产转存 |
| Agent Provider | Codex、Gemini CLI、Qwen Code、Antigravity、Grok CLI/Build 等本地或远程 agent runtime 与授权 profile | 原生登记 agent profile、credential reference、runtime、工作目录、隔离策略、能力探测、账号池、失败恢复 |

因此，`connector base_url` 不是产品中心。它只是执行层地址，用来承载网页自动化、任务轮询、CLI wrapper、MCP-to-HTTP 或 agent runtime。真正的资源主体是 cookie/session 和 agent credential/profile。

## 2. 开源项目模式与产品启发

| 开源项目类型 | 代表仓库 | 它们通常让用户填什么 | 对本产品的结论 |
|---|---|---|---|
| API 网关/渠道聚合 | `new-api`、One API 类项目 | channel `base_url`、API key、模型映射、倍率、渠道状态 | 适合借鉴渠道、路由、计费、健康检查；但它们的核心是 API key/channel，不是我们的核心资源 |
| WebUI 多后端平台 | `open-webui` | `OLLAMA_BASE_URL`、`OPENAI_API_BASE_URL`、`COMFYUI_BASE_URL`、`AUTOMATIC1111_BASE_URL` | 说明 base URL 配置是常见做法；在本产品里应作为 connector/runner 配置，而不是替代 cookie/agent 资源 |
| sub2api/every2api | `sub2api`、`every2api` forks | 订阅源、账号清单、上游地址、统一 API key | 适合借鉴订阅清单、批量导入、账号池、额度与路由；导入后仍应归一为 Web Cookie 或 Agent Provider |
| ChatGPT/Codex 转 API | `chatgpt2api`、`codex-proxy`、`codexProapi`、`ima2-gen` 等 | ChatGPT/Codex 登录态、CLI/OAuth cache、sidecar 地址，具体随项目而定 | `openai_image` 首选路径应是 ChatGPT Web Cookie 与 Codex Agent Provider，目标是 `gpt-image-2` / `codex-gpt-image-2` |
| CLI/Agent 转 API | `CLIProxyAPI`、`CliRelay`、`AIClient2API`、`geminicli2api` | 本地 CLI profile、OAuth cache、agent config、服务端口 | 这是 Agent Provider 主线：平台应管理 agent profile 与 runtime 隔离，而不是只记录一个 token |
| Midjourney 代理 | `novicezk/midjourney-proxy`、`PlexPt/midjourney-proxy`、`trueai-org/midjourney-proxy` | Discord/MJ session、guild、channel、user token、proxy secret | 这是 Web Cookie/任务通道主线：平台要把 session/channel 作为账号资源，严格限并发、审计和过期检测 |
| 视频平台 wrapper/MCP | `kling-api`、`mcp-kling`、`luma-ai-mcp-server`、`MiniMax-MCP-JS` | Web/JWT/API key/MCP config，依项目而定 | 能力可进入 Agent Provider 或 Web Cookie Provider；MCP 是 agent runtime 的一种形式 |
| 聚合器/SDK/自托管 | `pollinations`、`fal-js`、`replicate-python`、`ComfyUI`、`stable-diffusion-webui` | API key、endpoint、模型文件、GPU 服务地址 | 非首期核心。可作为 fallback、能力对照或 Agent Provider 后端，不应主导账号体系 |

## 3. 对“是否要求用户填 base_url”的重新回答

其他开源项目确实经常要求配置 `base_url`、`endpoint`、`server` 或 channel 地址，但这通常是“运行服务在哪里”的问题，不是“账号资源是什么”的问题。

本产品应该拆成两层：

| 层级 | 用户/管理员填写内容 | 说明 |
|---|---|---|
| 资源层 | Web cookie/session、cookie jar、Web session ref、Agent profile、CLI credential、MCP config | 这是本产品核心，必须原生建模 |
| 执行层 | connector base URL、agent runtime endpoint、sidecar 地址、MCP-to-HTTP 地址 | 这是执行入口，可选且可由部署自动发现 |

所以，用户不应该只被要求填写“连接器 base_url”。更准确的接入入口应该是：

1. 选择 provider。
2. 选择资源类型：`web_cookie_provider` 或 `agent_provider`。
3. 导入 cookie/session 或登记 agent profile。
4. 可选填写 connector/runner base URL。
5. 运行能力探测、健康检查、quota 检查和真实样本验收。

## 4. 资源模型补充

Web Cookie Provider 至少需要：

- `provider_id`
- `account_id`
- `credential_kind = cookie_secret`
- `cookie_domain_scope`
- `session_expires_at`
- `last_auth_check_at`
- `risk_level`
- `concurrency_limit`
- `daily_quota`
- `cooldown_until`
- `connector_base_url`，仅在对应项目要求外部 runner/sidecar 服务地址时填写
- `supported_operations`
- `supported_provider_models`

Agent Provider 至少需要：

- `provider_id`
- `account_id`
- `credential_kind = agent_provider_credential`
- `agent_runtime`
- `profile_ref`
- `workspace_policy`
- `network_policy`
- `concurrency_limit`
- `health_check_command` 或 `health_endpoint`
- `supported_operations`
- `supported_provider_models`
- `connector_base_url`，仅在对应项目要求外部 runner/sidecar 服务地址时填写

## 5. 对当前文档和实现的结论

当前源码已有一些可复用基础：

- secret kind 已出现 `cookie`。
- 账号导入能识别旧的 `websession://`、`cli://`、`vault://`、`secret://` 等引用，但入库必须归一为 Web Cookie 或 Agent Provider。
- provider/account/mapping/lease/quota/health/preflight/acceptance 已经形成框架。
- connector base URL 已经能作为执行层配置。

但按新定位仍需补强：

| 缺口 | 必要改动 |
|---|---|
| Cookie 只是 secret kind，不是完整资源模型 | 增加 Web Cookie provider resource profile、过期检测、域名 allowlist、cookie jar 解析、加密导入 UI |
| Agent 只是 CLI credential reference | 增加 Agent Provider profile、runtime、工作目录隔离、health probe、能力探测 |
| OAuth 命名过窄 | 管理台和文档改称“授权会话 / Web 会话 / Agent Provider” |
| base URL 被误认为核心输入 | UI 拆成资源层和执行层，base URL 作为可选 runner/connector 配置 |
| 聚合器/自托管权重过高 | 文档中降级为 fallback 或能力对照，首期验收聚焦 Web Cookie 与 Agent Provider |

## 6. 当前实现收口

本轮实现后，账号资源入口应按下面规则验收：

| 项目 | 当前要求 |
|---|---|
| 账号资源主类型 | 只允许产品主线使用 `web_cookie_provider` 与 `agent_provider` |
| 开源项目分类 | 可以保留 sub2api、MCP、聚合器、自托管、Web wrapper 等分类，但它们只能影响导入格式、执行层和风险标签 |
| 用户必填材料 | 必须按对应开源项目实际字段展示，例如 cookie header/cookie jar、agent profile、guild/channel、MCP config |
| 执行器地址 | 只有项目明确要求 runner、sidecar、CLIProxy、MCP-to-HTTP 服务地址时才展示或要求填写 |
| 管理台入口 | “授权资源”下拆成 Web Cookie、Agent Provider、授权会话、批量导入，不再把所有平台塞进单个 OAuth 表单 |
| 服务端接口 | `/v1/admin/platform-input-requirements` 输出各 provider 的实际输入要求，`/v1/admin/account-onboarding` 保存 `resource_type` 和 `resource_profile` |
