from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from . import models
from .catalog import TARGET_MODEL_TABLE
from .provider_templates import PROVIDER_TEMPLATES
from .utils import dumps, loads, redact_sensitive


ACCOUNT_RESOURCE_TYPES = {"web_cookie_provider", "agent_provider"}

PROJECT_CLASSIFICATION_TYPES = {
    "subscription_connector",
    "web_reverse_connector",
    "web_cookie_provider",
    "agent_connector",
    "agent_provider",
    "aggregator_connector",
    "mcp_connector",
    "mcp_agent_provider",
    "self_hosted_connector",
    "subscription_import",
}

REFERENCE_AUTH_TYPES = [
    "cookie_secret",
    "agent_provider_credential",
]

RUNTIME_BASE_URL_INPUT_NAMES = {
    "connector_base_url",
    "agent_runtime_endpoint",
    "runner_endpoint",
    "channel_base_url",
    "sdk_runtime_endpoint",
    "self_hosted_endpoint",
}

RUNTIME_BASE_URL_FIELD_NAMES = RUNTIME_BASE_URL_INPUT_NAMES | {
    "provider_base_url",
    "providerBaseUrl",
    "connectorBaseUrl",
    "base_url",
    "baseUrl",
    "upstream_url",
    "upstreamUrl",
    "agentRuntimeEndpoint",
    "runtime_endpoint",
    "runtimeEndpoint",
    "runnerEndpoint",
    "channelBaseUrl",
    "sdkRuntimeEndpoint",
    "selfHostedEndpoint",
    "endpoint",
}

PROVIDER_KEYWORDS: dict[str, list[str]] = {
    "openai_image": ["openai", "chatgpt", "codex", "gpt-image", "gpt_image", "gpt image"],
    "gemini": ["gemini", "antigravity", "veo", "nano banana", "nanobanana", "imagen"],
    "grok": ["grok", "xai", "imagine"],
    "qwen": ["qwen", "tongyi", "wan2", "wan ", "dashscope"],
    "jimeng": ["jimeng", "dreamina", "seedream", "seedance", "doubao"],
    "kling": ["kling", "klingai"],
    "luma": ["luma", "dream machine"],
    "runway": ["runway", "gen-3", "gen-4"],
    "midjourney": ["midjourney", "mj-", "niji", "discord"],
    "pollinations": ["pollinations"],
    "openrouter_image": ["openrouter"],
    "fal_replicate": ["fal", "replicate"],
    "seedream_proxy": ["seedream", "seededit"],
    "amux_qwen": ["amux", "qwen-image", "wan-image"],
    "flux_stability": ["comfyui", "stable diffusion", "stability", "flux", "sdxl", "controlnet"],
}

AUTH_HINTS: dict[str, list[str]] = {
    "oauth_reference": ["oauth", "device login", "device code", "login flow"],
    "cli_credential_reference": ["cli", "codex cli", "gemini cli", "qwen code", "claude code"],
    "agent_provider_credential": ["agent", "profile", "codex cli", "gemini cli", "qwen code", "antigravity"],
    "subscription_url": ["subscription", "sub2api", "sub url", "subscription_url"],
    "web_session_reference": ["web session", "cookie", "discord", "browser", "web reverse"],
    "cookie_secret": ["cookie", "cookie_header", "cookie jar", "session token", "discord token"],
    "mcp_config_reference": ["mcp"],
    "self_hosted_endpoint": ["comfyui", "stable diffusion", "self-hosted", "local gpu"],
    "aggregator_api_key": ["api key", "apikey", "bearer", "fal", "replicate", "openrouter", "pollinations"],
}

PROVIDER_RESOURCE_DEFAULTS: dict[str, str] = {
    "openai_image": "web_cookie_provider",
    "gemini": "agent_provider",
    "grok": "web_cookie_provider",
    "qwen": "agent_provider",
    "jimeng": "agent_provider",
    "kling": "agent_provider",
    "luma": "agent_provider",
    "runway": "agent_provider",
    "midjourney": "web_cookie_provider",
    "pollinations": "agent_provider",
    "openrouter_image": "agent_provider",
    "fal_replicate": "agent_provider",
    "seedream_proxy": "agent_provider",
    "amux_qwen": "agent_provider",
    "flux_stability": "agent_provider",
}

