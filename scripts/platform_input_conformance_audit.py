from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from media2api.catalog import TARGET_MODEL_TABLE
from media2api.services_connector_registry import PLATFORM_INPUT_REQUIREMENTS, REFERENCE_AUTH_TYPES, RUNTIME_BASE_URL_INPUT_NAMES


ALLOWED_RESOURCE_TYPES = {"web_cookie_provider", "agent_provider"}
ALLOWED_AUTH_METHODS = {"cookie_secret", "agent_provider_credential"}

EXPECTED_FIELDS: dict[str, dict[str, set[str]]] = {
    "openai_image": {
        "credentials": {"cookie_header_or_cookie_jar", "agent_profile"},
        "profile": set(),
        "runtime": {"connector_base_url"},
    },
    "gemini": {
        "credentials": {
            "gemini_credentials",
            "google_application_credentials",
            "gemini_oauth_creds_base64",
            "gemini_oauth_creds_file",
            "gemini_project_id",
        },
        "profile": set(),
        "runtime": {"agent_runtime_endpoint"},
    },
    "grok": {
        "credentials": {"grok_cookie_or_session", "agent_profile"},
        "profile": set(),
        "runtime": set(),
    },
    "qwen": {
        "credentials": {"qwen_oauth_creds_file", "qwen_oauth_cache_path", "qwen_oauth_credentials"},
        "profile": set(),
        "runtime": {"agent_runtime_endpoint"},
    },
    "jimeng": {
        "credentials": {"api_key"},
        "profile": set(),
        "runtime": set(),
    },
    "kling": {
        "credentials": {"kling_access_key", "kling_secret_key", "mcp_agent_config_ref"},
        "profile": set(),
        "runtime": set(),
    },
    "luma": {
        "credentials": {"luma_api_key"},
        "profile": set(),
        "runtime": set(),
    },
    "runway": {
        "credentials": {"useapi_api_key", "runway_email", "runway_password"},
        "profile": set(),
        "runtime": set(),
    },
    "midjourney": {
        "credentials": {"discord_session_or_user_token", "discord_bot_token"},
        "profile": {"guild_id", "channel_id", "discord_user_agent", "discord_server", "discord_cdn", "discord_wss"},
        "runtime": set(),
    },
    "pollinations": {
        "credentials": {"pollinations_key"},
        "profile": set(),
        "runtime": {"self_hosted_endpoint"},
    },
    "openrouter_image": {
        "credentials": {"openrouter_api_key", "openrouter_api_key_n", "anthropic_auth_token", "anthropic_api_key"},
        "profile": set(),
        "runtime": {"channel_base_url"},
    },
    "fal_replicate": {
        "credentials": {"fal_key", "replicate_api_token"},
        "profile": set(),
        "runtime": {"sdk_runtime_endpoint"},
    },
    "seedream_proxy": {
        "credentials": {"api_key"},
        "profile": set(),
        "runtime": set(),
    },
    "amux_qwen": {
        "credentials": {"qwen_oauth_creds_file", "qwen_oauth_cache_path", "qwen_oauth_credentials"},
        "profile": set(),
        "runtime": {"agent_runtime_endpoint"},
    },
    "flux_stability": {
        "credentials": {"comfyui_workflow_api_json", "model_config_json", "meigen_mcp_config"},
        "profile": set(),
        "runtime": {"self_hosted_endpoint"},
    },
}


EXPECTED_REQUIRED_CREDENTIALS: dict[str, set[str]] = {
    "openai_image": {"cookie_header_or_cookie_jar"},
    "gemini": {"gemini_credentials", "google_application_credentials", "gemini_oauth_creds_base64", "gemini_oauth_creds_file"},
    "grok": {"grok_cookie_or_session"},
    "qwen": {"qwen_oauth_creds_file", "qwen_oauth_cache_path", "qwen_oauth_credentials"},
    "jimeng": {"api_key"},
    "kling": {"kling_access_key", "kling_secret_key"},
    "luma": {"luma_api_key"},
    "runway": {"useapi_api_key"},
    "midjourney": {"discord_session_or_user_token"},
    "pollinations": {"pollinations_key"},
    "openrouter_image": {"openrouter_api_key", "openrouter_api_key_n", "anthropic_auth_token", "anthropic_api_key"},
    "fal_replicate": {"fal_key", "replicate_api_token"},
    "seedream_proxy": {"api_key"},
    "amux_qwen": {"qwen_oauth_creds_file", "qwen_oauth_cache_path", "qwen_oauth_credentials"},
    "flux_stability": {"comfyui_workflow_api_json", "model_config_json", "meigen_mcp_config"},
}


EXPECTED_REQUIRED_PROFILE: dict[str, set[str]] = {
    "midjourney": {"guild_id", "channel_id"},
}


