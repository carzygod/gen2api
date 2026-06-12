from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SOURCE_REPO = ROOT / "source-repo"
sys.path.insert(0, str(ROOT))

from media2api.catalog import TARGET_MODEL_TABLE
from media2api.services_connector_registry import PLATFORM_INPUT_REQUIREMENTS


EvidenceSpec = dict[str, Any]


EVIDENCE_SPECS: dict[str, dict[str, list[EvidenceSpec]]] = {
    "openai_image": {
        "cookie_header_or_cookie_jar": [
            {"path": "icebear0828__codex-proxy/.env.example", "patterns": ["CODEX_JWT_TOKEN"]},
        ],
        "agent_profile": [
            {"path": "violet27chen__codexProapi/README.md", "patterns": ["OAuth Login", "manual JSON input", "Batch Import"]},
        ],
        "connector_base_url": [
            {"path": "icebear0828__codex-proxy/README.md", "patterns": ["Base URL", "http://localhost:8080/v1"]},
        ],
    },
    "gemini": {
        "gemini_credentials": [
            {"path": "gzzhongqi__geminicli2api/README.md", "patterns": ["GEMINI_CREDENTIALS"]},
        ],
        "google_application_credentials": [
            {"path": "gzzhongqi__geminicli2api/README.md", "patterns": ["GOOGLE_APPLICATION_CREDENTIALS"]},
        ],
        "gemini_oauth_creds_base64": [
            {"path": "xiaoxihexiaoyu__AIClient-2-API/src/services/api-server.js", "patterns": ["--gemini-oauth-creds-base64"]},
        ],
        "gemini_oauth_creds_file": [
            {"path": "xiaoxihexiaoyu__AIClient-2-API/src/services/api-server.js", "patterns": ["--gemini-oauth-creds-file"]},
        ],
        "gemini_project_id": [
            {"path": "xiaoxihexiaoyu__AIClient-2-API/src/services/api-server.js", "patterns": ["--project-id"]},
        ],
        "agent_runtime_endpoint": [
            {"path": "gzzhongqi__geminicli2api/README.md", "patterns": ["base_url", "http://localhost:8888/v1"]},
        ],
    },
    "qwen": {
        "qwen_oauth_creds_file": [
            {"path": "xiaoxihexiaoyu__AIClient-2-API/src/services/api-server.js", "patterns": ["--qwen-oauth-creds-file"]},
        ],
        "qwen_oauth_cache_path": [
            {"path": "xiaoxihexiaoyu__AIClient-2-API/static/app/provider-manager.js", "patterns": ["~/.qwen/oauth_creds.json"]},
        ],
        "qwen_oauth_credentials": [
            {"path": "xiaoxihexiaoyu__AIClient-2-API/src/auth/qwen-oauth.js", "patterns": ["openai-qwen-oauth"]},
        ],
        "agent_runtime_endpoint": [
            {"path": "kittors__CliRelay/README_CN.md", "patterns": ["http://localhost:8317", "base_url"]},
        ],
    },
    "grok": {
        "grok_cookie_or_session": [
            {"path": "chenyme__grok2api/config.defaults.toml", "patterns": ["cf_cookies", "user_agent"]},
        ],
        "agent_profile": [
            {"path": "merterbak__Grok-MCP/docker-compose.yml", "patterns": ["XAI_API_KEY"]},
        ],
    },
    "jimeng": {
        "api_key": [
            {"path": "fkxianzhou__ComfyUI-Jimeng-API/api_keys.json.example", "patterns": ["apiKey"]},
        ],
    },
    "kling": {
        "kling_access_key": [
            {"path": "aself101__kling-api/README.md", "patterns": ["KLING_ACCESS_KEY"]},
        ],
        "kling_secret_key": [
            {"path": "aself101__kling-api/README.md", "patterns": ["KLING_SECRET_KEY"]},
        ],
        "mcp_agent_config_ref": [
            {"path": "199-mcp__mcp-kling/src/index.ts", "patterns": ["KLING_ACCESS_KEY", "KLING_SECRET_KEY"]},
        ],
    },
    "midjourney": {
        "discord_session_or_user_token": [
            {"path": "PlexPt__midjourney-proxy/src/main/resources/application.yml", "patterns": ["user-token"]},
        ],
        "discord_bot_token": [
            {"path": "PlexPt__midjourney-proxy/src/main/resources/application.yml", "patterns": ["bot-token"]},
        ],
        "guild_id": [
            {"path": "PlexPt__midjourney-proxy/src/main/resources/application.yml", "patterns": ["guild-id"]},
        ],
        "channel_id": [
            {"path": "PlexPt__midjourney-proxy/src/main/resources/application.yml", "patterns": ["channel-id"]},
        ],
        "discord_user_agent": [
            {"path": "novicezk__midjourney-proxy/docs/config.md", "patterns": ["user-agent"]},
        ],
        "discord_server": [
            {"path": "novicezk__midjourney-proxy/docs/config.md", "patterns": ["ng-discord.server"]},
        ],
        "discord_cdn": [
            {"path": "novicezk__midjourney-proxy/docs/config.md", "patterns": ["ng-discord.cdn"]},
        ],
        "discord_wss": [
            {"path": "novicezk__midjourney-proxy/docs/config.md", "patterns": ["ng-discord.wss"]},
        ],
    },
    "seedream_proxy": {
        "api_key": [
            {"path": "seedance-api__seedance-api/README.md", "patterns": ["api_key"]},
        ],
    },
    "luma": {
        "luma_api_key": [
            {"path": "bobtista__luma-ai-mcp-server/src/luma_ai_mcp_server/__init__.py", "patterns": ["--api-key", "LUMA_API_KEY"]},
        ],
    },
    "runway": {
        "useapi_api_key": [
            {"path": "lvalics__n8n-nodes-useapi/credentials/UseApiApi.credentials.ts", "patterns": ["apiKey"]},
        ],
        "runway_email": [
            {"path": "lvalics__n8n-nodes-useapi/credentials/UseApiApi.credentials.ts", "patterns": ["runwayEmail"]},
        ],
        "runway_password": [
            {"path": "lvalics__n8n-nodes-useapi/credentials/UseApiApi.credentials.ts", "patterns": ["runwayPassword"]},
        ],
    },
    "pollinations": {
        "pollinations_key": [
            {"path": "pollinations__pollinations/APIDOCS.md", "patterns": ["POLLINATIONS_KEY", "Authorization: Bearer"]},
        ],
        "self_hosted_endpoint": [
            {"path": "pollinations__pollinations/AGENTS.md", "patterns": ["localhost:8788"]},
        ],
    },
    "openrouter_image": {
        "openrouter_api_key": [
            {"path": "OpenRouterTeam__openrouter-examples/typescript/README.md", "patterns": ["OPENROUTER_API_KEY"]},
        ],
        "openrouter_api_key_n": [
            {"path": "Mirrowel__LLM-API-Key-Proxy/Deployment guide.md", "patterns": ["OPENROUTER_API_KEY_1"]},
        ],
        "anthropic_auth_token": [
            {"path": "OpenRouterTeam__openrouter-examples/claude-code/statusline.ts", "patterns": ["ANTHROPIC_AUTH_TOKEN"]},
        ],
        "anthropic_api_key": [
            {"path": "OpenRouterTeam__openrouter-examples/claude-code/statusline.ts", "patterns": ["ANTHROPIC_API_KEY"]},
        ],
        "channel_base_url": [
            {"path": "QuantumNous__new-api/web/default/src/i18n/locales/en.json", "patterns": ["Base URL is required for this channel type"]},
        ],
    },
    "fal_replicate": {
        "fal_key": [
            {"path": "fal-ai__fal-js/README.md", "patterns": ["FAL_KEY"]},
        ],
        "replicate_api_token": [
            {"path": "replicate__replicate-python/README.md", "patterns": ["REPLICATE_API_TOKEN"]},
        ],
        "sdk_runtime_endpoint": [
            {"path": "fal-ai__fal-js/libs/proxy/README.md", "patterns": ["/api/fal/proxy"]},
        ],
    },
    "amux_qwen": {
        "qwen_oauth_creds_file": [
            {"path": "xiaoxihexiaoyu__AIClient-2-API/src/services/api-server.js", "patterns": ["--qwen-oauth-creds-file"]},
        ],
        "qwen_oauth_cache_path": [
            {"path": "xiaoxihexiaoyu__AIClient-2-API/static/app/provider-manager.js", "patterns": ["~/.qwen/oauth_creds.json"]},
        ],
        "qwen_oauth_credentials": [
            {"path": "xiaoxihexiaoyu__AIClient-2-API/src/auth/qwen-oauth.js", "patterns": ["openai-qwen-oauth"]},
        ],
        "agent_runtime_endpoint": [
            {"path": "kittors__CliRelay/README_CN.md", "patterns": ["http://localhost:8317", "base_url"]},
        ],
    },
    "flux_stability": {
        "comfyui_workflow_api_json": [
            {"path": "jau123__MeiGen-AI-Design-MCP/plugin/commands/setup.md", "patterns": ["workflow_api.json"]},
        ],
        "model_config_json": [
            {"path": "HanseWare__FastFusion/README.md", "patterns": ["model_config.json"]},
        ],
        "meigen_mcp_config": [
            {"path": "jau123__MeiGen-AI-Design-MCP/src/cli/init.ts", "patterns": ["mcp_config.json"]},
        ],
        "self_hosted_endpoint": [
            {"path": "HanseWare__FastFusion/README.md", "patterns": ["http://localhost:8000"]},
        ],
    },
}