PLATFORM_INPUT_REQUIREMENTS: dict[str, dict[str, Any]] = {
    "openai_image": {
        "primary_resource_type": "web_cookie_provider",
        "accepted_resource_types": ["web_cookie_provider", "agent_provider"],
        "opensource_basis": ["chatgpt2api", "codex-proxy", "codexProapi", "ima2-gen"],
        "user_inputs": [
            {"name": "cookie_header_or_cookie_jar", "label": "ChatGPT Web cookie/header 或 cookie jar", "required": True, "auth_method": "cookie_secret", "store_as": "encrypted_secret", "evidence": "icebear0828__codex-proxy/.env.example: optional ChatGPT JWT; violet27chen__codexProapi/README.md supports OAuth Login or paste auth.json/manual JSON"},
            {"name": "agent_profile", "label": "Codex Agent/CLI profile", "required": False, "auth_method": "agent_provider_credential", "store_as": "encrypted_secret_or_agent_ref", "evidence": "violet27chen__codexProapi/README.md: add Codex accounts via OAuth Login, manual JSON, or batch import"},
            {"name": "connector_base_url", "label": "执行器地址", "required": False, "when": "使用 codex-proxy/chatgpt2api sidecar 时填写", "evidence": "icebear0828__codex-proxy/README.md and codexProapi/README.md expose localhost proxy Base URL/port for client-side sidecar access"},
        ],
        "user_actions": ["导入本人已登录的 ChatGPT cookie/session", "或选择 Codex Agent profile", "运行图片生成/编辑样本验收"],
    },
    "gemini": {
        "primary_resource_type": "agent_provider",
        "accepted_resource_types": ["agent_provider"],
        "opensource_basis": ["geminicli2api", "CLIProxyAPI", "CliRelay", "AIClient2API"],
        "user_inputs": [
            {"name": "gemini_credentials", "label": "GEMINI_CREDENTIALS JSON", "required": True, "any_of_group": "gemini_oauth_material", "auth_method": "agent_provider_credential", "store_as": "encrypted_secret_or_agent_ref", "evidence": "gzzhongqi__geminicli2api/.env.example: GEMINI_CREDENTIALS JSON string is the highest-priority credential source"},
            {"name": "google_application_credentials", "label": "GOOGLE_APPLICATION_CREDENTIALS file/ref", "required": True, "any_of_group": "gemini_oauth_material", "auth_method": "agent_provider_credential", "store_as": "encrypted_secret_or_agent_ref", "evidence": "gzzhongqi__geminicli2api/.env.example: GOOGLE_APPLICATION_CREDENTIALS points to oauth_creds.json when GEMINI_CREDENTIALS is not set"},
            {"name": "gemini_oauth_creds_base64", "label": "--gemini-oauth-creds-base64", "required": True, "any_of_group": "gemini_oauth_material", "auth_method": "agent_provider_credential", "store_as": "encrypted_secret_or_agent_ref", "evidence": "AIClient2API README: --gemini-oauth-creds-base64 is one accepted Gemini CLI OAuth credential source"},
            {"name": "gemini_oauth_creds_file", "label": "--gemini-oauth-creds-file / ~/.gemini/oauth_creds.json", "required": True, "any_of_group": "gemini_oauth_material", "auth_method": "agent_provider_credential", "store_as": "encrypted_secret_or_agent_ref", "evidence": "AIClient2API README: --gemini-oauth-creds-file is accepted; docs list ~/.gemini/oauth_creds.json as the default credential path"},
            {"name": "gemini_project_id", "label": "GEMINI_PROJECT_ID / --project-id", "required": False, "auth_method": "agent_provider_credential", "store_as": "encrypted_secret_or_agent_ref", "when": "when the selected Gemini wrapper needs an explicit Google Cloud project id", "evidence": "gzzhongqi__geminicli2api/.env.example: GEMINI_PROJECT_ID is optional when not embedded; AIClient2API README marks --project-id required for gemini-cli-oauth"},
            {"name": "agent_runtime_endpoint", "label": "Agent runtime / CLIProxyAPI 服务地址", "required": False, "when": "使用外部 agent wrapper 时填写", "evidence": "gzzhongqi__geminicli2api/.env.example: optional HOST/PORT; README client uses localhost wrapper base_url only for the sidecar"},
        ],
        "user_actions": ["选择本地 Gemini/Antigravity 授权 profile", "登记 agent runtime 隔离策略", "运行 Nano Banana / Veo 样本验收"],
    },
    "qwen": {
        "primary_resource_type": "agent_provider",
        "accepted_resource_types": ["agent_provider"],
        "opensource_basis": ["CLIProxyAPI", "CliRelay", "AIClient2API"],
        "user_inputs": [
            {"name": "qwen_oauth_creds_file", "label": "--qwen-oauth-creds-file", "required": True, "any_of_group": "qwen_oauth_material", "auth_method": "agent_provider_credential", "store_as": "encrypted_secret_or_agent_ref", "evidence": "AIClient2API README: --qwen-oauth-creds-file is required when model-provider is openai-qwen-oauth"},
            {"name": "qwen_oauth_cache_path", "label": "~/.qwen/oauth_creds.json", "required": True, "any_of_group": "qwen_oauth_material", "auth_method": "agent_provider_credential", "store_as": "encrypted_secret_or_agent_ref", "evidence": "AIClient2API docs list ~/.qwen/oauth_creds.json as the Qwen OAuth credential storage path"},
            {"name": "qwen_oauth_credentials", "label": "Qwen OAuth credentials JSON", "required": True, "any_of_group": "qwen_oauth_material", "auth_method": "agent_provider_credential", "store_as": "encrypted_secret_or_agent_ref", "evidence": "CLIProxyAPI/CliRelay Qwen OAuth flows store provider credentials in the agent runtime auth directory"},
            {"name": "agent_runtime_endpoint", "label": "Agent runtime / relay 服务地址", "required": False, "when": "使用 CliRelay/CLIProxyAPI 时填写", "evidence": "kittors__CliRelay/README_CN.md: unified endpoint http://localhost:8317 and base_url http://localhost:8317/v1"},
        ],
        "user_actions": ["登记 Qwen Code 授权 profile", "绑定可执行 runtime", "验收 qwen-image-edit 或 Wan 视频能力"],
    },
    "grok": {
        "primary_resource_type": "web_cookie_provider",
        "accepted_resource_types": ["web_cookie_provider", "agent_provider"],
        "opensource_basis": ["grok2api", "Grok-MCP", "AIClient2API"],
        "user_inputs": [
            {"name": "grok_cookie_or_session", "label": "Grok Web/Build cookie 或 session", "required": True, "auth_method": "cookie_secret", "store_as": "encrypted_secret", "evidence": "chenyme__grok2api/README.md: Grok Web capabilities and proxy.clearance with cf_cookies/user_agent"},
            {"name": "agent_profile", "label": "Grok agent/MCP profile", "required": False, "auth_method": "agent_provider_credential", "evidence": "router-for-me__CLIProxyAPI/README.md: Grok Build OAuth login support; merterbak__Grok-MCP/README.md config uses XAI_API_KEY"},
        ],
        "user_actions": ["导入本人 Grok Web/Build 会话", "或登记 Grok Agent/MCP profile", "验收 Imagine 图片/视频输出"],
    },
    "jimeng": {
        "primary_resource_type": "agent_provider",
        "accepted_resource_types": ["agent_provider"],
        "opensource_basis": ["ComfyUI-Jimeng-API", "seedance-api", "ima2-gen"],
        "user_inputs": [
            {"name": "api_key", "label": "api_keys.json apiKey / api_key", "required": True, "auth_method": "agent_provider_credential", "store_as": "encrypted_secret_or_agent_ref", "require_named_field": True, "aliases": ["apiKey"], "evidence": "fkxianzhou__ComfyUI-Jimeng-API/api_keys.json.example stores apiKey values; seedance-api/README.md requires api_key"},
        ],
        "user_actions": ["按 ComfyUI-Jimeng-API 的 api_keys.json/apiKey 或 seedance-api 的 api_key 提交托管凭据。", "配置并发和额度限制。", "验收图片/视频任务与资产转存。"],
    },
    "kling": {
        "primary_resource_type": "agent_provider",
        "accepted_resource_types": ["agent_provider"],
        "opensource_basis": ["kling-api", "mcp-kling", "ComfyUI-KLingAI-API"],
        "user_inputs": [
            {"name": "kling_access_key", "label": "KLING_ACCESS_KEY", "required": True, "auth_method": "agent_provider_credential", "store_as": "encrypted_secret_or_agent_ref", "evidence": "aself101__kling-api/.env.example and 199-mcp__mcp-kling/.env.example require KLING_ACCESS_KEY"},
            {"name": "kling_secret_key", "label": "KLING_SECRET_KEY", "required": True, "auth_method": "agent_provider_credential", "store_as": "encrypted_secret_or_agent_ref", "evidence": "aself101__kling-api/.env.example and 199-mcp__mcp-kling/.env.example require KLING_SECRET_KEY"},
            {"name": "mcp_agent_config_ref", "label": "Kling MCP/Agent config ref", "required": False, "auth_method": "agent_provider_credential", "store_as": "agent_ref_or_config", "when": "Use this only when an external MCP/Agent profile already contains both Kling keys", "evidence": "199-mcp__mcp-kling/README.md uses MCP config/env to hold KLING_ACCESS_KEY and KLING_SECRET_KEY"},
        ],
        "user_actions": ["Register KLING_ACCESS_KEY and KLING_SECRET_KEY, or an MCP/agent profile that contains them.", "Bind video duration/concurrency limits.", "Validate t2v/i2v/extend."],
    },
    "midjourney": {
        "primary_resource_type": "web_cookie_provider",
        "accepted_resource_types": ["web_cookie_provider"],
        "opensource_basis": ["novicezk/midjourney-proxy", "PlexPt/midjourney-proxy", "trueai-org/midjourney-proxy"],
        "user_inputs": [
            {"name": "discord_session_or_user_token", "label": "Discord/Midjourney session 或 user token", "required": True, "auth_method": "cookie_secret", "store_as": "encrypted_secret", "evidence": "PlexPt__midjourney-proxy/src/main/resources/application.yml: mj.discord.user-token"},
            {"name": "discord_bot_token", "label": "Discord bot token", "required": False, "auth_method": "cookie_secret", "store_as": "encrypted_secret", "when": "PlexPt/trueai-style proxy requires a bot token", "evidence": "PlexPt__midjourney-proxy/src/main/resources/application.yml: mj.discord.bot-token"},
            {"name": "guild_id", "label": "Discord guild/server id", "required": True, "evidence": "PlexPt__midjourney-proxy/src/main/resources/application.yml: mj.discord.guild-id"},
            {"name": "channel_id", "label": "Discord channel id", "required": True, "evidence": "PlexPt__midjourney-proxy/src/main/resources/application.yml: mj.discord.channel-id"},
            {"name": "discord_user_agent", "label": "Discord user-agent", "required": False, "when": "novicezk/trueai-style session bridge requires a browser user-agent", "evidence": "midjourney-proxy family reads Discord browser/session metadata; keep optional and platform-specific"},
            {"name": "discord_server", "label": "Discord server reverse endpoint", "required": False, "when": "the selected Midjourney bridge explicitly exposes a Discord API reverse endpoint", "evidence": "midjourney-proxy reverse settings are bridge-specific; not a gen2api account base_url"},
            {"name": "discord_cdn", "label": "Discord CDN reverse endpoint", "required": False, "when": "the selected Midjourney bridge explicitly exposes a Discord CDN reverse endpoint", "evidence": "midjourney-proxy reverse settings are bridge-specific; not a gen2api account base_url"},
            {"name": "discord_wss", "label": "Discord gateway WSS reverse endpoint", "required": False, "when": "the selected Midjourney bridge explicitly exposes a Discord gateway reverse endpoint", "evidence": "midjourney-proxy reverse settings are bridge-specific; not a gen2api account base_url"},
        ],
        "user_actions": ["按 midjourney-proxy 的字段绑定 guild/channel/session", "并发默认 1", "验收 imagine/upscale/variation"],
    },
    "seedream_proxy": {
        "primary_resource_type": "agent_provider",
        "accepted_resource_types": ["agent_provider"],
        "opensource_basis": ["ComfyUI-Jimeng-API", "seedance-api", "ima2-gen"],
        "user_inputs": [
            {"name": "api_key", "label": "api_keys.json apiKey / api_key", "required": True, "auth_method": "agent_provider_credential", "store_as": "encrypted_secret_or_agent_ref", "require_named_field": True, "aliases": ["apiKey"], "evidence": "fkxianzhou__ComfyUI-Jimeng-API/api_keys.json.example and seedance-api/README.md both require apiKey/api_key-style credentials"},
        ],
        "user_actions": ["按 ComfyUI-Jimeng-API 的 api_keys.json/apiKey 或 seedance-api 的 api_key 提交托管凭据。", "验收 Seedream/Seededit/Seedance 输出。"],
    },
    "luma": {
        "primary_resource_type": "agent_provider",
        "accepted_resource_types": ["agent_provider"],
        "opensource_basis": ["luma-ai-mcp-server"],
        "user_inputs": [
            {"name": "luma_api_key", "label": "LUMA_API_KEY / --api-key", "required": True, "auth_method": "agent_provider_credential", "store_as": "encrypted_secret_or_agent_ref", "require_named_field": True, "aliases": ["LUMA_API_KEY", "api-key"], "evidence": "bobtista__luma-ai-mcp-server/src/luma_ai_mcp_server/__init__.py uses click --api-key with envvar LUMA_API_KEY; server.py raises when LUMA_API_KEY is missing"},
        ],
        "user_actions": ["按 luma-ai-mcp-server 的 LUMA_API_KEY/--api-key 提交托管凭据。", "验收 Dream Machine 视频任务。"],
    },
    "runway": {
        "primary_resource_type": "agent_provider",
        "accepted_resource_types": ["agent_provider"],
        "opensource_basis": ["n8n-nodes-useapi", "ai-video-generator-api", "Nexior", "opentryon", "ComfyUI-Kie-API"],
        "user_inputs": [
            {"name": "useapi_api_key", "label": "UseAPI apiKey", "required": True, "auth_method": "agent_provider_credential", "store_as": "encrypted_secret_or_agent_ref", "require_named_field": True, "aliases": ["apiKey", "USEAPI_API_KEY"], "evidence": "lvalics__n8n-nodes-useapi/credentials/UseApiApi.credentials.ts defines required credential field apiKey"},
            {"name": "runway_email", "label": "Runway Email", "required": False, "auth_method": "agent_provider_credential", "store_as": "encrypted_secret_or_agent_ref", "aliases": ["runwayEmail"], "when": "only when using the UseAPI account-registration helper; otherwise keep the main gen2api account form credential-ref only", "evidence": "lvalics__n8n-nodes-useapi/credentials/UseApiApi.credentials.ts includes optional Runway Email for UseAPI registration"},
            {"name": "runway_password", "label": "Runway Password", "required": False, "auth_method": "agent_provider_credential", "store_as": "encrypted_secret_or_agent_ref", "aliases": ["runwayPassword"], "when": "only when using the UseAPI account-registration helper; otherwise keep the main gen2api account form credential-ref only", "evidence": "lvalics__n8n-nodes-useapi/credentials/UseApiApi.credentials.ts includes optional Runway Password for UseAPI registration"},
        ],
        "user_actions": ["按 n8n-nodes-useapi 的 UseAPI apiKey 提交托管凭据。", "只有使用 UseAPI 注册 helper 时才把 Runway Email/Password 放入 Agent Provider 加密材料。", "验收 gen3/gen4/extend。"],
    },
    "pollinations": {
        "primary_resource_type": "agent_provider",
        "accepted_resource_types": ["agent_provider"],
        "opensource_basis": ["pollinations/pollinations"],
        "user_inputs": [
            {"name": "pollinations_key", "label": "POLLINATIONS_KEY / Authorization Bearer key", "required": True, "auth_method": "agent_provider_credential", "store_as": "encrypted_secret_or_agent_ref", "require_named_field": True, "aliases": ["POLLINATIONS_API_KEY", "key"], "evidence": "pollinations__pollinations/APIDOCS.md sends Authorization: Bearer $POLLINATIONS_KEY or ?key=; README also shows POLLINATIONS_API_KEY"},
            {"name": "self_hosted_endpoint", "label": "自托管 Pollinations endpoint", "required": False, "when": "使用自托管 Pollinations 服务时填写", "evidence": "pollinations__pollinations/AGENTS.md: local gen worker on port 8788; APIDOCS.md Base URL https://gen.pollinations.ai"},
        ],
        "user_actions": ["按 Pollinations 文档提交 POLLINATIONS_KEY/POLLINATIONS_API_KEY 或 bearer key。", "只有自托管 Pollinations 服务时才填写 self_hosted_endpoint。", "作为 fallback/Agent 后端验收图片和视频能力。"],
    },
    "openrouter_image": {
        "primary_resource_type": "agent_provider",
        "accepted_resource_types": ["agent_provider"],
        "opensource_basis": ["new-api", "one-api", "openrouter-examples", "open-webui", "LLM-API-Key-Proxy"],
        "user_inputs": [
            {"name": "openrouter_api_key", "label": "OPENROUTER_API_KEY", "required": True, "any_of_group": "openrouter_key_material", "auth_method": "agent_provider_credential", "store_as": "encrypted_secret_or_agent_ref", "require_named_field": True, "evidence": "OpenRouterTeam__openrouter-examples/typescript/README.md requires OPENROUTER_API_KEY"},
            {"name": "openrouter_api_key_n", "label": "OPENROUTER_API_KEY_N", "required": True, "any_of_group": "openrouter_key_material", "auth_method": "agent_provider_credential", "store_as": "encrypted_secret_or_agent_ref", "require_named_field": True, "aliases": ["OPENROUTER_API_KEY_1", "OPENROUTER_API_KEY_2"], "evidence": "Mirrowel__LLM-API-Key-Proxy/.env.example supports OPENROUTER_API_KEY_N style key pools"},
            {"name": "anthropic_auth_token", "label": "ANTHROPIC_AUTH_TOKEN", "required": True, "any_of_group": "openrouter_key_material", "auth_method": "agent_provider_credential", "store_as": "encrypted_secret_or_agent_ref", "require_named_field": True, "evidence": "OpenRouterTeam__openrouter-examples/claude-code/statusline.ts accepts ANTHROPIC_AUTH_TOKEN for an OpenRouter-backed Claude Code example"},
            {"name": "anthropic_api_key", "label": "ANTHROPIC_API_KEY", "required": True, "any_of_group": "openrouter_key_material", "auth_method": "agent_provider_credential", "store_as": "encrypted_secret_or_agent_ref", "require_named_field": True, "evidence": "OpenRouterTeam__openrouter-examples/claude-code/statusline.ts also accepts ANTHROPIC_API_KEY"},
            {"name": "channel_base_url", "label": "OpenRouter-compatible channel endpoint", "required": False, "when": "使用 new-api/one-api channel 或自托管 OpenAI-compatible runner 时填写", "evidence": "songquanpeng__one-api/README.md: add API Key on Channels and set API Base to deployment; QuantumNous__new-api/README.md documents custom upstream/channel gateway"},
        ],
        "user_actions": ["按 OpenRouter 示例提交 OPENROUTER_API_KEY，或按对应代理项目提交 OPENROUTER_API_KEY_N/ANTHROPIC_AUTH_TOKEN。", "只有 channel 网关项目实际存在时才填写 channel_base_url。", "同步图片模型能力并作为 fallback/Agent 后端验收。"],
    },
    "fal_replicate": {
        "primary_resource_type": "agent_provider",
        "accepted_resource_types": ["agent_provider"],
        "opensource_basis": ["fal-ai/fal-js", "replicate/replicate-python", "ComfyUI-Kie-API", "mediagateway", "opentryon"],
        "user_inputs": [
            {"name": "fal_key", "label": "FAL_KEY", "required": True, "any_of_group": "fal_replicate_key_material", "auth_method": "agent_provider_credential", "store_as": "encrypted_secret_or_agent_ref", "require_named_field": True, "evidence": "fal-ai__fal-js/README.md uses credentials: FAL_KEY and requires FAL_KEY env var"},
            {"name": "replicate_api_token", "label": "REPLICATE_API_TOKEN", "required": True, "any_of_group": "fal_replicate_key_material", "auth_method": "agent_provider_credential", "store_as": "encrypted_secret_or_agent_ref", "require_named_field": True, "evidence": "replicate__replicate-python tests and docs use REPLICATE_API_TOKEN"},
            {"name": "sdk_runtime_endpoint", "label": "SDK wrapper/runtime endpoint", "required": False, "when": "把 fal/Replicate SDK 包装成 HTTP runner 时填写", "evidence": "fal-ai__fal-js/libs/proxy/README.md exposes /api/fal/proxy; samagra14__mediagateway/README.md uses Backend API http://localhost:3001"},
        ],
        "user_actions": ["按 fal-js 的 FAL_KEY 或 replicate-python 的 REPLICATE_API_TOKEN 提交托管凭据。", "把同步 SDK 调用包装为异步 MediaJob。", "验收图片/视频任务轮询和资产转存。"],
    },
    "amux_qwen": {
        "primary_resource_type": "agent_provider",
        "accepted_resource_types": ["agent_provider"],
        "opensource_basis": ["CLIProxyAPI", "CliRelay", "AIClient2API", "Qwen Code"],
        "user_inputs": [
            {"name": "qwen_oauth_creds_file", "label": "--qwen-oauth-creds-file", "required": True, "any_of_group": "amux_qwen_oauth_material", "auth_method": "agent_provider_credential", "store_as": "encrypted_secret_or_agent_ref", "evidence": "AIClient2API README: --qwen-oauth-creds-file is required when model-provider is openai-qwen-oauth"},
            {"name": "qwen_oauth_cache_path", "label": "~/.qwen/oauth_creds.json", "required": True, "any_of_group": "amux_qwen_oauth_material", "auth_method": "agent_provider_credential", "store_as": "encrypted_secret_or_agent_ref", "evidence": "xiaoxihexiaoyu__AIClient-2-API/README-JA.md stores Qwen OAuth creds at ~/.qwen/oauth_creds.json"},
            {"name": "qwen_oauth_credentials", "label": "Qwen OAuth credentials JSON", "required": True, "any_of_group": "amux_qwen_oauth_material", "auth_method": "agent_provider_credential", "store_as": "encrypted_secret_or_agent_ref", "evidence": "CLIProxyAPI/CliRelay Qwen OAuth flows store provider credentials in the agent runtime auth directory"},
            {"name": "agent_runtime_endpoint", "label": "Agent runtime / wrapper endpoint", "required": False, "when": "使用 AMux/Qwen wrapper 服务时填写", "evidence": "kittors__CliRelay/README_CN.md exposes unified endpoint http://localhost:8317/v1 for CLI/Agent relay"},
        ],
        "user_actions": ["按 Qwen/AMux Agent Provider 的 OAuth cache 字段提交托管凭据。", "只有使用外部 wrapper 服务时才填写 agent_runtime_endpoint。", "验收 qwen-image/qwen-image-edit/wan-image。"],
    },
    "flux_stability": {
        "primary_resource_type": "agent_provider",
        "accepted_resource_types": ["agent_provider"],
        "opensource_basis": ["ComfyUI", "stable-diffusion-webui", "FastFusion", "Aquiles-Image", "MeiGen-AI-Design-MCP"],
        "user_inputs": [
            {"name": "comfyui_workflow_api_json", "label": "ComfyUI workflow API JSON", "required": True, "any_of_group": "flux_stability_runner_material", "auth_method": "agent_provider_credential", "store_as": "agent_ref_or_config", "require_named_field": True, "aliases": ["workflow_api_json"], "evidence": "jau123__MeiGen-AI-Design-MCP/plugin/commands/setup.md: ComfyUI local setup imports workflow API JSON"},
            {"name": "model_config_json", "label": "FastFusion model_config.json", "required": True, "any_of_group": "flux_stability_runner_material", "auth_method": "agent_provider_credential", "store_as": "agent_ref_or_config", "require_named_field": True, "evidence": "HanseWare__FastFusion/README.md uses model_config.json for Diffusers/FLUX"},
            {"name": "meigen_mcp_config", "label": "MeiGen MCP config", "required": True, "any_of_group": "flux_stability_runner_material", "auth_method": "agent_provider_credential", "store_as": "agent_ref_or_config", "require_named_field": True, "aliases": ["mcp_config"], "evidence": "jau123__MeiGen-AI-Design-MCP stores MCP/tool config for image generation workflows"},
            {"name": "self_hosted_endpoint", "label": "自托管 WebUI/ComfyUI endpoint", "required": False, "when": "使用本地 GPU/自托管服务时填写", "evidence": "HanseWare__FastFusion/README.md runs OpenAI-compatible image endpoints on localhost:8000; Aquiles-Image/README.md runs local server on localhost:5500 with optional API key"},
        ],
        "user_actions": ["按 ComfyUI workflow API JSON、FastFusion model_config.json 或 MeiGen MCP config 提交 Agent Provider 材料。", "只有使用本地 HTTP runner 时才填写 self_hosted_endpoint。", "作为 Agent 后端/fallback 验收。"],
    },
}