def names(items: list[dict[str, Any]], predicate) -> set[str]:
    return {str(item.get("name")) for item in items if item.get("name") and predicate(item)}


def fail(message: str, detail: Any) -> None:
    raise AssertionError(f"{message}: {json.dumps(detail, ensure_ascii=False, sort_keys=True)}")


def main() -> None:
    if set(REFERENCE_AUTH_TYPES) != ALLOWED_AUTH_METHODS:
        fail("registry exposes non-product auth methods", {"expected": sorted(ALLOWED_AUTH_METHODS), "actual": REFERENCE_AUTH_TYPES})

    target_providers = {row[0] for row in TARGET_MODEL_TABLE}
    configured_providers = set(PLATFORM_INPUT_REQUIREMENTS)
    missing = sorted(target_providers - configured_providers)
    if missing:
        fail("TARGET_MODEL_TABLE providers missing platform input requirements", missing)

    extra_expected = sorted(target_providers - set(EXPECTED_FIELDS))
    if extra_expected:
        fail("audit expected field matrix is missing providers", extra_expected)

    summary: dict[str, Any] = {"providers": 0, "runtime_base_url_allowed": [], "runtime_base_url_blocked": []}
    for provider_id in sorted(target_providers):
        requirements = PLATFORM_INPUT_REQUIREMENTS[provider_id]
        user_inputs = list(requirements.get("user_inputs") or [])
        primary_resource_type = str(requirements.get("primary_resource_type") or "")
        accepted_resource_types = {str(item) for item in requirements.get("accepted_resource_types") or [primary_resource_type]}
        if primary_resource_type not in ALLOWED_RESOURCE_TYPES:
            fail("provider has non-product primary resource type", {"provider_id": provider_id, "primary_resource_type": primary_resource_type})
        if not accepted_resource_types or not accepted_resource_types.issubset(ALLOWED_RESOURCE_TYPES):
            fail("provider has non-product accepted resource types", {"provider_id": provider_id, "accepted_resource_types": sorted(accepted_resource_types)})
        if not user_inputs:
            fail("provider has no user input profile", {"provider_id": provider_id})

        for item in user_inputs:
            auth_method = str(item.get("auth_method") or "")
            if auth_method and auth_method not in ALLOWED_AUTH_METHODS:
                fail("provider exposes non-product auth method", {"provider_id": provider_id, "item": item})
            if item.get("name") in RUNTIME_BASE_URL_INPUT_NAMES and item.get("required"):
                fail("runtime/baseURL field must never be required", {"provider_id": provider_id, "item": item})
            if not item.get("evidence"):
                fail("platform input is missing open-source evidence", {"provider_id": provider_id, "item": item})

        actual = {
            "credentials": names(user_inputs, lambda item: bool(item.get("auth_method") or item.get("store_as"))),
            "profile": names(
                user_inputs,
                lambda item: item.get("name") not in RUNTIME_BASE_URL_INPUT_NAMES and not item.get("auth_method") and not item.get("store_as"),
            ),
            "runtime": names(user_inputs, lambda item: item.get("name") in RUNTIME_BASE_URL_INPUT_NAMES),
        }
        expected = EXPECTED_FIELDS[provider_id]
        if actual != expected:
            fail("provider user input field matrix drifted", {"provider_id": provider_id, "expected": sorted_map(expected), "actual": sorted_map(actual)})

        required_credentials = names(user_inputs, lambda item: item.get("required") and bool(item.get("auth_method") or item.get("store_as")))
        if required_credentials != EXPECTED_REQUIRED_CREDENTIALS[provider_id]:
            fail(
                "provider required credential fields drifted",
                {"provider_id": provider_id, "expected": sorted(EXPECTED_REQUIRED_CREDENTIALS[provider_id]), "actual": sorted(required_credentials)},
            )

        required_profile = names(
            user_inputs,
            lambda item: item.get("required")
            and item.get("name") not in RUNTIME_BASE_URL_INPUT_NAMES
            and not item.get("auth_method")
            and not item.get("store_as"),
        )
        if required_profile != EXPECTED_REQUIRED_PROFILE.get(provider_id, set()):
            fail(
                "provider required resource_profile fields drifted",
                {"provider_id": provider_id, "expected": sorted(EXPECTED_REQUIRED_PROFILE.get(provider_id, set())), "actual": sorted(required_profile)},
            )

        if actual["runtime"]:
            summary["runtime_base_url_allowed"].append(provider_id)
        else:
            summary["runtime_base_url_blocked"].append(provider_id)
        summary["providers"] += 1

    print(json.dumps({"status": "ok", **summary}, ensure_ascii=False, sort_keys=True))


def sorted_map(value: dict[str, set[str]]) -> dict[str, list[str]]:
    return {key: sorted(items) for key, items in value.items()}


if __name__ == "__main__":
    main()
