# GitHub 开源项目调研表：订阅转 API / Web 转 API / 图片视频反代 API

文档版本：v1.0
编写日期：2026-06-09
源码基线：`media2api/catalog.py`、`media2api/provider_templates.py`
目标：围绕 `gen2api/media2api` 当前声明的图片与视频模型类型，系统梳理 GitHub 开源社区中与 Web Cookie 转 API、CLI/Agent Provider 转 API、媒体生成反代 API 相关的项目，并提取可用于构建“Web Cookie + Agent Provider 图片/视频生成版 sub2api 平台”的能力。

## 1. 范围与边界

本表覆盖公开 GitHub 可检索项目中，与以下方向强相关的仓库：

| 方向 | 纳入标准 | 不纳入或仅低优先级参考 |
|---|---|---|
| Web Cookie 转 API | 通过浏览器 cookie/session、Web storage、网页会话、浏览器自动化、Web SDK、第三方反代或 sidecar，把上游网页产品能力转换为 API | 需要绕过风控、破解、批量薅号、验证码规避、窃取会话的实现细节 |
| Agent Provider 转 API | 把 Gemini CLI、Codex CLI、Qwen Code、Antigravity、Grok CLI/Build 等 Agent/CLI 授权资源转换为 OpenAI-compatible 或媒体任务 API | 仅普通聊天 UI、没有 API 暴露能力的项目 |
| 订阅转 API | 把 ChatGPT、Claude、Gemini、Codex、Antigravity、Qwen Code、Grok 等订阅、OAuth 或 Agent 额度转换为 API | 仅作为 Web Cookie 与 Agent Provider 的账号池/订阅清单参考，不作为独立主线 |
| 图片/视频反代 API | 支持文生图、图生图、图片编辑、文生视频、图生视频、视频延展、Midjourney 任务通道等能力 | 只支持纯文本聊天且没有媒体扩展空间的项目 |
| 聚合网关 | 提供渠道、账号池、模型映射、计费、限流、OpenAI 兼容接口、管理后台 | 非首期核心；只抽取账号池、渠道、路由、计费等工程模式 |
| 自托管模型 API | 可作为 Agent Provider 后端或 fallback 的开源推理服务或 MCP/API 服务 | 非首期核心；纯论文、纯训练代码、没有服务接口的仓库 |

说明：GitHub 搜索结果会随时间变化，本表按 2026-06-09 的公开可检索项目整理；“所有”在执行上理解为“围绕当前源码模型类型与用户需求，尽量覆盖主流且可验证的公开项目类别”。表中允许记录 Web cookie/session、Agent credential/profile 的字段类型、生命周期和治理要求，但不会记录验证码绕过、风控规避、批量账号获取、窃取会话或非授权 token 获取步骤。

## 2. 当前源码要求覆盖的模型类型

| 源码 Provider | 当前目标模型/能力 | 操作类型 | 调研时必须覆盖的开源生态方向 |
|---|---|---|---|
| `openai_image` | `gpt-image-2`, `codex-gpt-image-2`, ChatGPT Images | `text_to_image`, `image_to_image`, `image_edit` | Codex/ChatGPT 订阅转图像 API、gpt-image 兼容代理、Codex sidecar、OpenAI-compatible 图片服务 |
| `gemini` | `veo-3.1`, `nano-banana`, `nano-banana-pro`, `imagen-4` | 图片生成/编辑、文生视频、图生视频 | Gemini CLI/Antigravity 转 API、Gemini OpenAI-compatible 代理、Veo 视频 connector |
| `grok` | `grok-imagine-image`, `grok-imagine-video` | 图片生成、图生图、文生视频、图生视频 | Grok Web/Build/CLI 转 API、Grok Imagine connector、xAI API/MCP 代理 |
| `qwen` | `qwen-image`, `qwen-image-edit`, `qwen-video`, `wan-video` | 图片生成/编辑、文生视频、图生视频 | Qwen Code 转 API、DashScope/Qwen Image/Wan connector、本地 Wan 推理服务 |
| `jimeng` | `seedream`, `seededit`, `seedance-i2v`, `seedance-t2v` | 图片生成/编辑、文生视频、图生视频 | Jimeng/Dreamina/Seedream/Seedance 网页或第三方 connector、火山/Ark 兼容服务 |
| `kling` | `kling-i2v-standard`, `kling-i2v-hq`, `kling-t2v`, `kling-extend` | 文生视频、图生视频、视频延展 | Kling Web/官方开放 API/第三方 connector、ComfyUI 节点、MCP 服务 |
| `luma` | `luma-dream-machine`, `luma-extend` | 文生视频、图生视频、视频延展 | Luma Dream Machine API/MCP、useapi/n8n 代理、视频生成 connector |
| `runway` | `runway-gen3`, `runway-gen4`, `runway-extend` | 文生视频、图生视频、视频延展 | Runway Gen-3/Gen-4 第三方 API connector、useapi/n8n、视频生成聚合服务 |
| `midjourney` | `mj-v6`, `mj-v7`, `niji`, variation/blend/describe | 文生图、图生图/变体 | Midjourney Discord 任务通道代理、Midjourney Proxy、OpenAI-compatible MJ 网关 |
| `pollinations` | `gpt-image-2`, `nanobanana`, `seedream`, `qwen-image`, `grok-imagine`, `veo`, `seedance`, `wan` | 图片+视频聚合 | Pollinations 自托管/聚合 API、模型注册、无密钥/可选密钥策略 |
| `openrouter_image` | `gpt-image`, `nano-banana`, `seedream`, `recraft`, `flux`, `qwen-image` | 图片生成、图生图 | OpenRouter 兼容渠道、New API/One API 渠道接入、OpenAI-compatible 图片聚合 |
| `fal_replicate` | `nano-banana`, `qwen-image`, `seedream`, `flux`, `recraft`, `wan-video` | 图片+视频聚合 | fal/Replicate API connector、媒体任务异步化、模型市场路由 |
| `seedream_proxy` | `seedream-3`, `seedream-4`, `seedream-5`, `seededit` | 图片生成、图生图、图片编辑 | Seedream/Seededit 代理、Jimeng/Volcengine/第三方 connector |
| `amux_qwen` | `qwen-image`, `qwen-image-edit`, `wan-image` | 图片生成、图生图、图片编辑 | Qwen Image、Wan Image、Qwen Code 转 API、第三方 Qwen 图片代理 |
| `flux_stability` | `flux`, `sdxl`, `stable-image`, `controlnet` | 图片生成、图生图、图片编辑 | ComfyUI、FLUX、Stable Diffusion、Stability 兼容 API、自托管推理服务 |