PROVIDER_GUIDE_OVERRIDES: dict[str, dict[str, Any]] = {
    "openai_image": {
        "title": "ChatGPT Web Cookie / Codex Agent 图像资源接入",
        "recommended_auth_methods": ["cookie_secret", "agent_provider_credential"],
        "credential_ref_example": "secret://providers/openai_image/chatgpt_cookie_01",
        "base_url_example": "",
        "steps": [
            "按 ChatGPT Web/Codex 类开源项目的实际要求，导入本人已授权的 cookie/session 或 Codex Agent profile。",
            "如果使用 chatgpt2api/codex-proxy sidecar，再填写该 sidecar 的执行地址；不使用 sidecar 时不要求 base_url。",
            "平台把 cookie/session 或 agent profile 转成 encrypted secret/ref，并绑定账号池。",
            "保存后运行健康检查、能力同步和 text_to_image/image_edit 样本验收。",
        ],
    },
    "gemini": {
        "title": "Gemini / Antigravity Agent Provider 资源接入",
        "recommended_auth_methods": ["agent_provider_credential"],
        "credential_ref_example": "agent://providers/gemini/acct_01",
        "base_url_example": "",
        "steps": [
            "按 geminicli2api/CLIProxyAPI/CliRelay 的方式选择 Gemini CLI、Antigravity 或 agent profile。",
            "登记 CLI/OAuth cache 引用、agent runtime endpoint 和工作目录隔离策略。",
            "只有使用外部 agent wrapper 服务时才填写 base_url。",
            "能力同步后至少验收 nano-banana 图像和 veo 视频各一条样本。",
        ],
    },
    "midjourney": {
        "title": "Midjourney / Discord Web Session 任务通道接入",
        "recommended_auth_methods": ["cookie_secret"],
        "credential_ref_example": "secret://providers/midjourney/discord_session_01",
        "base_url_example": "",
        "steps": [
            "按 midjourney-proxy 系项目实际字段填写 Discord/MJ session、guild id、channel id。",
            "gen2api 的账号资源只登记频道、会话和可选 bot/reverse 字段；proxy 服务地址属于具体执行器部署，不作为 Midjourney 账号字段暴露。",
            "在 gen2api 中选择 midjourney，绑定频道资源和并发 1。",
            "运行 imagine、variation 或 upscale 样本验收，确认结果已转存为 MediaAsset。",
        ],
    },
    "kling": {
        "title": "Kling Access Key / MCP Agent 视频资源接入",
        "recommended_auth_methods": ["agent_provider_credential"],
        "credential_ref_example": "agent://providers/kling/acct_01",
        "base_url_example": "",
        "steps": [
            "按 kling-api/mcp-kling/ComfyUI-KLingAI-API 项目的实际模式登记 KLING_ACCESS_KEY + KLING_SECRET_KEY，或登记 MCP/Agent config。",
            "当前复核不在主账号表单要求 Kling Web cookie/JWT；base_url 只有在另有 MCP-to-HTTP 或 runner 明确要求时才属于执行层。",
            "在 gen2api 中选择 kling，启用 i2v/t2v/extend 对应模型和并发限制。",
            "先验收 image_to_video，再验收 text_to_video 或 video_extend。",
        ],
    },
    "flux_stability": {
        "title": "ComfyUI / FLUX / Stable Diffusion Agent 后端接入",
        "recommended_auth_methods": ["agent_provider_credential"],
        "credential_ref_example": "agent://providers/flux_stability/local_comfyui",
        "base_url_example": "",
        "steps": [
            "登记 ComfyUI、Stable Diffusion WebUI、FLUX workflow、MCP config 或本地 runner profile。",
            "只有使用自托管 HTTP 服务时才填写 endpoint/base_url；本地 agent/MCP profile 不要求 base_url。",
            "在 gen2api 中选择 flux_stability，作为 Agent Provider 后端或 fallback 执行层登记 workflow 能力。",
            "验收 text_to_image、image_to_image 或 image_edit，确认 GPU 队列不会阻塞主 API。",
        ],
    },
}