def fail(message: str, detail: Any) -> None:
    raise AssertionError(f"{message}: {json.dumps(detail, ensure_ascii=False, sort_keys=True)}")


def field_names(provider_id: str) -> set[str]:
    requirements = PLATFORM_INPUT_REQUIREMENTS.get(provider_id)
    if not requirements:
        fail("provider missing platform input requirements", {"provider_id": provider_id})
    return {str(item.get("name")) for item in requirements.get("user_inputs") or [] if item.get("name")}


def spec_passes(spec: EvidenceSpec) -> bool:
    evidence_path = SOURCE_REPO / str(spec["path"])
    if not evidence_path.is_file():
        fail("evidence file is missing", {"path": str(evidence_path)})
    content = evidence_path.read_text(encoding="utf-8", errors="ignore").casefold()
    missing = [pattern for pattern in spec["patterns"] if str(pattern).casefold() not in content]
    if missing:
        return False
    return True


def main() -> None:
    if not SOURCE_REPO.is_dir():
        fail("source-repo is required for source evidence audit", {"path": str(SOURCE_REPO)})

    target_providers = {row[0] for row in TARGET_MODEL_TABLE}
    missing_provider_specs = sorted(target_providers - set(EVIDENCE_SPECS))
    extra_provider_specs = sorted(set(EVIDENCE_SPECS) - target_providers)
    if missing_provider_specs or extra_provider_specs:
        fail(
            "source evidence provider coverage drifted",
            {"missing": missing_provider_specs, "extra": extra_provider_specs},
        )

    checks = 0
    summary: dict[str, Any] = {"providers": 0, "fields": 0, "evidence_checks": 0}
    for provider_id in sorted(target_providers):
        actual_fields = field_names(provider_id)
        specified_fields = set(EVIDENCE_SPECS[provider_id])
        if actual_fields != specified_fields:
            fail(
                "source evidence field coverage drifted",
                {
                    "provider_id": provider_id,
                    "missing": sorted(actual_fields - specified_fields),
                    "extra": sorted(specified_fields - actual_fields),
                },
            )

        for field_name in sorted(actual_fields):
            specs = EVIDENCE_SPECS[provider_id][field_name]
            if not specs:
                fail("source evidence field has no specs", {"provider_id": provider_id, "field_name": field_name})
            passed = [spec for spec in specs if spec_passes(spec)]
            checks += len(specs)
            if not passed:
                fail(
                    "source evidence patterns not found",
                    {"provider_id": provider_id, "field_name": field_name, "specs": specs},
                )
            summary["fields"] += 1

        summary["providers"] += 1

    summary["evidence_checks"] = checks
    print(json.dumps({"status": "ok", **summary}, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