## 3. GitHub 项目明细表

### 3.1 订阅转 API / CLI-Agent 转 API / 通用网关

| # | 项目 | 类型 | 支持平台 | 支持模型/能力 | 覆盖源码类型 | 上游鉴权方式 | 下游鉴权/管理 | 适配结论 |
|---:|---|---|---|---|---|---|---|---|
| 1 | [Wei-Shaw/sub2api](https://github.com/Wei-Shaw/sub2api) | 订阅转 API、账号/额度分发 | ChatGPT/Codex、Claude、Gemini、Antigravity、Grok、Qwen Code 等订阅/CLI/Agent 资源 | 以 OpenAI-compatible 聊天/响应接口为主；可作为图片/视频 connector 的账号池与额度调度参考 | 间接覆盖 `openai_image`, `gemini`, `grok`, `qwen` | 上游通常为 OAuth、CLI 登录态、账号引用或订阅资源引用 | 平台侧 API Key、用户/额度/路由管理 | 高优先级抽取：账号池、订阅资源登记、API key 分发、计费与调度；媒体能力需由专门 connector 补齐 |
| 2 | [emptyinkpot/sub2api](https://github.com/emptyinkpot/sub2api) | `sub2api` 生态实现/派生 | 与 `sub2api` 类似的订阅资源接入 | 以订阅转 OpenAI-compatible API 为主 | 间接覆盖图片/视频 provider | 订阅/OAuth/账号引用 | API Key 或代理服务鉴权 | 作为 `sub2api` 分支生态参考，重点看资源模型差异 |
| 3 | [qixing-jk/all-api-hub](https://github.com/qixing-jk/all-api-hub) | 多平台订阅统一调度 | ChatGPT、Claude、Gemini、Codex、Qwen Code 等 | 聚焦多订阅统一管理、负载均衡、故障转移 | 间接覆盖 `openai_image`, `gemini`, `qwen` | 多账号、OAuth/CLI 资源引用 | 统一 API Key、后台管理 | 可抽取“多订阅资源池 + 统一出口”的需求，不作为媒体 connector 本身 |
| 4 | [B022MC/b022hub](https://github.com/B022MC/b022hub) | 订阅转 API Hub | Codex、Gemini、Claude、Qwen Code 等 | OpenAI-compatible 代理、订阅额度汇聚 | 间接覆盖 `openai_image`, `gemini`, `qwen` | 账号/OAuth/CLI 授权引用 | API Key/Hub 管理 | 作为 sub2api 类型平台竞品参考 |
| 5 | [yunfanxing6/every2api](https://github.com/yunfanxing6/every2api) | 多资源转 API | 多 CLI/网页/订阅资源 | 聚合为 API 调用 | 间接覆盖 | 上游账号/订阅/会话引用 | 统一 API Key | 作为“任何资源转 API”的命名与抽象参考 |
| 6 | [QuantumNous/new-api](https://github.com/QuantumNous/new-api) | 通用 API 管理与分发系统 | OpenAI、Azure、Anthropic、Gemini、OpenRouter、Midjourney Proxy、Suno 等多渠道 | 聊天、Embedding、图像、音频、Midjourney/Suno 任务等，依渠道而定 | 直接/间接覆盖 `openrouter_image`, `midjourney`, `gemini`, `qwen`, 聚合类 provider | 上游渠道 API Key、代理 Base URL、第三方 connector key | 用户 Token、渠道、模型映射、倍率、计费、限流 | 高优先级抽取：渠道模型、令牌、倍率计费、管理后台、失败重试；媒体 provider 需按 gen2api 资产规范重构 |
| 7 | [songquanpeng/one-api](https://github.com/songquanpeng/one-api) | OpenAI API 管理/转发 | OpenAI、Azure、Anthropic、Gemini、Baidu、Qwen、Spark、Doubao 等 | OpenAI-compatible 文本与部分图像/多模态能力，依渠道而定 | 间接覆盖 `gemini`, `qwen`, `openrouter_image` | 上游渠道 API Key | 下游 Token、渠道、用户、额度 | 高优先级抽取：经典渠道/令牌/模型映射模式；媒体任务异步化不足，需要 gen2api 扩展 |
| 8 | [lianluo-esign/ferrogate](https://github.com/lianluo-esign/ferrogate) | OpenAI-compatible 代理/网关 | 多模型服务与 OpenAI-compatible 端点 | 通用 LLM 代理与路由 | 间接覆盖聚合类 provider | 上游 API Key/代理地址 | 统一 API Key/网关鉴权 | 可抽取网关配置与路由，不是媒体生成核心 |
| 9 | [LMRouter/lmrouter](https://github.com/LMRouter/lmrouter) | OpenAI-compatible LLM Router | 多 Provider 路由 | 模型路由、负载均衡、OpenAI-compatible | 间接覆盖 `openrouter_image`, `fal_replicate` 的路由思想 | 上游 Provider API Key | Router API Key | 可抽取模型路由、权重、失败处理 |
| 10 | [poixeai/proxify](https://github.com/poixeai/proxify) | LLM API Proxy | 多 LLM API | 代理、日志、鉴权 | 间接覆盖 | 上游 API Key | 下游 API Key | 作为轻量代理参考，媒体能力需补齐 |
| 11 | [router-for-me/CLIProxyAPI](https://github.com/router-for-me/CLIProxyAPI) | CLI/Agent 转 API | Claude Code、Gemini CLI、Codex CLI、Qwen Code、Grok CLI/Build、Antigravity 等 | OpenAI/Gemini/Anthropic compatible 接口，多账号轮询，部分多模态输入 | 间接覆盖 `openai_image`, `gemini`, `grok`, `qwen` | CLI/OAuth 授权文件、账号登录态、API Key 引用 | 统一 API Key、多账号管理 | 高优先级抽取：CLI/Agent 资源转 API、账号轮询、健康检查；图片/视频输出需专门 connector |
| 12 | [kittors/CliRelay](https://github.com/kittors/CliRelay) | CLI 订阅聚合与 API 转发 | Claude Code、Gemini CLI、Qwen Code、Codex 等 | 订阅额度代理、OpenAI-compatible 调用、部分图片生成配置 | 间接覆盖 `openai_image`, `gemini`, `qwen` | OAuth/CLI 凭据、账号配置、API Key | 平台 API Key/面板 | 高优先级抽取：账号导入、模型别名、图片开关、面板化管理 |
| 13 | [xiaoxihexiaoyu/AIClient-2-API](https://github.com/xiaoxihexiaoyu/AIClient-2-API) / [justlovemaki/AIClient2API](https://github.com/justlovemaki/AIClient2API) | AI 客户端/CLI 转 API | Gemini CLI、Antigravity、Qwen Code、Kiro、Codex、Grok 等 | OpenAI-compatible API，包含 Gemini/Grok/Qwen/Codex 等客户端资源；部分仓库声明 Grok 图片/视频 | 直接/间接覆盖 `gemini`, `grok`, `qwen`, `openai_image` | OAuth、CLI credential、账号 token 引用、API Key | OpenAI-compatible API Key | 高优先级抽取：把“客户端资源”作为独立 `quota_source`；媒体能力需逐项验收 |
| 14 | [Brioch/gemini-openai-proxy](https://github.com/Brioch/gemini-openai-proxy) | Gemini 转 OpenAI-compatible API | Gemini API | Gemini 模型代理到 OpenAI 格式 | 间接覆盖 `gemini` 图片/视频，但仓库多偏文本 | Gemini API Key | 本地/代理 API Key 可选 | 可作为 Gemini HTTP 协议转换参考，Veo/Nano Banana 需要另做媒体任务层 |
| 15 | [gzzhongqi/geminicli2api](https://github.com/gzzhongqi/geminicli2api) | Gemini CLI 转 API | Gemini CLI | Gemini CLI 额度转 OpenAI-compatible API | 间接覆盖 `gemini` | Gemini CLI OAuth/本地授权材料 | API Key/代理鉴权 | 可抽取 CLI 资源接入，但不直接覆盖视频资产处理 |
| 16 | [Mirrowel/LLM-API-Key-Proxy](https://github.com/Mirrowel/LLM-API-Key-Proxy) | Gemini/Vertex/OpenAI 代理 | Gemini API、Vertex AI、OpenAI-compatible | 多 key 代理、模型转发 | 间接覆盖 `gemini` 与聚合类 | 上游 API Key/Vertex 凭据 | 代理 API Key | 可抽取 key 池、限流、回退机制 |

### 3.2 OpenAI / ChatGPT / Codex 图像资源

| # | 项目 | 类型 | 支持平台 | 支持模型/能力 | 覆盖源码类型 | 上游鉴权方式 | 下游鉴权/管理 | 适配结论 |
|---:|---|---|---|---|---|---|---|---|
| 17 | [icebear0828/codex-proxy](https://github.com/icebear0828/codex-proxy) | Codex/ChatGPT 订阅转 OpenAI-compatible API | ChatGPT/Codex | Responses、Codex CLI 相关调用；声明支持 `gpt-image-2` image generation tool | `openai_image` | ChatGPT/Codex OAuth 或 CLI 登录态引用 | 本地服务 API Key/反代配置 | 高优先级抽取：Codex 订阅图像 sidecar，适合承接 `gpt-image-2` |
| 18 | [violet27chen/codexProapi](https://github.com/violet27chen/codexProapi) | Codex Pro 转 API | ChatGPT/Codex | Codex 模型、`gpt-image-2`、多账号代理 | `openai_image` | ChatGPT/Codex OAuth/账号引用 | API Key/代理服务 | 高优先级抽取：多账号 Codex 图像资源池 |
| 19 | [basketikun/chatgpt2api](https://github.com/basketikun/chatgpt2api) | ChatGPT Web 转 API | ChatGPT Web | ChatGPT Web 反代，仓库说明包含 GPT-Image-2、Responses API 兼容 | `openai_image` | ChatGPT Web 账号/会话引用 | API Key/账号池配置 | 技术上相关但合规风险高；只抽取任务队列、账号池和资产输出思想 |
| 20 | [lidge-jun/ima2-gen](https://github.com/lidge-jun/ima2-gen) | 图片/视频生成工具 | OpenAI GPT Image、Codex OAuth、Grok、Doubao Seedream 等 | GPT Image、Grok 视频、Seedream 等图像/视频生成 | `openai_image`, `grok`, `seedream_proxy`, `jimeng` | OpenAI API Key、Codex OAuth、Grok/第三方 API Key | 本地 Web 应用鉴权可选 | 可抽取多 provider 表单、图片/视频任务参数、BYO key/订阅混合模式 |
| 21 | [oakplank/claude-gpt-image-bridge](https://github.com/oakplank/claude-gpt-image-bridge) | Agent/CLI 图像桥接 | Codex CLI、ChatGPT 订阅 | 通过 Codex CLI/ChatGPT 订阅触发 `gpt-image-2` 图像生成 | `openai_image` | Codex CLI 登录态/订阅引用 | 本地工具，无完整 API 网关 | 可作为 sidecar connector 原型；需要包装为 gen2api 任务 API |
| 22 | [Wangnov/gpt-image-2-skill](https://github.com/Wangnov/gpt-image-2-skill) | Agent skill / 图像生成工具 | Codex/OpenAI | `gpt-image-2`、Nano Banana、Flux/Kontext 等可配置图像能力 | `openai_image`, `gemini`, `flux_stability` | OpenAI API Key 或 Codex 订阅/本地授权 | Agent skill，无下游网关 | 可抽取图像模型参数与多后端配置 |
| 23 | [laolin5564/canvas-realm-gpt-image-2-studio](https://github.com/laolin5564/canvas-realm-gpt-image-2-studio) | GPT-Image-2 Studio | OpenAI/ChatGPT/Codex 图像能力 | GPT-Image-2 图像生成/编辑工作流 | `openai_image` | OpenAI API Key 或 Codex/订阅引用，依部署配置 | 本地 Web 项目 | 可抽取 UI 参数、批量图像任务，不是 API 网关核心 |
| 24 | [CookSleep/gpt_image_playground](https://github.com/CookSleep/gpt_image_playground) / [xxxily/gpt-image-playground](https://github.com/xxxily/gpt-image-playground) | GPT Image Playground | OpenAI 图像 API | GPT Image 生成/编辑/变体实验 | `openai_image` | OpenAI API Key | 本地 Web 鉴权可选 | 可抽取图片参数与调试界面；不属于订阅转 API |

### 3.3 Midjourney / Discord 任务通道代理

| # | 项目 | 类型 | 支持平台 | 支持模型/能力 | 覆盖源码类型 | 上游鉴权方式 | 下游鉴权/管理 | 适配结论 |
|---:|---|---|---|---|---|---|---|---|
| 25 | [trueai-org/midjourney-proxy](https://github.com/trueai-org/midjourney-proxy) | Midjourney Proxy | Midjourney、Discord 频道/账号、可选 Youchuan | Imagine、upscale、variation、blend、describe、face swap 等任务 | `midjourney` | Discord/Midjourney 账号、频道、服务配置引用 | Swagger/API 服务，可配置鉴权 | 高优先级抽取：MJ 异步任务、按钮动作、回调、任务状态、账号/频道池 |
| 26 | [novicezk/midjourney-proxy](https://github.com/novicezk/midjourney-proxy) | Midjourney Proxy | Midjourney Discord | Imagine、UPSCALE、VARIATION、任务提交/查询/回调 | `midjourney` | Discord/Midjourney 账号、guild/channel/session 引用 | API Secret/代理鉴权 | 高优先级抽取：任务队列、回调、失败状态、严格并发；上游会话材料必须 vault 化 |
| 27 | [PlexPt/midjourney-proxy](https://github.com/PlexPt/midjourney-proxy) | Midjourney Proxy 派生/封装 | Midjourney | 多账号、队列、任务、API 调用，依分支实现 | `midjourney` | Discord/MJ 账号池引用 | API Secret/后台鉴权 | 可作为 novicezk 生态派生参考；优先抽取多账号池、队列容量、任务按钮动作 |
| 28 | [yachty66/unofficial_midjourney_python_api](https://github.com/yachty66/unofficial_midjourney_python_api) | 非官方 MJ Python API | Midjourney Discord | Prompt 到 MJ 任务、图像结果获取 | `midjourney` | Discord 用户授权/频道信息引用 | 脚本级，无完整下游鉴权 | 只作为协议历史参考；不采纳任何获取 token 的教程内容 |
| 29 | [Draym/midjourney-api](https://github.com/Draym/midjourney-api) | Midjourney API wrapper | Midjourney Discord | Imagine、upscale、variation | `midjourney` | Discord/Midjourney 账号/频道引用 | 本地 API 鉴权可选 | 可抽取简单 API 形态 |
| 30 | [Dooy/chatgpt-web-midjourney-proxy](https://github.com/Dooy/chatgpt-web-midjourney-proxy) | Web UI + Midjourney Proxy | ChatGPT Web UI、Midjourney Proxy、OpenAI-compatible API | 聊天 + MJ 绘图、代理整合 | `midjourney`, 间接 `openai_image` | OpenAI/代理 API Key、MJ Proxy 配置 | Web 登录/API Key | 可抽取“聊天 UI + 生图代理”产品集成方式 |

### 3.4 Gemini / Grok / Qwen / Jimeng / Seedream / Seedance

| # | 项目 | 类型 | 支持平台 | 支持模型/能力 | 覆盖源码类型 | 上游鉴权方式 | 下游鉴权/管理 | 适配结论 |
|---:|---|---|---|---|---|---|---|---|
| 31 | [chenyme/grok2api](https://github.com/chenyme/grok2api) | Grok 转 OpenAI-compatible API | Grok / xAI | Grok 文本、多模态，部分实现面向 Grok Web/Build 资源 | `grok`，媒体能力待验收 | Grok/xAI API Key 或 Web/账号引用，依仓库配置 | OpenAI-compatible API Key | 可作为 Grok connector 候选；必须单独验收 Imagine 图片/视频 |
| 32 | [merterbak/Grok-MCP](https://github.com/merterbak/Grok-MCP) | Grok MCP 服务 | xAI/Grok API | Grok 模型调用，MCP 工具化 | 间接 `grok` | xAI API Key | MCP client 配置 | 可抽取 MCP connector 形态，不直接解决图片/视频任务 |
| 33 | [gateway/ComfyUI-Kie-API](https://github.com/gateway/ComfyUI-Kie-API) | ComfyUI 第三方 API 节点 | Kie.ai 等第三方图像/视频平台 | Kling、Veo、Sora、Runway、Hailuo、Pixverse、Seedream、Flux 等依 Kie 平台而定 | `kling`, `gemini`, `runway`, `jimeng`, `seedream_proxy`, `flux_stability` | Kie.ai API Key | ComfyUI 本地节点，无完整下游网关 | 高优先级抽取：第三方媒体聚合 connector 与模型映射 |
| 34 | [fkxianzhou/ComfyUI-Jimeng-API](https://github.com/fkxianzhou/ComfyUI-Jimeng-API) | ComfyUI Jimeng/即梦 API 节点 | Jimeng、Seedream、Seedance | 即梦图片/视频节点，依上游 API 支持 | `jimeng`, `seedream_proxy` | Jimeng/第三方 API Key 或账号引用，依配置 | ComfyUI 本地节点 | 可抽取 Jimeng connector 参数：图片、视频、参考图、任务轮询 |
| 35 | [seedance-api/seedance-api](https://github.com/seedance-api/seedance-api) | Seedance API 服务/说明 | Seedance / ByteDance 视频 | 文生视频、图生视频 | `jimeng` | API Key 或第三方服务 token | API 服务鉴权 | 可作为 Seedance connector 需求参考，需核验开源代码完整度 |
| 36 | [Anil-matcha/Open-Generative-AI](https://github.com/Anil-matcha/Open-Generative-AI) | 多模型生成式 AI 集合 | Qwen、FLUX、SD、TTS 等开源模型 | 图像生成、文本、音频等 | `qwen`, `flux_stability` | 本地模型/服务 Key 可选 | 本地服务/脚本 | 可抽取自托管模型目录与能力矩阵 |
| 37 | [deepbeepmeep/Wan2GP](https://github.com/deepbeepmeep/Wan2GP) | Wan 视频本地推理/工具 | Wan 2.x | 文生视频、图生视频、本地视频生成 | `qwen`, `fal_replicate` 的 `wan-video` 后备 | 本地推理，无上游账号；GPU 资源即鉴权边界 | 本地服务鉴权需自行加 | 可作为自托管 Wan connector 后端，需包装任务队列与资产输出 |
| 38 | [pollinations/pollinations](https://github.com/pollinations/pollinations) | 开源图片/视频生成聚合 API | Pollinations、多个第三方/开源模型 | 图片生成、部分视频生成；模型包括 gpt-image、nanobanana、seedream、qwen、flux、veo/seedance/wan 等随服务变化 | `pollinations`, `openrouter_image`, `fal_replicate`, `flux_stability`, `jimeng`, `qwen`, `gemini` | 公共/可选 API Key、服务侧账号或自托管配置 | HTTP API，可自行加下游 key | 高优先级抽取：聚合 API、模型别名、无密钥/可选密钥模式、媒体 URL 返回 |

### 3.5 Kling / Luma / Runway / Hailuo / 视频平台 connector

| # | 项目 | 类型 | 支持平台 | 支持模型/能力 | 覆盖源码类型 | 上游鉴权方式 | 下游鉴权/管理 | 适配结论 |
|---:|---|---|---|---|---|---|---|---|
| 39 | [aself101/kling-api](https://github.com/aself101/kling-api) | Kling 非官方 API wrapper | Kling AI | 文生视频、图生视频、图片生成/任务查询，依版本而定 | `kling` | Kling 账号/JWT/API credential 引用 | 本地 API 鉴权可选 | 高优先级抽取：Kling 任务提交、轮询、资产下载；合规风险需单独评估 |
| 40 | [KlingTeam/ComfyUI-KLingAI-API](https://github.com/KlingTeam/ComfyUI-KLingAI-API) | Kling 官方/社区 ComfyUI 节点 | Kling AI API | 文生视频、图生视频、视频延展/特效，依 API 支持 | `kling` | Kling Access Key/Secret Key 或 API Key | ComfyUI 本地节点 | 高优先级抽取：Kling 官方 API 参数、长任务轮询、extend 能力 |
| 41 | [199-mcp/mcp-kling](https://github.com/199-mcp/mcp-kling) | Kling MCP 服务 | Kling AI API | 文生视频、图生视频、任务查询 | `kling` | Kling API Key/credential | MCP client 配置 | 可抽取 MCP-to-connector 适配形态 |
| 42 | [bobtista/luma-ai-mcp-server](https://github.com/bobtista/luma-ai-mcp-server) | Luma MCP 服务 | Luma AI / Dream Machine | 视频生成、图片到视频、任务状态 | `luma` | Luma API Key | MCP client 配置 | 可抽取 Luma MCP connector；需包装为 HTTP 任务 API |
| 43 | [lvalics/n8n-nodes-useapi](https://github.com/lvalics/n8n-nodes-useapi) | n8n 节点 / useapi.net 连接器 | Midjourney、Runway、Luma、Kling、MiniMax/Hailuo、Pika、Suno 等 | 图像/视频任务，依 useapi 平台 | `midjourney`, `runway`, `luma`, `kling`, 扩展 `hailuo` | useapi.net API Token、各平台账号由 useapi 承载 | n8n credential | 高优先级抽取：第三方媒体平台聚合、任务参数、回调/轮询 |
| 44 | [samagra14/mediagateway](https://github.com/samagra14/mediagateway) | 媒体生成 API 网关 | 多媒体生成服务 | 文生图、文生视频、媒体任务网关，依实现 | 聚合 `fal_replicate`, `flux_stability`, 视频类 provider | 上游 API Key/服务配置 | 网关 API Key | 可参考媒体任务网关边界；需核验模型覆盖 |
| 45 | [mountsea-ai/ai-video-generator-api](https://github.com/mountsea-ai/ai-video-generator-api) | 视频生成 API 示例/服务 | Kling、Runway、Sora、Veo、Hailuo、Luma、Pixverse 等 | 文生视频、图生视频，依平台 | `kling`, `runway`, `luma`, `gemini`, 扩展 Sora/Hailuo/Pixverse | 平台 API Key 或第三方聚合 Key | API Key/Bearer | 可抽取视频平台能力矩阵；需区分开源代码与商业 API 文档 |
| 46 | [AceDataCloud/Nexior](https://github.com/AceDataCloud/Nexior) | 多平台 AI API/MCP 聚合 | Midjourney、Kling、Runway、Luma、Hailuo、Seedream、Veo、Sora 等，依服务 | 图片/视频/音频生成 | 多数源码 provider | AceDataCloud API Key | MCP/API Key | 可作为商业聚合 connector 参考，重点看模型别名与任务状态 |
| 47 | [MiniMax-AI/MiniMax-MCP-JS](https://github.com/MiniMax-AI/MiniMax-MCP-JS) | MiniMax/Hailuo MCP 服务 | MiniMax、Hailuo 视频、语音/图像能力 | 视频生成、语音、图像，依官方 API | 可扩展 `hailuo`，补充视频生态 | MiniMax API Key | MCP client 配置 | 作为 Hailuo/MiniMax 视频扩展候选，不是当前源码 P0 |
| 48 | [tryonlabs/opentryon](https://github.com/tryonlabs/opentryon) | 虚拟试穿/视频图像 API | Runway、Kling、Luma、Replicate/FAL 等可配置 | 图像/视频生成工作流 | `runway`, `kling`, `luma`, `fal_replicate` | 上游 API Key | 本地/服务 API Key | 可抽取垂直场景工作流与多后端路由 |

### 3.6 fal / Replicate / OpenRouter / Flux / Stability / 自托管模型

| # | 项目 | 类型 | 支持平台 | 支持模型/能力 | 覆盖源码类型 | 上游鉴权方式 | 下游鉴权/管理 | 适配结论 |
|---:|---|---|---|---|---|---|---|---|
| 49 | [open-webui/open-webui](https://github.com/open-webui/open-webui) | 多模型 Web UI/后端 | OpenAI-compatible、Ollama、OpenRouter、图片生成后端等 | 文本、多模态、图像生成集成，依配置 | `openrouter_image`, `flux_stability` 间接 | OpenAI/OpenRouter/后端 API Key | 用户登录、后端 key 配置 | 可抽取管理 UI 和多后端配置，不作为媒体反代核心 |
| 50 | [Comfy-Org/ComfyUI](https://github.com/Comfy-Org/ComfyUI) | 自托管图像/视频工作流引擎 | Stable Diffusion、FLUX、ControlNet、Wan/视频工作流扩展 | 图片生成、图生图、图片编辑、视频工作流，依节点 | `flux_stability`, `qwen/wan` 后备 | 本地 GPU/模型文件；可加 API Key | 本地服务需自行鉴权 | 高优先级抽取：自托管图片/视频后备 connector，适合解决成本与独立性 |
| 51 | [AUTOMATIC1111/stable-diffusion-webui](https://github.com/AUTOMATIC1111/stable-diffusion-webui) | Stable Diffusion WebUI/API | Stable Diffusion、SDXL、ControlNet 插件 | 文生图、图生图、图片编辑/局部重绘 | `flux_stability` | 本地模型/可选账号密码/API auth | 本地 API auth 可配置 | 可作为 `flux_stability` 传统 SD 后备 connector |
| 52 | [vllm-project/vllm](https://github.com/vllm-project/vllm) | OpenAI-compatible 推理服务 | 多开源模型，含部分多模态模型 | OpenAI-compatible 文本/多模态推理；图片/视频生成不是核心 | 间接 `flux_stability` 不充分 | 本地服务/API Key 可配置 | OpenAI-compatible API Key | 只作自托管网关参考，不直接覆盖图片/视频生成 |
| 53 | [HanseWare/FastFusion](https://github.com/HanseWare/FastFusion) | FLUX/Stable Diffusion API 服务 | FLUX、Stable Diffusion | 图片生成 API | `flux_stability` | 本地模型/GPU，API Key 可选 | 本地 API Key 可选 | 可作为 FLUX 图像 connector 后端 |
| 54 | [Aquiles-ai/Aquiles-Image](https://github.com/Aquiles-ai/Aquiles-Image) | Open-source AI image API | FLUX、Stable Diffusion、Qwen Image 等依实现 | 文生图、图生图、图片编辑 | `flux_stability`, `qwen`, `amux_qwen` | 本地/第三方模型 Key | API Key/Bearer 可配置 | 可作为图片模型聚合后备 |
| 55 | [jau123/MeiGen-AI-Design-MCP](https://github.com/jau123/MeiGen-AI-Design-MCP) | 设计/生图 MCP | GPT Image、Nano Banana、ComfyUI 等图像能力，依配置 | 图片生成、编辑、设计任务 | `flux_stability`, `gemini`, `openai_image` | 上游 API Key/本地服务 | MCP client 配置 | 可抽取 MCP 作为 connector 输入层 |
| 56 | [fal-ai/fal-js](https://github.com/fal-ai/fal-js) | fal 官方开源 SDK | fal.ai 模型市场 | FLUX、Wan、Kling、Luma、Veo 等依 fal 模型市场 | `fal_replicate`, `flux_stability`, `qwen/wan`, 视频类 provider | `FAL_KEY` / fal API Key | SDK，无下游网关 | 适合作为 fal connector SDK，不是订阅转 API |
| 57 | [replicate/replicate-python](https://github.com/replicate/replicate-python) | Replicate 官方开源 SDK | Replicate 模型市场 | FLUX、SD、Wan、视频模型等依市场 | `fal_replicate`, `flux_stability` | Replicate API Token | SDK，无下游网关 | 适合作为 Replicate connector SDK |
| 58 | [openrouter-ai/openrouter-examples](https://github.com/OpenRouterTeam/openrouter-examples) | OpenRouter 示例/SDK | OpenRouter | OpenAI-compatible 文本/多模态/图像模型，依 OpenRouter 上架 | `openrouter_image` | OpenRouter API Key | 示例，无下游网关 | 适合作为 OpenRouter 图片渠道接入参考 |

## 4. 模型覆盖矩阵

| 源码 Provider | 已找到的主要开源项目 | 覆盖状态 | 主要缺口 |
|---|---|---|---|
| `openai_image` | `codex-proxy`, `codexProapi`, `chatgpt2api`, `ima2-gen`, `claude-gpt-image-bridge`, `gpt-image-2-skill`, `canvas-realm-gpt-image-2-studio`, `gpt_image_playground` | 已有 Web Cookie/CLI/Agent 多种样本 | 需要 ChatGPT Web cookie 原生托管、Codex Agent profile、图片编辑验收、账号材料加密和过期检测 |
| `gemini` | `sub2api`, `CLIProxyAPI`, `CliRelay`, `AIClient2API`, `geminicli2api`, `gemini-openai-proxy`, `LLM-API-Key-Proxy`, `ComfyUI-Kie-API` | Agent/API 转接样本充足 | Veo/Nano Banana 媒体任务层、Agent runtime 隔离与资产下载需单独实现 |
| `grok` | `AIClient2API`, `CLIProxyAPI`, `grok2api`, `Grok-MCP`, `ima2-gen` | 文本/CLI/MCP 样本存在 | Grok Imagine 图片/视频的公开开源 connector 较少，必须验收真实媒体输出 |
| `qwen` | `AIClient2API`, `CLIProxyAPI`, `CliRelay`, `ComfyUI-Kie-API`, `Wan2GP`, `Aquiles-Image`, `Open-Generative-AI` | Qwen Code/API/Wan 自托管样本存在 | `qwen-image-edit`、`wan-video` 需要按 API/本地推理拆分 connector |
| `jimeng` / `seedream_proxy` | `ComfyUI-Jimeng-API`, `seedance-api`, `pollinations`, `ComfyUI-Kie-API`, `ima2-gen`, `MeiGen-AI-Design-MCP` | 图片/视频聚合与 ComfyUI/Agent 样本存在 | 当前复核以 Ark/API key/ref 或 Agent profile 为主；不把 Dreamina/Jimeng Web Cookie 作为主账号表单 |
| `kling` | `kling-api`, `ComfyUI-KLingAI-API`, `mcp-kling`, `n8n-nodes-useapi`, `ai-video-generator-api`, `Nexior`, `opentryon` | 视频 connector 样本较多 | 官方 API 与非官方 Web wrapper 要分层，extend 能力需验收 |
| `luma` | `luma-ai-mcp-server`, `n8n-nodes-useapi`, `ai-video-generator-api`, `Nexior`, `opentryon` | MCP/第三方聚合样本存在 | Luma extend 与 asset transfer 需独立验收 |
| `runway` | `n8n-nodes-useapi`, `ai-video-generator-api`, `Nexior`, `opentryon`, `ComfyUI-Kie-API` | 第三方聚合样本存在 | 直接 Runway Web/API 开源 wrapper 较少，需依 useapi/Kie/商业聚合或自研 connector |
| `midjourney` | `trueai-org/midjourney-proxy`, `novicezk/midjourney-proxy`, `PlexPt/midjourney-proxy`, `unofficial_midjourney_python_api`, `midjourney-api`, `chatgpt-web-midjourney-proxy`, `n8n-nodes-useapi` | 最成熟的图片任务代理生态之一 | Discord/MJ 授权材料敏感，必须严格 vault 化、限并发、合规审查 |
| `pollinations` | `pollinations/pollinations` | 直接覆盖 | 模型清单动态变化，需要运行时拉取/健康检查 |
| `openrouter_image` | `new-api`, `one-api`, `openrouter-examples`, `open-webui`, `LLM-API-Key-Proxy` | 渠道接入成熟 | OpenRouter 图片模型能力随平台变化，需动态 capability sync |
| `fal_replicate` | `fal-js`, `replicate-python`, `ComfyUI-Kie-API`, `mediagateway`, `opentryon` | SDK/聚合样本充足 | 需要把同步 SDK 调用包装为 gen2api 异步 MediaJob |
| `flux_stability` | `ComfyUI`, `stable-diffusion-webui`, `FastFusion`, `Aquiles-Image`, `jau123/MeiGen-AI-Design-MCP`, `Pollinations` | 自托管与聚合样本充足 | 需要统一工作流模板、模型文件管理、GPU 队列与输出资产规范 |

## 5. 对 gen2api 需求文档的增补要求

| 编号 | 需求项 | 说明 | 优先级 |
|---|---|---|---|
| R-OSS-001 | 建立开源 connector registry | 在管理后台维护项目来源、平台、模型、操作类型、鉴权方式、风险等级、验收状态 | P0 |
| R-OSS-002 | 上游账号资源统一抽象 | 产品主路径只保留 `cookie_secret` 与 `agent_provider_credential`；`web_session_reference`、`cli_credential_reference`、`oauth_reference`、`mcp_config_reference`、`subscription_url`、`self_hosted_endpoint`、`api_key` 只能作为开源项目原始字段、兼容导入别名或执行层配置解析，入库后必须归一到 Web Cookie 或 Agent Provider | P0 |
| R-OSS-003 | 媒体能力矩阵验收 | 每个 connector 必须声明是否支持 T2I/I2I/Edit/T2V/I2V/Extend、最大时长、参考图数量、回调、取消、重试、资产下载 | P0 |
| R-OSS-004 | 异步任务协议标准化 | Midjourney、Kling、Luma、Runway、Seedance、Wan 等长任务统一进入 `MediaJob`，输出统一 `MediaAsset` | P0 |
| R-OSS-005 | 账号池与订阅池资源模型 | 参考 sub2api/CLIProxyAPI/CliRelay/New API，实现账号状态、并发、冷却、失败次数、额度、日限额、路由权重 | P0 |
| R-OSS-006 | Web Cookie / Agent Provider 原生治理 | 平台原生接收并加密托管 Web cookie/session 与 Agent Provider credential/profile，记录生命周期、健康、额度、并发和审计；禁止验证码绕过、风控规避、批量账号获取或窃取会话流程 | P0 |
| R-OSS-007 | 图片视频专用路由策略 | 生图优先按成本/质量/速度分层；生视频优先按时长、可用性、排队时间、失败率路由 | P0 |
| R-OSS-008 | 第三方聚合 connector 分层 | `pollinations`, `openrouter_image`, `fal_replicate`, `useapi/Kie/Nexior` 等作为 aggregator adapter，与 Web 账号池 provider 分开治理 | P1 |
| R-OSS-009 | MCP connector 适配层 | 对 Kling/Luma/MiniMax/MeiGen 等 MCP 服务增加 MCP-to-HTTP sidecar 模板，统一转成 gen2api connector 协议 | P1 |
| R-OSS-010 | 自托管推理后备 | 对 ComfyUI、SD WebUI、FLUX、Wan2GP 等建立自托管 provider 模板，用于降低外部依赖和成本 | P1 |
| R-OSS-011 | 项目风险标注 | 每个开源项目按 `official_api`, `third_party_aggregator`, `subscription_connector`, `web_reverse`, `self_hosted`, `high_risk_unofficial` 标注风险 | P0 |
| R-OSS-012 | 持续调研机制 | 每月刷新 GitHub 项目清单，记录 stars、最近提交、license、能力变化、可用性、是否停止维护 | P2 |

## 6. 优先接入建议

| 阶段 | 接入对象 | 目标 | 原因 |
|---|---|---|---|
| P0-1 | `pollinations`、`fal/Replicate`、`OpenRouter`、ComfyUI/FLUX | 先打通稳定图片输出和资产规范 | 鉴权清晰、合规风险低、可快速验证 gen2api 的 MediaJob/MediaAsset |
| P0-2 | Codex/ChatGPT 图像 sidecar、Gemini/Veo sidecar、Qwen/Wan connector | 覆盖 `openai_image`, `gemini`, `qwen` 的核心模型 | 与当前源码 P0 模型贴合，且可复用订阅转 API 项目的账号池思想 |
| P0-3 | Jimeng/Seedream/Seedance、Kling | 完成图片+视频混合生产 provider | 覆盖 P0/P1 中最关键的中文生态图片/视频资源 |
| P1 | Midjourney Proxy、Luma、Runway、MiniMax/Hailuo | 丰富高质量图片/视频模型 | 生态成熟但授权材料敏感或依赖第三方聚合，需更强治理 |
| P2 | Sora/Pika/Pixverse 等扩展视频平台 | 补齐长期视频模型市场 | 当前源码未作为核心 provider，但市场价值高 |

## 7. 来源索引

| 主题 | 主要来源 |
|---|---|
| `sub2api` 生态与订阅转 API | [GitHub topic: sub2api](https://github.com/topics/sub2api), [Wei-Shaw/sub2api](https://github.com/Wei-Shaw/sub2api), [qixing-jk/all-api-hub](https://github.com/qixing-jk/all-api-hub), [B022MC/b022hub](https://github.com/B022MC/b022hub), [yunfanxing6/every2api](https://github.com/yunfanxing6/every2api) |
| 通用 API 网关 | [QuantumNous/new-api](https://github.com/QuantumNous/new-api), [songquanpeng/one-api](https://github.com/songquanpeng/one-api), [lianluo-esign/ferrogate](https://github.com/lianluo-esign/ferrogate), [LMRouter/lmrouter](https://github.com/LMRouter/lmrouter), [poixeai/proxify](https://github.com/poixeai/proxify) |
| CLI/Agent 转 API | [router-for-me/CLIProxyAPI](https://github.com/router-for-me/CLIProxyAPI), [kittors/CliRelay](https://github.com/kittors/CliRelay), [xiaoxihexiaoyu/AIClient-2-API](https://github.com/xiaoxihexiaoyu/AIClient-2-API), [justlovemaki/AIClient2API](https://github.com/justlovemaki/AIClient2API), [gzzhongqi/geminicli2api](https://github.com/gzzhongqi/geminicli2api) |
| Codex/ChatGPT 图像 | [icebear0828/codex-proxy](https://github.com/icebear0828/codex-proxy), [violet27chen/codexProapi](https://github.com/violet27chen/codexProapi), [basketikun/chatgpt2api](https://github.com/basketikun/chatgpt2api), [lidge-jun/ima2-gen](https://github.com/lidge-jun/ima2-gen), [oakplank/claude-gpt-image-bridge](https://github.com/oakplank/claude-gpt-image-bridge), [Wangnov/gpt-image-2-skill](https://github.com/Wangnov/gpt-image-2-skill) |
| Midjourney | [trueai-org/midjourney-proxy](https://github.com/trueai-org/midjourney-proxy), [novicezk/midjourney-proxy](https://github.com/novicezk/midjourney-proxy), [PlexPt/midjourney-proxy](https://github.com/PlexPt/midjourney-proxy), [yachty66/unofficial_midjourney_python_api](https://github.com/yachty66/unofficial_midjourney_python_api), [Draym/midjourney-api](https://github.com/Draym/midjourney-api), [Dooy/chatgpt-web-midjourney-proxy](https://github.com/Dooy/chatgpt-web-midjourney-proxy) |
| Gemini/Grok/Qwen/Jimeng | [Brioch/gemini-openai-proxy](https://github.com/Brioch/gemini-openai-proxy), [Mirrowel/LLM-API-Key-Proxy](https://github.com/Mirrowel/LLM-API-Key-Proxy), [chenyme/grok2api](https://github.com/chenyme/grok2api), [merterbak/Grok-MCP](https://github.com/merterbak/Grok-MCP), [fkxianzhou/ComfyUI-Jimeng-API](https://github.com/fkxianzhou/ComfyUI-Jimeng-API), [seedance-api/seedance-api](https://github.com/seedance-api/seedance-api), [deepbeepmeep/Wan2GP](https://github.com/deepbeepmeep/Wan2GP) |
| 视频平台 connector | [aself101/kling-api](https://github.com/aself101/kling-api), [KlingTeam/ComfyUI-KLingAI-API](https://github.com/KlingTeam/ComfyUI-KLingAI-API), [199-mcp/mcp-kling](https://github.com/199-mcp/mcp-kling), [bobtista/luma-ai-mcp-server](https://github.com/bobtista/luma-ai-mcp-server), [lvalics/n8n-nodes-useapi](https://github.com/lvalics/n8n-nodes-useapi), [samagra14/mediagateway](https://github.com/samagra14/mediagateway), [mountsea-ai/ai-video-generator-api](https://github.com/mountsea-ai/ai-video-generator-api), [AceDataCloud/Nexior](https://github.com/AceDataCloud/Nexior), [MiniMax-AI/MiniMax-MCP-JS](https://github.com/MiniMax-AI/MiniMax-MCP-JS) |
| 自托管/聚合图片视频后备 | [pollinations/pollinations](https://github.com/pollinations/pollinations), [Comfy-Org/ComfyUI](https://github.com/Comfy-Org/ComfyUI), [AUTOMATIC1111/stable-diffusion-webui](https://github.com/AUTOMATIC1111/stable-diffusion-webui), [HanseWare/FastFusion](https://github.com/HanseWare/FastFusion), [Aquiles-ai/Aquiles-Image](https://github.com/Aquiles-ai/Aquiles-Image), [jau123/MeiGen-AI-Design-MCP](https://github.com/jau123/MeiGen-AI-Design-MCP), [fal-ai/fal-js](https://github.com/fal-ai/fal-js), [replicate/replicate-python](https://github.com/replicate/replicate-python), [OpenRouter examples](https://github.com/OpenRouterTeam/openrouter-examples) |