def runtime_base_url_input_fields(input_requirements: dict[str, Any]) -> list[str]:
    return [
        str(item.get("name"))
        for item in input_requirements.get("user_inputs", [])
        if item.get("name") in RUNTIME_BASE_URL_INPUT_NAMES
    ]


def provider_runtime_base_url_allowed_from_requirements(input_requirements: dict[str, Any]) -> bool:
    return bool(runtime_base_url_input_fields(input_requirements))


def provider_runtime_base_url_allowed(provider_id: str) -> bool:
    input_requirements = PLATFORM_INPUT_REQUIREMENTS.get(provider_id)
    if not input_requirements:
        return True
    return provider_runtime_base_url_allowed_from_requirements(input_requirements)


def strip_runtime_base_url_fields(data: Any) -> Any:
    if isinstance(data, dict):
        return {
            key: strip_runtime_base_url_fields(value)
            for key, value in data.items()
            if key not in RUNTIME_BASE_URL_FIELD_NAMES
        }
    if isinstance(data, list):
        return [strip_runtime_base_url_fields(item) for item in data]
    return data


def provider_runtime_config(provider_id: str, config: dict[str, Any] | None) -> dict[str, Any]:
    value = dict(config or {})
    return value if provider_runtime_base_url_allowed(provider_id) else strip_runtime_base_url_fields(value)


