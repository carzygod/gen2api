# Web Cookie / Agent Provider 账号添加体系二次复查

复查日期：2026-06-09
源码范围：`media2api/main.py`、`media2api/services_oauth_sessions.py`、`media2api/services_connector_registry.py`、`media2api/services_account_import.py`

## 1. 明确纠偏结论

本产品不再按“OAuth / token / subscription / connector base_url”组织账号体系。首期账号资源只保留两类：

| 资源类型 | 用户真正提供什么 | 平台怎么保存 |
| --- | --- | --- |
| `web_cookie_provider` | 本人已授权的 Web cookie、cookie jar、session token、Discord/MJ guild/channel 任务通道材料 | `auth_method=cookie_secret`，敏感值加密成 `secret://...`，资源画像写入 `resource_profile` |
| `agent_provider` | Codex/Gemini/Qwen/Antigravity/Grok/MCP/本地 runner 等 Agent profile、credential cache、runtime 配置或 `agent://...` 引用 | `auth_method=agent_provider_credential`，敏感值加密成 `secret://...` 或保存外部 `agent://...` 引用 |

`OAuth`、`CLI credential`、`MCP config`、`token ref`、`subscription_url`、`self_hosted_endpoint` 只能作为兼容导入字段或 Agent Provider 内部材料，不再作为产品主路径的独立鉴权方式展示。

`base_url`、`endpoint`、`runner_url` 只属于执行层。只有对应开源项目明确要求外部 runner、sidecar、CLIProxy、MCP-to-HTTP 服务地址时才填写，不得作为所有平台通用必填项。

`secret://...` 不是绕过资源类型的万能引用。平台会查已托管 secret 的真实 `kind`：`kind=cookie` 只能落到 `web_cookie_provider`，`kind=agent_provider` 只能落到 `agent_provider`；旧引用或明文材料归档成 secret 后也必须遵守这个绑定关系。

## 2. 平台逐项对照

| Provider | 归一资源类型 | 用户应填字段 | 上游开源生态依据 | 明确判断 |
| --- | --- | --- | --- | --- |
| `openai_image` | `web_cookie_provider` 优先，可选 `agent_provider` | ChatGPT Web cookie/header/cookie jar；或 Codex Agent profile | ChatGPT/Codex Web-to-API、Codex proxy 类项目通常依赖 Web 登录态或 CLI/Agent profile | 不应让用户填官方 OpenAI API key；执行器地址仅在使用 chatgpt2api/codex-proxy sidecar 时出现 |
| `gemini` | `agent_provider` | Gemini CLI/Antigravity profile、credential cache、`agent://` 引用 | geminicli2api、CLIProxyAPI、CliRelay、AIClient2API 类项目围绕 CLI/OAuth cache/agent runtime | OAuth 只是 Agent Provider credential 的来源，不单独作为产品主路径 |
| `qwen` | `agent_provider` | Qwen Code profile、credential cache、`agent://` 引用 | Qwen Code / CLI relay / AIClient2API 生态以本地 CLI/Agent 授权为主 | 不应默认推荐 DashScope/API key；如导入旧 token，也归入 Agent Provider |
| `grok` | `web_cookie_provider` 优先，可选 `agent_provider` | Grok Web/Build cookie/session；或 Grok Agent/MCP profile | Grok Web wrapper 与 Grok MCP/agent 项目并存 | 不是 OAuth 平台；主入口是 Web session 或 Agent profile |
| `jimeng` | `agent_provider` | Volcengine Ark/Jimeng API key/ref 或 Jimeng Agent profile | ComfyUI-Jimeng-API 使用 `api_keys.json`/Ark API key；当前复核未证明必须要求 Web cookie | 不应要求通用 base_url；主账号表单走 Agent Provider credential/ref |
| `kling` | `agent_provider` | `KLING_ACCESS_KEY` + `KLING_SECRET_KEY` 或 MCP/Agent profile | kling-api、mcp-kling、ComfyUI Kling 类项目以 access key / secret key / MCP config 为主 | MCP config 归入 Agent Provider，不单独暴露成第三种账号类型 |
| `midjourney` | `web_cookie_provider` | Discord/MJ session 或 user token、guild_id、channel_id | midjourney-proxy 类项目通常要求 Discord 会话、服务器、频道 | 必须按 channel/session 建账号资源，严格并发 1 和审计 |
| `seedream_proxy` | `agent_provider` | Seedream/Seedance API key/ref 或 Agent profile | ComfyUI-Jimeng-API、seedance-api 等项目以 API key/ref 或执行层托管凭据为主 | 不在主账号表单要求 Web cookie；需要执行层时仍归入 Agent Provider |
| `runway` | `agent_provider` | UseAPI credential/ref 或 Runway authorized Agent profile | n8n-nodes-useapi 等项目要求 UseAPI credential 或外部授权 helper | 不在主账号表单收集 Runway 密码/cookie；第三方聚合材料只能作为 Agent 后端材料 |
| `luma` | `agent_provider` | Luma MCP config、Agent credential 或 `agent://` 引用 | luma MCP/server 类项目以工具/agent 配置为主 | 不做独立 API key 类型，统一归到 Agent Provider |
| `pollinations` | `agent_provider` | 公共/自托管 Pollinations runner profile、可选 token/ref | Pollinations 更像 fallback/agent 后端 | 非账号体系中心；作为 Agent Provider 后端或 fallback |
| `openrouter_image` | `agent_provider` | 托管 channel credential、Agent profile 或 `agent://` 引用 | OpenRouter/new-api/one-api 属于 channel/聚合生态 | 不能成为官方 key 聚合器主路径；作为 Agent 后端材料 |
| `fal_replicate` | `agent_provider` | fal/Replicate SDK wrapper profile、token ref 或 `agent://` 引用 | fal/Replicate SDK 项目常见是 SDK credential | 作为 Agent Provider 后端；同步 SDK 调用需包装为异步 MediaJob |
| `amux_qwen` | `agent_provider` | AMux/Qwen Agent profile、Qwen credential cache | Qwen/AMux CLI/Agent wrapper 生态 | 不再默认强调 OAuth/token，统一 Agent Provider |
| `flux_stability` | `agent_provider` | ComfyUI/FLUX/SD workflow、MCP config、本地 runner profile | ComfyUI、SD WebUI、FLUX、自托管 GPU runner | 自托管 endpoint 是 runner 位置，不是第三种账号资源 |