class ConnectorRegistryService:
    def __init__(self, project_root: Path | None = None) -> None:
        self.project_root = project_root or Path(__file__).resolve().parent.parent

    def refresh_from_local_repos(self, db: Session, res_repo_path: str | None = None) -> dict[str, Any]:
        root = self._resolve_res_repo(res_repo_path)
        if not root.exists():
            return {"object": "connector_registry.refresh", "status": "failed", "error": "RES_REPO_NOT_FOUND", "path": str(root)}
        scanned = 0
        created = 0
        updated = 0
        items: list[dict[str, Any]] = []
        for repo_dir in sorted(path for path in root.iterdir() if path.is_dir() and (path / ".git").exists()):
            scanned += 1
            metadata = self.classify_repo(repo_dir)
            item = db.get(models.OpenSourceConnectorProject, metadata["id"])
            if item:
                updated += 1
            else:
                item = models.OpenSourceConnectorProject(id=metadata["id"], repo_url=metadata["repo_url"])
                db.add(item)
                created += 1
            self._apply_metadata(item, metadata)
            db.flush()
            items.append(self.serialize_project(item))
        db.commit()
        return {
            "object": "connector_registry.refresh",
            "status": "ok",
            "path": str(root),
            "scanned": scanned,
            "created": created,
            "updated": updated,
            "data": items,
        }

    def list_projects(
        self,
        db: Session,
        *,
        provider_id: str | None = None,
        project_type: str | None = None,
        status: str | None = None,
        risk_level: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        query = db.query(models.OpenSourceConnectorProject)
        if project_type:
            query = query.filter(models.OpenSourceConnectorProject.project_type == project_type)
        if status:
            query = query.filter(models.OpenSourceConnectorProject.status == status)
        if risk_level:
            query = query.filter(models.OpenSourceConnectorProject.risk_level == risk_level)
        projects = query.order_by(models.OpenSourceConnectorProject.project_type, models.OpenSourceConnectorProject.id).limit(min(limit, 1000)).all()
        rows = [self.serialize_project(project) for project in projects]
        if provider_id:
            rows = [row for row in rows if provider_id in row["provider_ids"]]
        return rows

    def provider_guide(self, db: Session, provider_id: str) -> dict[str, Any]:
        target = next((row for row in TARGET_MODEL_TABLE if row[0] == provider_id), None)
        template = PROVIDER_TEMPLATES.get(provider_id)
        operations: list[str] = []
        models_: list[str] = []
        if template:
            operations.extend(template.operations)
            models_.extend(template.models)
            for mapping in template.mappings:
                operations.extend(mapping.operations)
                models_.append(mapping.provider_model)
        if target:
            models_.extend(target[1])
            operations.extend(target[2])
        operations = sorted(dict.fromkeys(operations))
        models_ = sorted(dict.fromkeys(model for model in models_ if model))
        override = PROVIDER_GUIDE_OVERRIDES.get(provider_id, {})
        input_requirements = PLATFORM_INPUT_REQUIREMENTS.get(provider_id, {})
        resource_type = input_requirements.get("primary_resource_type") or PROVIDER_RESOURCE_DEFAULTS.get(provider_id, "agent_provider")
        recommended_auth_methods = override.get("recommended_auth_methods") or self.default_auth_methods_for_resource(resource_type)
        account_id = f"acct_{provider_id}_01"
        base_url = override.get("base_url_example", "")
        runtime_input_fields = runtime_base_url_input_fields(input_requirements)
        runtime_base_url_allowed = bool(runtime_input_fields)
        credential_ref = override.get("credential_ref_example")
        if not credential_ref:
            credential_ref = f"secret://providers/{provider_id}/cookie_01" if resource_type == "web_cookie_provider" else f"agent://providers/{provider_id}/acct_01"
        payload = {
            "provider_id": provider_id,
            "account_id": account_id,
            "label": f"{provider_id} production account 01",
            "auth_method": recommended_auth_methods[0],
            "credential_ref": credential_ref,
            "credential_value": "",
            "credential_kind": "custom",
            "supported_operations": operations,
            "supported_provider_models": models_,
            "quota_buckets": [{"type": "daily", "remaining_estimate": None, "source": "connector"}],
            "concurrency_limit": 1,
            "region": "",
            "plan": resource_type,
            "resource_type": resource_type,
            "resource_profile": {
                "resource_type": resource_type,
                "input_requirements": input_requirements.get("user_inputs", []),
                "opensource_basis": input_requirements.get("opensource_basis", []),
            },
            "status": "active",
            "upsert": True,
            "sync_capabilities": True,
            "run_health_check": True,
        }
        if base_url and runtime_base_url_allowed:
            payload["provider_base_url"] = base_url
        related_projects = self.list_projects(db, provider_id=provider_id, limit=50)
        steps = override.get("steps") or [
            "按该平台对应开源项目实际要求选择 Web Cookie/session 或 Agent Provider profile。",
            "明文 cookie/session/profile 只用于一次性提交，平台保存为 encrypted secret/ref。",
            "如果执行器支持 delegated OAuth/device login，可 POST /v1/admin/authorized-resource-sessions 发起授权资源会话，授权后完成并自动创建账号。",
            "base_url 只在对应项目确实要求 sidecar/runner 服务地址时填写。",
            "在 gen2api 中填写 provider、资源类型、授权材料、能力范围和并发上限。",
            "保存后运行 capabilities sync、health check、quota sync 和 external acceptance。",
        ]
        return {
            "object": "media2api.account_onboarding_guide",
            "provider_id": provider_id,
            "title": override.get("title") or f"{provider_id} 资源接入",
            "resource_type": resource_type,
            "accepted_resource_types": input_requirements.get("accepted_resource_types") or [resource_type],
            "input_requirements": input_requirements.get("user_inputs", []),
            "user_actions": input_requirements.get("user_actions", []),
            "opensource_basis": input_requirements.get("opensource_basis", []),
            "recommended_auth_methods": recommended_auth_methods,
            "supported_operations": operations,
            "supported_provider_models": models_,
            "base_url_example": base_url,
            "runtime_base_url_allowed": runtime_base_url_allowed,
            "runtime_base_url_input_fields": runtime_input_fields,
            "base_url_policy": "Only show or submit provider_base_url when input_requirements includes a runner/sidecar/runtime endpoint field.",
            "credential_ref_example": credential_ref,
            "steps": steps,
            "payload_template": payload,
            "curl": self._curl_for_payload(payload),
            "related_open_source_projects": related_projects,
            "safety_boundary": [
                "Web cookie/session 与 Agent credential 可以由主平台加密托管或使用 vault/agent 引用。",
                "明文 cookie/token/profile 只允许一次性提交，入库后必须变成 encrypted secret/ref。",
                "不得沉淀账号密码、验证码处理、风控规避、批量账号获取或窃取会话流程。",
            ],
        }

    def provider_guides(self, db: Session, provider_id: str | None = None) -> list[dict[str, Any]]:
        provider_ids = [provider_id] if provider_id else [row[0] for row in TARGET_MODEL_TABLE]
        return [self.provider_guide(db, item) for item in provider_ids]

    def onboarding_plan(self, db: Session, payload: dict[str, Any]) -> dict[str, Any]:
        provider_id = str(payload.get("provider_id") or "").strip()
        if not provider_id:
            raise ValueError("PROVIDER_ID_REQUIRED")
        guide = self.provider_guide(db, provider_id)
        planned = dict(guide["payload_template"])
        for key, value in payload.items():
            if value not in (None, "", [], {}):
                if key == "provider_base_url":
                    input_requirements = PLATFORM_INPUT_REQUIREMENTS.get(provider_id, {})
                    if not provider_runtime_base_url_allowed_from_requirements(input_requirements):
                        raise ValueError("PROVIDER_BASE_URL_NOT_ALLOWED")
                planned[key] = value
        return {
            "object": "media2api.account_onboarding_plan",
            "provider_id": provider_id,
            "guide": guide,
            "payload": planned,
            "curl": self._curl_for_payload(planned),
            "next_steps": [
                "确认 Web Cookie/session 或 Agent Provider profile 是该平台对应开源项目实际要求的材料。",
                "执行器 base_url 只有在对应项目明确要求 sidecar/runner 服务地址时填写。",
                "如果还没有 credential_ref，可使用 /v1/admin/authorized-resource-sessions 发起授权资源会话，再完成会话。",
                "POST 到 /v1/admin/account-onboarding 保存账号。",
                "保存后运行 /v1/admin/accounts/{account_id}/external-acceptance。",
            ],
        }

    def classify_repo(self, repo_dir: Path) -> dict[str, Any]:
        owner, repo = self._owner_repo_from_dir(repo_dir)
        repo_url = self._remote_url(repo_dir, owner, repo)
        corpus = self._read_corpus(repo_dir)
        lowered = corpus.lower()
        provider_ids = self._infer_providers(owner, repo, lowered)
        project_type = self._infer_project_type(repo, lowered, provider_ids)
        raw_auth_hints = self._infer_raw_auth_hints(lowered)
        auth_types = self._infer_auth_types(project_type, lowered)
        operations = self._infer_operations(provider_ids, lowered)
        platforms = self._infer_platforms(provider_ids, lowered)
        models_ = self._infer_models(provider_ids, lowered)
        risk_level = self._risk_for(project_type, lowered)
        license_id = self._license(repo_dir)
        return {
            "id": f"{owner}__{repo}",
            "repo_url": repo_url,
            "owner": owner,
            "repo": repo,
            "local_path": str(repo_dir),
            "project_type": project_type,
            "status": "discovered",
            "risk_level": risk_level,
            "provider_ids": provider_ids,
            "platforms": platforms,
            "models": models_,
            "operations": operations,
            "auth_types": auth_types,
            "downstream_auth": self._infer_downstream_auth(lowered),
            "evidence": {
                "readme_excerpt": redact_sensitive(corpus[:1600]),
                "classification": {
                    "account_resource_type": PROVIDER_RESOURCE_DEFAULTS.get(provider_ids[0], "agent_provider") if provider_ids else "agent_provider",
                    "project_type": project_type,
                    "matched_providers": provider_ids,
                    "matched_auth_types": auth_types,
                    "raw_auth_hints": raw_auth_hints,
                },
            },
            "maintenance_status": "local_clone_present",
            "license": license_id,
            "notes": "Generated from local res-repo scan; verify README claims with connector conformance before production.",
            "last_scanned_at": datetime.utcnow(),
        }

    def serialize_project(self, item: models.OpenSourceConnectorProject) -> dict[str, Any]:
        return {
            "id": item.id,
            "repo_url": item.repo_url,
            "owner": item.owner,
            "repo": item.repo,
            "local_path": item.local_path,
            "project_type": item.project_type,
            "status": item.status,
            "risk_level": item.risk_level,
            "provider_ids": loads(item.provider_ids_json, []),
            "platforms": loads(item.platforms_json, []),
            "models": loads(item.models_json, []),
            "operations": loads(item.operations_json, []),
            "auth_types": loads(item.auth_types_json, []),
            "downstream_auth": loads(item.downstream_auth_json, []),
            "evidence": loads(item.evidence_json, {}),
            "maintenance_status": item.maintenance_status,
            "license": item.license,
            "notes": item.notes,
            "last_scanned_at": item.last_scanned_at.isoformat() + "Z" if item.last_scanned_at else None,
            "created_at": item.created_at.isoformat() + "Z" if item.created_at else None,
            "updated_at": item.updated_at.isoformat() + "Z" if item.updated_at else None,
        }

    def default_auth_methods_for_resource(self, resource_type: str) -> list[str]:
        if resource_type == "web_cookie_provider":
            return ["cookie_secret"]
        if resource_type == "agent_provider":
            return ["agent_provider_credential"]
        if resource_type == "mcp_agent_provider":
            return ["agent_provider_credential"]
        if resource_type == "agent_connector":
            return ["agent_provider_credential"]
        if resource_type == "web_reverse_connector":
            return ["cookie_secret"]
        if resource_type == "mcp_connector":
            return ["agent_provider_credential"]
        if resource_type == "self_hosted_connector":
            return ["agent_provider_credential"]
        if resource_type == "aggregator_connector":
            return ["agent_provider_credential"]
        return ["agent_provider_credential"]

    def default_base_url(self, provider_id: str) -> str:
        template = PROVIDER_TEMPLATES.get(provider_id)
        config = template.default_config if template else {}
        return str(config.get("base_url") or "")

    def _apply_metadata(self, item: models.OpenSourceConnectorProject, metadata: dict[str, Any]) -> None:
        item.repo_url = metadata["repo_url"]
        item.owner = metadata["owner"]
        item.repo = metadata["repo"]
        item.local_path = metadata["local_path"]
        item.project_type = metadata["project_type"]
        item.risk_level = metadata["risk_level"]
        item.provider_ids_json = dumps(metadata["provider_ids"])
        item.platforms_json = dumps(metadata["platforms"])
        item.models_json = dumps(metadata["models"])
        item.operations_json = dumps(metadata["operations"])
        item.auth_types_json = dumps(metadata["auth_types"])
        item.downstream_auth_json = dumps(metadata["downstream_auth"])
        item.evidence_json = dumps(metadata["evidence"])
        item.maintenance_status = metadata["maintenance_status"]
        item.license = metadata["license"]
        item.notes = metadata["notes"]
        item.last_scanned_at = metadata["last_scanned_at"]
        if item.status not in {"shortlisted", "adapter_designing", "connector_ready", "conformance_passed", "external_acceptance_passed", "production_enabled", "deprecated"}:
            item.status = metadata["status"]

    def _resolve_res_repo(self, res_repo_path: str | None) -> Path:
        if res_repo_path:
            path = Path(res_repo_path)
            return path if path.is_absolute() else self.project_root / path
        return self.project_root / "res-repo"

    def _owner_repo_from_dir(self, repo_dir: Path) -> tuple[str, str]:
        if "__" in repo_dir.name:
            owner, repo = repo_dir.name.split("__", 1)
            return owner, repo
        return "unknown", repo_dir.name

    def _remote_url(self, repo_dir: Path, owner: str, repo: str) -> str:
        config = repo_dir / ".git" / "config"
        if config.exists():
            text = config.read_text(encoding="utf-8", errors="ignore")
            for line in text.splitlines():
                stripped = line.strip()
                if stripped.startswith("url = "):
                    return stripped.replace("url = ", "", 1).strip().removesuffix(".git")
        return f"https://github.com/{owner}/{repo}"

    def _read_corpus(self, repo_dir: Path) -> str:
        parts: list[str] = []
        candidates = [
            "README.md",
            "README.en.md",
            "README_CN.md",
            "README.zh.md",
            "README_ZH.md",
            "README",
            "AGENTS.md",
            "CLAUDE.md",
        ]
        for name in candidates:
            path = repo_dir / name
            if path.exists() and path.is_file():
                parts.append(path.read_text(encoding="utf-8", errors="ignore")[:12000])
        for doc in sorted((repo_dir / "docs").glob("*.md"))[:8] if (repo_dir / "docs").exists() else []:
            parts.append(doc.read_text(encoding="utf-8", errors="ignore")[:4000])
        return "\n\n".join(parts)

    def _infer_providers(self, owner: str, repo: str, corpus: str) -> list[str]:
        haystack = f"{owner} {repo} {corpus}".lower()
        matched = []
        for provider_id, keywords in PROVIDER_KEYWORDS.items():
            if any(keyword in haystack for keyword in keywords):
                matched.append(provider_id)
        return sorted(dict.fromkeys(matched))

    def _infer_project_type(self, repo: str, corpus: str, provider_ids: list[str]) -> str:
        name = repo.lower()
        if "mcp" in name or " mcp" in corpus:
            return "mcp_agent_provider"
        if any(word in name or word in corpus for word in ["comfyui", "stable-diffusion", "flux", "self-hosted", "local gpu"]):
            return "agent_provider"
        if any(word in name or word in corpus for word in ["sub2api", "subscription", "oauth", "cli", "agent", "codex", "antigravity"]):
            return "agent_provider" if any(word in name or word in corpus for word in ["cli", "agent", "codex", "antigravity"]) else "subscription_import"
        if any(word in name or word in corpus for word in ["proxy", "web", "midjourney", "discord"]):
            return "web_cookie_provider"
        if any(word in name or word in corpus for word in ["gateway", "router", "relay", "openrouter", "fal", "replicate", "pollinations", "new-api", "one-api"]):
            return "aggregator_connector"
        if provider_ids:
            return PROVIDER_RESOURCE_DEFAULTS.get(provider_ids[0], "aggregator_connector")
        return "unknown"

    def _infer_auth_types(self, project_type: str, corpus: str) -> list[str]:
        auth_types = set(self.default_auth_methods_for_resource(project_type))
        for auth_type in self._infer_raw_auth_hints(corpus):
            auth_types.add(self._normalize_reference_auth_type(auth_type))
        return sorted(item for item in auth_types if item in REFERENCE_AUTH_TYPES)

    def _infer_raw_auth_hints(self, corpus: str) -> list[str]:
        return sorted(
            auth_type
            for auth_type, keywords in AUTH_HINTS.items()
            if any(keyword in corpus for keyword in keywords)
        )

    def _normalize_reference_auth_type(self, auth_type: str) -> str:
        if auth_type in {"cookie_secret", "web_session_reference"}:
            return "cookie_secret"
        return "agent_provider_credential"

    def _infer_operations(self, provider_ids: list[str], corpus: str) -> list[str]:
        operations: set[str] = set()
        for provider_id in provider_ids:
            target = next((row for row in TARGET_MODEL_TABLE if row[0] == provider_id), None)
            if target:
                operations.update(target[2])
        if any(word in corpus for word in ["image", "images/generations", "text_to_image", "imagine", "flux", "stable diffusion"]):
            operations.add("text_to_image")
        if any(word in corpus for word in ["edit", "mask", "image_to_image", "variation", "upscale"]):
            operations.add("image_to_image")
        if any(word in corpus for word in ["image_edit", "inpaint", "seededit"]):
            operations.add("image_edit")
        if any(word in corpus for word in ["video", "text_to_video", "t2v", "veo", "kling", "runway", "luma", "seedance", "wan"]):
            operations.update(["text_to_video", "image_to_video"])
        if any(word in corpus for word in ["extend", "video_extend"]):
            operations.add("video_extend")
        return sorted(operations)

    def _infer_platforms(self, provider_ids: list[str], corpus: str) -> list[str]:
        labels = {
            "openai_image": "ChatGPT/Codex",
            "gemini": "Gemini/Veo",
            "grok": "Grok",
            "qwen": "Qwen/Wan",
            "jimeng": "Jimeng/Seedream/Seedance",
            "kling": "Kling",
            "luma": "Luma",
            "runway": "Runway",
            "midjourney": "Midjourney",
            "pollinations": "Pollinations",
            "openrouter_image": "OpenRouter",
            "fal_replicate": "fal/Replicate",
            "seedream_proxy": "Seedream",
            "amux_qwen": "AMux/Qwen",
            "flux_stability": "Flux/Stability/ComfyUI",
        }
        platforms = [labels[item] for item in provider_ids if item in labels]
        if "sora" in corpus:
            platforms.append("Sora")
        if "hailuo" in corpus or "minimax" in corpus:
            platforms.append("MiniMax/Hailuo")
        return sorted(dict.fromkeys(platforms))

    def _infer_models(self, provider_ids: list[str], corpus: str) -> list[str]:
        models_: set[str] = set()
        for provider_id in provider_ids:
            target = next((row for row in TARGET_MODEL_TABLE if row[0] == provider_id), None)
            if target:
                models_.update(str(item) for item in target[1])
        for token in ["gpt-image-2", "nano-banana", "veo", "seedream", "seedance", "qwen-image", "wan", "flux", "sdxl", "kling", "runway", "luma"]:
            if token in corpus:
                models_.add(token)
        return sorted(model for model in models_ if model)

    def _infer_downstream_auth(self, corpus: str) -> list[str]:
        result = {"bearer_api_key"}
        if "x-api-key" in corpus or "x api key" in corpus:
            result.add("x-api-key")
        if "jwt" in corpus:
            result.add("jwt")
        if "admin token" in corpus:
            result.add("admin_token")
        return sorted(result)

    def _risk_for(self, project_type: str, corpus: str) -> str:
        if project_type == "self_hosted_connector":
            return "self_hosted"
        if project_type == "aggregator_connector":
            return "third_party_aggregator"
        if project_type in {"mcp_connector", "mcp_agent_provider"}:
            return "mcp_connector"
        if "cookie" in corpus or "discord" in corpus or "web session" in corpus:
            return "high_risk_unofficial"
        if project_type in {"subscription_connector", "subscription_import"}:
            return "subscription_connector"
        if project_type in {"agent_connector", "agent_provider"}:
            return "agent_connector"
        return "needs_review"

    def _license(self, repo_dir: Path) -> str:
        for name in ["LICENSE", "LICENSE.md", "COPYING"]:
            path = repo_dir / name
            if path.exists() and path.is_file():
                first = path.read_text(encoding="utf-8", errors="ignore")[:500].lower()
                if "mit license" in first:
                    return "MIT"
                if "apache license" in first:
                    return "Apache-2.0"
                if "gnu general public license" in first:
                    return "GPL"
                return "present"
        return ""

    def _curl_for_payload(self, payload: dict[str, Any]) -> str:
        body = dumps(redact_sensitive(payload))
        return (
            "curl -X POST "
            "-H \"Authorization: Bearer dev-admin-key\" "
            "-H \"Content-Type: application/json\" "
            f"http://127.0.0.1:8080/v1/admin/account-onboarding -d '{body}'"
        )