## 3. 源码已按本结论收口的点

| 模块 | 调整 |
| --- | --- |
| `services_connector_registry.py` | `REFERENCE_AUTH_TYPES` 收窄为 `cookie_secret`、`agent_provider_credential`；provider guide 推荐方法只返回这两类 |
| `main.py` | account onboarding、批量导入、quickstart、workflow 默认 `auth_method` 改为 `agent_provider_credential`；管理台主入口拆为 Web Cookie 与 Agent Provider |
| `services_account_import.py` | 旧的 OAuth/CLI/MCP/token/subscription 字段只作为兼容解析，归一后仍是 Cookie 或 Agent Provider |
| `services_oauth_sessions.py` | 授权会话回调收到旧格式字段时归一为 Cookie 或 Agent Provider，不再扩散成独立主路径 |

补充要求：开源项目画像中标记为 `required` 的平台专属字段必须被后端统一强校验，覆盖账号向导、批量导入、直接建账号、模板安装/激活、配置导入、授权会话完成和授权回调。系统不再允许用户只提交一个泛化 connector/baseURL 或空 profile 来绕过真实登录材料，例如 Midjourney 必须提供 Discord 会话材料以及 `guild_id`、`channel_id`。

## 4. 对用户字段的明确口径

用户只需要先回答两个问题：

1. 这是 Web 会话资源吗？如果是，填 cookie/session/channel，走 `web_cookie_provider + cookie_secret`。
2. 这是 Agent/CLI/MCP/runner 资源吗？如果是，填 agent profile/runtime/config，走 `agent_provider + agent_provider_credential`。

只有在开源项目文档明确说“需要启动一个 HTTP runner/sidecar，并填写其服务地址”时，才显示或填写 `base_url` / `endpoint`。否则不要求用户填写。

## 5. 仍需注意

- 代码中 `/v1/admin/oauth-sessions` 路径名保留是兼容历史接口，管理台和文档必须称为“授权会话”。
- 旧的订阅清单导入能力可以保留，但导入结果必须归一到 `web_cookie_provider` 或 `agent_provider`。
- 文档和 UI 不应再把 API key、OAuth reference、subscription URL、MCP config、self-hosted endpoint 当作平级账号类型。
