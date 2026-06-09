from __future__ import annotations

import json
from typing import Any
import urllib.request

from .services_connector_registry import PLATFORM_INPUT_REQUIREMENTS, PROVIDER_RESOURCE_DEFAULTS, RUNTIME_BASE_URL_INPUT_NAMES
from .utils import redact_sensitive


ACCOUNT_CONTAINER_KEYS = (
    "accounts",
    "resources",
    "items",
    "data",
    "subscriptions",
    "credentials",
    "results",
)

CREDENTIAL_REF_KEYS = (
    "credential_ref",
    "credentialRef",
    "credential_reference",
    "credentialReference",
    "token_reference",
    "tokenReference",
    "token_ref",
    "tokenRef",
    "oauth_ref",
    "oauthRef",
    "oauth_reference",
    "oauthReference",
    "cli_ref",
    "cliRef",
    "cli_credential_ref",
    "cliCredentialRef",
    "cli_credential_reference",
    "cliCredentialReference",
    "web_session_ref",
    "webSessionRef",
    "websession_ref",
    "websessionRef",
    "web_session_reference",
    "webSessionReference",
    "mcp_config_ref",
    "mcpConfigRef",
    "mcp_config_reference",
    "mcpConfigReference",
    "endpoint_ref",
    "endpointRef",
    "self_hosted_endpoint",
    "selfHostedEndpoint",
    "self_hosted_endpoint_ref",
    "selfHostedEndpointRef",
    "account_ref",
    "accountRef",
    "subscription_ref",
    "subscriptionRef",
    "vault_ref",
    "vaultRef",
    "secret_ref",
    "secretRef",
    "env_ref",
    "envRef",
    "resource_ref",
    "resourceRef",
    "ref",
)

RAW_CREDENTIAL_KEYS = (
    "credential_value",
    "credentialValue",
    "credential",
    "value",
    "token",
    "access_token",
    "accessToken",
    "refresh_token",
    "refreshToken",
    "id_token",
    "idToken",
    "session_token",
    "sessionToken",
    "session",
    "cookies",
    "cookie",
    "cookie_header",
    "cookieHeader",
    "authorization",
    "Authorization",
    "bearer_token",
    "bearerToken",
    "subscription_url",
    "subscriptionUrl",
)

STRUCTURED_CREDENTIAL_KEYS = (
    "GEMINI_CREDENTIALS",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "GEMINI_PROJECT_ID",
    "GOOGLE_CLOUD_PROJECT",
    "gemini_credentials",
    "google_application_credentials",
    "gemini_oauth_creds_base64",
    "gemini_oauth_creds_file",
    "gemini_project_id",
    "KLING_ACCESS_KEY",
    "KLING_SECRET_KEY",
    "kling_access_key",
    "kling_secret_key",
    "QWEN_OAUTH_CREDS_FILE",
    "qwen_oauth_creds_file",
    "qwen_oauth_cache_path",
    "qwen_oauth_credentials",
    "api_key",
    "apiKey",
    "LUMA_API_KEY",
    "luma_api_key",
    "USEAPI_API_KEY",
    "useapi_api_key",
    "runwayEmail",
    "runway_email",
    "runwayPassword",
    "runway_password",
    "POLLINATIONS_KEY",
    "POLLINATIONS_API_KEY",
    "pollinations_key",
    "pollinations_api_key",
    "OPENROUTER_API_KEY",
    "OPENROUTER_API_KEY_1",
    "OPENROUTER_API_KEY_2",
    "openrouter_api_key",
    "openrouter_api_key_n",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_API_KEY",
    "anthropic_auth_token",
    "anthropic_api_key",
    "FAL_KEY",
    "fal_key",
    "REPLICATE_API_TOKEN",
    "replicate_api_token",
    "comfyui_workflow_api_json",
    "workflow_api_json",
    "model_config_json",
    "meigen_mcp_config",
    "mcp_config",
)

SAFE_EXTERNAL_REF_PREFIXES = (
    "env://",
    "secret://",
    "public://",
    "vault://",
    "subscription://",
    "oauth://",
    "cli://",
    "websession://",
    "mcp://",
    "endpoint://",
    "connector://",
    "tokenref://",
    "agent://",
)

AUTH_METHOD_ALIASES = {
    "token": "agent_provider_credential",
    "token_reference": "agent_provider_credential",
    "tokenref": "agent_provider_credential",
    "subscription": "agent_provider_credential",
    "subscription_url": "agent_provider_credential",
    "sub": "agent_provider_credential",
    "oauth": "agent_provider_credential",
    "oauth_ref": "agent_provider_credential",
    "oauth_reference": "agent_provider_credential",
    "cli": "agent_provider_credential",
    "cli_credential": "agent_provider_credential",
    "cli_credential_reference": "agent_provider_credential",
    "web": "cookie_secret",
    "web_session": "cookie_secret",
    "websession": "cookie_secret",
    "browser_session": "cookie_secret",
    "cookie": "cookie_secret",
    "cookie_secret": "cookie_secret",
    "cookie_header": "cookie_secret",
    "cookie_jar": "cookie_secret",
    "agent": "agent_provider_credential",
    "agent_provider": "agent_provider_credential",
    "agent_provider_credential": "agent_provider_credential",
    "mcp": "agent_provider_credential",
    "mcp_config": "agent_provider_credential",
    "mcp_config_reference": "agent_provider_credential",
    "endpoint": "agent_provider_credential",
    "self_hosted": "agent_provider_credential",
    "self_hosted_endpoint": "agent_provider_credential",
    "aggregator": "agent_provider_credential",
    "aggregator_api_key": "agent_provider_credential",
    "api_key": "agent_provider_credential",
    "secret_json": "agent_provider_credential",
}

AUTH_METHOD_BY_REF_PREFIX = {
    "subscription://": "agent_provider_credential",
    "oauth://": "agent_provider_credential",
    "cli://": "agent_provider_credential",
    "websession://": "cookie_secret",
    "agent://": "agent_provider_credential",
    "mcp://": "agent_provider_credential",
    "endpoint://": "agent_provider_credential",
    "tokenref://": "agent_provider_credential",
    "connector://": "agent_provider_credential",
    "vault://": "agent_provider_credential",
}

AGENT_PROVIDER_CREDENTIAL_KIND_ALIASES = {
    "agent",
    "agent_provider",
    "agent_provider_credential",
    "api_key",
    "aggregator_api_key",
    "bearer",
    "bearer_token",
    "cli",
    "cli_credential",
    "cli_credential_reference",
    "mcp",
    "mcp_config",
    "mcp_config_reference",
    "oauth",
    "oauth_ref",
    "oauth_reference",
    "secret_json",
    "self_hosted",
    "self_hosted_endpoint",
    "subscription",
    "subscription_url",
    "token",
    "token_reference",
    "tokenref",
}

COOKIE_CREDENTIAL_KIND_ALIASES = {
    "browser_session",
    "cookie",
    "cookie_header",
    "cookie_jar",
    "cookie_secret",
    "session",
    "web",
    "web_session",
    "web_session_reference",
    "websession",
}

OPERATION_ALIASES = {
    "t2i": "text_to_image",
    "txt2img": "text_to_image",
    "text2image": "text_to_image",
    "text_to_image": "text_to_image",
    "image_generation": "text_to_image",
    "image": "text_to_image",
    "i2i": "image_to_image",
    "img2img": "image_to_image",
    "image2image": "image_to_image",
    "image_to_image": "image_to_image",
    "edit": "image_edit",
    "image_edit": "image_edit",
    "inpaint": "image_edit",
    "t2v": "text_to_video",
    "txt2video": "text_to_video",
    "text2video": "text_to_video",
    "text_to_video": "text_to_video",
    "video_generation": "text_to_video",
    "video": "text_to_video",
    "i2v": "image_to_video",
    "img2video": "image_to_video",
    "image2video": "image_to_video",
    "image_to_video": "image_to_video",
    "extend": "video_extend",
    "video_extend": "video_extend",
}

PROVIDER_ID_KEYS = ("provider_id", "providerId", "provider", "platform", "service", "vendor")
AUTH_METHOD_KEYS = ("auth_method", "authMethod", "auth_type", "authType", "type", "kind")
ACCOUNT_ID_KEYS = ("account_id", "accountId", "id", "account", "resource_id", "resourceId", "name")
LABEL_KEYS = ("label", "name", "display_name", "displayName", "title", "account_id", "accountId", "id")
BASE_URL_KEYS = ("provider_base_url", "providerBaseUrl", "connector_base_url", "connectorBaseUrl", "base_url", "baseUrl", "upstream_url", "upstreamUrl", "endpoint")
OPERATIONS_KEYS = ("supported_operations", "supportedOperations", "operations", "operation", "capabilities")
PROVIDER_MODELS_KEYS = ("supported_provider_models", "supportedProviderModels", "provider_models", "providerModels", "models", "model_ids", "modelIds", "model")
NESTED_CONTEXT_KEYS = ("account", "resource", "credential", "credentials", "auth", "authorization_info", "authorizationInfo", "session", "metadata")
RESOURCE_TYPE_KEYS = ("resource_type", "resourceType", "source_type", "sourceType", "kind")
RESOURCE_PROFILE_KEYS = ("resource_profile", "resourceProfile", "profile", "agent_profile", "agentProfile", "runtime", "session_profile", "sessionProfile")
RUNTIME_PROFILE_KEYS = tuple(
    dict.fromkeys(
        BASE_URL_KEYS
        + (
            "agent_runtime_endpoint",
            "agentRuntimeEndpoint",
            "runtime_endpoint",
            "runtimeEndpoint",
            "runner_endpoint",
            "runnerEndpoint",
            "channel_base_url",
            "channelBaseUrl",
            "sdk_runtime_endpoint",
            "sdkRuntimeEndpoint",
            "self_hosted_endpoint",
            "selfHostedEndpoint",
        )
    )
)


def _provider_runtime_profile_key(provider_id: str) -> str:
    requirements = PLATFORM_INPUT_REQUIREMENTS.get(provider_id, {})
    for item in requirements.get("user_inputs", []):
        name = str(item.get("name") or "").strip()
        if name in RUNTIME_BASE_URL_INPUT_NAMES:
            return name
    return "connector_base_url" if provider_id not in PLATFORM_INPUT_REQUIREMENTS else ""


def _first_value(row: dict[str, Any], keys: tuple[str, ...] | list[str]) -> Any:
    for key in keys:
        value = row.get(key)
        if value is not None and value != "":
            return value
    return None


def _nested_dicts(row: dict[str, Any]) -> list[dict[str, Any]]:
    nested: list[dict[str, Any]] = []
    for key in NESTED_CONTEXT_KEYS:
        value = row.get(key)
        if isinstance(value, dict):
            nested.append(value)
    return nested


def _first_deep_value(row: dict[str, Any], keys: tuple[str, ...] | list[str]) -> Any:
    value = _first_value(row, keys)
    if value is not None:
        return value
    for child in _nested_dicts(row):
        value = _first_value(child, keys)
        if value is not None:
            return value
    return None


def _structured_credential_value(row: dict[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for source in [row, *_nested_dicts(row)]:
        for key in STRUCTURED_CREDENTIAL_KEYS:
            value = source.get(key)
            if value is not None and value != "":
                values[key] = value
    return values


def _list_value(value: Any) -> list[Any]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass
        return [item.strip() for item in stripped.split(",") if item.strip()]
    return [value]


def _string_list_value(value: Any, *, keys: tuple[str, ...] = ("id", "name", "model", "value")) -> list[str]:
    values: list[str] = []
    for item in _list_value(value):
        if isinstance(item, dict):
            selected = _first_value(item, keys)
            if selected is not None:
                values.extend(_string_list_value(selected, keys=keys))
            continue
        text = str(item).strip()
        if text:
            values.append(text)
    return values


def _normalize_operation(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    key = text.lower().replace("-", "_").replace(" ", "_").replace("/", "_")
    return OPERATION_ALIASES.get(key, text)


def _operations_from_models(value: Any) -> list[str]:
    operations: list[str] = []
    for item in _list_value(value):
        if not isinstance(item, dict):
            continue
        for op in _string_list_value(_first_value(item, OPERATIONS_KEYS) or item.get("capabilities")):
            normalized = _normalize_operation(op)
            if normalized and normalized not in operations:
                operations.append(normalized)
    return operations


def _model_operation_hints(value: Any) -> dict[str, list[str]]:
    hints: dict[str, list[str]] = {}
    for item in _list_value(value):
        if not isinstance(item, dict):
            continue
        model_id = _first_value(item, ("id", "name", "model", "provider_model", "providerModel", "value"))
        if model_id is None:
            continue
        operations = _normalize_operations(_first_value(item, OPERATIONS_KEYS) or item.get("capabilities"))
        if operations:
            hints[str(model_id)] = operations
    return hints


def _normalize_operations(value: Any) -> list[str]:
    operations: list[str] = []
    for item in _string_list_value(value, keys=("id", "name", "operation", "value")):
        normalized = _normalize_operation(item)
        if normalized and normalized not in operations:
            operations.append(normalized)
    return operations


def _dict_value(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return {}
    return {}


def _int_value(value: Any, default: int) -> int:
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return default


def _is_safe_ref(value: str) -> bool:
    return value.startswith(SAFE_EXTERNAL_REF_PREFIXES)


def _normalize_auth_method(value: Any, credential_ref: str = "") -> str:
    text = str(value or "").strip()
    normalized = AUTH_METHOD_ALIASES.get(text.lower().replace("-", "_").replace(" ", "_"))
    if normalized:
        return normalized
    for prefix, method in AUTH_METHOD_BY_REF_PREFIX.items():
        if credential_ref.startswith(prefix):
            return method
    return text


def _normalize_credential_kind(value: Any, *, auth_method: str = "", raw_credential_field: str = "") -> str:
    text = str(value or "").strip()
    normalized = text.lower().replace("-", "_").replace(" ", "_")
    raw_field = raw_credential_field.lower().replace("-", "_").replace(" ", "_")
    if normalized in COOKIE_CREDENTIAL_KIND_ALIASES:
        return "cookie"
    if normalized in AGENT_PROVIDER_CREDENTIAL_KIND_ALIASES:
        return "agent_provider"
    if raw_field in {"api_key", "apikey", "authorization", "bearer_token", "token"}:
        return "agent_provider"
    if auth_method == "cookie_secret":
        return "cookie"
    if auth_method == "agent_provider_credential":
        return "agent_provider"
    return text


def _infer_resource_type(provider_id: str, auth_method: str, item: dict[str, Any], request: dict[str, Any]) -> str:
    explicit = str(_first_deep_value(item, RESOURCE_TYPE_KEYS) or request.get("resource_type") or "").strip()
    if explicit:
        return explicit
    if auth_method in {"cookie_secret", "web_session_reference"}:
        return "web_cookie_provider"
    if auth_method in {"agent_provider_credential", "cli_credential_reference", "mcp_config_reference", "oauth_reference"}:
        return "agent_provider"
    if any(_first_deep_value(item, (key,)) for key in ("cookie", "cookies", "cookie_header", "cookieHeader", "session_token", "sessionToken")):
        return "web_cookie_provider"
    if any(_first_deep_value(item, (key,)) for key in ("agent_profile", "agentProfile", "cli_profile", "cliProfile", "mcp_config", "mcpConfig")):
        return "agent_provider"
    return PROVIDER_RESOURCE_DEFAULTS.get(provider_id, "agent_provider")


def _resource_profile(provider_id: str, item: dict[str, Any], request: dict[str, Any], *, provider_base_url: Any, resource_type: str, auth_method: str) -> dict[str, Any]:
    profile = _dict_value(request.get("resource_profile"))
    for value in (_first_deep_value(item, RESOURCE_PROFILE_KEYS), item.get("metadata")):
        profile.update(_dict_value(value))
    for key in (
        "cookie_domain_scope",
        "domain",
        "guild_id",
        "guildId",
        "channel_id",
        "channelId",
        "discord_server",
        "server",
        "agent_runtime_endpoint",
        "runtime_endpoint",
        "workspace_policy",
        "network_policy",
        "session_expires_at",
        "expires_at",
    ):
        value = _first_deep_value(item, (key,))
        if value is not None and value != "":
            profile[key] = value
    runtime_key = _provider_runtime_profile_key(provider_id)
    runtime_value = str(provider_base_url).strip() if provider_base_url else ""
    if runtime_key:
        for key in RUNTIME_PROFILE_KEYS:
            value = profile.pop(key, None)
            if not runtime_value and value is not None and str(value).strip():
                runtime_value = str(value).strip()
        if runtime_value:
            profile[runtime_key] = runtime_value
    profile["resource_type"] = resource_type
    profile["auth_method"] = auth_method
    if provider_base_url and not runtime_key:
        profile["connector_base_url"] = str(provider_base_url).strip()
    return profile


def _quota_buckets_value(item: dict[str, Any], request: dict[str, Any]) -> list[dict[str, Any]]:
    quota_value = _first_deep_value(item, ("quota_buckets", "quotaBuckets", "quotas", "quota", "limits", "usage"))
    if quota_value is None:
        quota_value = request.get("quota_buckets")
    if isinstance(quota_value, list):
        return [value for value in quota_value if isinstance(value, dict)]
    if isinstance(quota_value, dict):
        if any(key in quota_value for key in ("type", "remaining_estimate", "remaining", "limit", "used", "reset_at")):
            bucket = {
                "type": quota_value.get("type") or quota_value.get("name") or "credits",
                "remaining_estimate": quota_value.get("remaining_estimate", quota_value.get("remaining", quota_value.get("balance"))),
                "limit": quota_value.get("limit"),
                "used": quota_value.get("used"),
                "reset_at": quota_value.get("reset_at") or quota_value.get("resetAt"),
                "confidence": quota_value.get("confidence"),
            }
            return [{key: value for key, value in bucket.items() if value is not None and value != ""}]
        return [quota_value]
    for key in ("remaining_credits", "remainingCredits", "balance", "credits", "quota_remaining", "quotaRemaining"):
        value = _first_deep_value(item, (key,))
        if value is not None and value != "":
            return [{"type": "credits", "remaining_estimate": value, "confidence": 0.5}]
    return []


def _extract_items_from_json(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if not isinstance(value, dict):
        return []
    for key in ACCOUNT_CONTAINER_KEYS:
        child = value.get(key)
        if isinstance(child, list):
            return [item for item in child if isinstance(item, dict)]
        if isinstance(child, dict):
            if all(isinstance(item, dict) for item in child.values()):
                rows: list[dict[str, Any]] = []
                for child_key, item in child.items():
                    row = dict(item)
                    row.setdefault("account_id", child_key)
                    rows.append(row)
                return rows
            return _extract_items_from_json(child)
    if any(key in value for key in CREDENTIAL_REF_KEYS + RAW_CREDENTIAL_KEYS + ("account_id", "id", "label", "provider_id")):
        return [value]
    return []


def parse_account_import_content(content: str) -> list[dict[str, Any]]:
    stripped = (content or "").strip()
    if not stripped:
        return []
    if stripped[0] in "[{":
        parsed = json.loads(stripped)
        return _extract_items_from_json(parsed)
    rows: list[dict[str, Any]] = []
    for line in stripped.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parsed = json.loads(line)
        if isinstance(parsed, dict):
            rows.append(parsed)
    return rows


def sanitize_import_plan(plan: dict[str, Any]) -> dict[str, Any]:
    clean = dict(plan)
    rows: list[dict[str, Any]] = []
    for row in clean.get("data", []):
        row_copy = dict(row)
        raw_payload = dict(row_copy.get("onboarding_request") or {})
        payload = dict(raw_payload)
        if payload.get("credential_value"):
            payload["credential_value"] = "[secret]"
        payload = redact_sensitive(payload)
        payload["credential_value"] = "[secret]" if raw_payload.get("credential_value") else ""
        credential_ref = str(raw_payload.get("credential_ref") or "")
        if credential_ref and _is_safe_ref(credential_ref):
            payload["credential_ref"] = credential_ref
        else:
            payload["credential_ref"] = "[secret]" if credential_ref else None
        payload["credential_kind"] = raw_payload.get("credential_kind") or ""
        payload["credential_secret_id"] = raw_payload.get("credential_secret_id")
        row_copy["onboarding_request"] = payload
        rows.append(row_copy)
    clean["data"] = rows
    return clean


class AccountSubscriptionImportService:
    def __init__(self, allowed_auth_methods: list[str], *, max_fetch_bytes: int = 1_000_000) -> None:
        self.allowed_auth_methods = set(allowed_auth_methods)
        self.max_fetch_bytes = max_fetch_bytes

    def fetch_subscription(self, url: str, *, timeout_seconds: int = 15) -> str:
        url = (url or "").strip()
        if not url.startswith(("http://", "https://")):
            raise ValueError("SUBSCRIPTION_URL_HTTP_REQUIRED")
        request = urllib.request.Request(url, headers={"User-Agent": "media2api-account-import/0.1"})
        with urllib.request.urlopen(request, timeout=max(1, int(timeout_seconds))) as response:
            data = response.read(self.max_fetch_bytes + 1)
        if len(data) > self.max_fetch_bytes:
            raise ValueError("SUBSCRIPTION_PAYLOAD_TOO_LARGE")
        return data.decode("utf-8")

    def build_plan(self, request: dict[str, Any]) -> dict[str, Any]:
        provider_id = str(request.get("provider_id") or "").strip()
        auth_method = _normalize_auth_method(request.get("auth_method") or "agent_provider_credential")
        if not provider_id:
            raise ValueError("PROVIDER_ID_REQUIRED")
        if auth_method not in self.allowed_auth_methods:
            raise ValueError("AUTH_METHOD_UNSUPPORTED")

        source_items: list[dict[str, Any]] = []
        source_summary = {
            "accounts": 0,
            "content": 0,
            "subscription_url": bool(request.get("subscription_url")),
            "subscription_url_fetched": False,
        }
        accounts = request.get("accounts") or []
        if isinstance(accounts, list):
            source_accounts = [item for item in accounts if isinstance(item, dict)]
            source_summary["accounts"] = len(source_accounts)
            source_items.extend(source_accounts)
        content = str(request.get("content") or "").strip()
        if content:
            parsed_content = parse_account_import_content(content)
            source_summary["content"] = len(parsed_content)
            source_items.extend(parsed_content)
        if request.get("subscription_url"):
            fetched = self.fetch_subscription(str(request["subscription_url"]), timeout_seconds=int(request.get("fetch_timeout_seconds") or 15))
            parsed_fetched = parse_account_import_content(fetched)
            source_summary["subscription_url_fetched"] = True
            source_summary["subscription_url_items"] = len(parsed_fetched)
            source_items.extend(parsed_fetched)

        max_items = _int_value(request.get("max_items"), 200)
        if len(source_items) > max_items:
            raise ValueError("ACCOUNT_IMPORT_MAX_ITEMS_EXCEEDED")

        rows: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        for index, item in enumerate(source_items):
            try:
                payload = self.normalize_item(item, request, index=index)
                rows.append(
                    {
                        "index": index,
                        "provider_id": payload["provider_id"],
                        "account_id": payload.get("account_id"),
                        "label": payload["label"],
                        "auth_method": payload["auth_method"],
                        "credential_mode": "reference" if payload.get("credential_ref") else "secret",
                        "onboarding_request": payload,
                    }
                )
            except ValueError as exc:
                errors.append({"index": index, "error": str(exc), "source": redact_sensitive(item)})

        return {
            "object": "media2api.account_subscription_import_plan",
            "provider_id": provider_id,
            "auth_method": auth_method,
            "source": source_summary,
            "planned": len(rows),
            "failed": len(errors),
            "data": rows,
            "errors": errors,
        }

    def normalize_item(self, item: dict[str, Any], request: dict[str, Any], *, index: int) -> dict[str, Any]:
        provider_id = str(_first_deep_value(item, PROVIDER_ID_KEYS) or request.get("provider_id") or "").strip()
        auth_method = _normalize_auth_method(_first_deep_value(item, AUTH_METHOD_KEYS) or request.get("auth_method") or "agent_provider_credential")
        if not provider_id:
            raise ValueError("PROVIDER_ID_REQUIRED")
        if auth_method not in self.allowed_auth_methods:
            raise ValueError("AUTH_METHOD_UNSUPPORTED")

        account_id = _first_deep_value(item, ACCOUNT_ID_KEYS)
        label = _first_deep_value(item, LABEL_KEYS) or f"{provider_id}-{index + 1}"
        provider_base_url = _first_deep_value(item, BASE_URL_KEYS) or request.get("provider_base_url")
        provider_config = dict(_dict_value(request.get("provider_config")))
        provider_config.update(_dict_value(item.get("provider_config") or item.get("config")))
        model_value = _first_deep_value(item, PROVIDER_MODELS_KEYS)
        model_operation_hints = _model_operation_hints(model_value)
        supported_operations = _normalize_operations(_first_deep_value(item, OPERATIONS_KEYS))
        supported_provider_models = _string_list_value(model_value, keys=("id", "name", "model", "provider_model", "providerModel", "value"))
        supported_operations.extend(operation for operation in _operations_from_models(model_value) if operation not in supported_operations)
        capabilities = _dict_value(_first_deep_value(item, ("capabilities",)))
        if not supported_operations:
            supported_operations = _normalize_operations(capabilities.get("operations"))
        if not supported_provider_models:
            supported_provider_models = _string_list_value(capabilities.get("models") or capabilities.get("provider_models"), keys=("id", "name", "model", "provider_model", "providerModel", "value"))
        if model_operation_hints:
            provider_config["model_operation_hints"] = {**_dict_value(provider_config.get("model_operation_hints")), **model_operation_hints}
        quota_buckets = _quota_buckets_value(item, request)

        credential_ref = str(_first_deep_value(item, CREDENTIAL_REF_KEYS) or "").strip()
        credential_value = ""
        raw_credential_field = ""
        if credential_ref and not _is_safe_ref(credential_ref):
            credential_value = credential_ref
            credential_ref = ""
        if not credential_ref:
            structured_credential_value = _structured_credential_value(item)
            api_key_value = _first_deep_value(item, ("api_key", "apiKey")) if not structured_credential_value else None
            raw_credential_field = "structured_credential" if structured_credential_value else ("api_key" if api_key_value is not None else "")
            raw_value = structured_credential_value if structured_credential_value else (api_key_value if raw_credential_field else _first_deep_value(item, RAW_CREDENTIAL_KEYS))
            if raw_value is not None and str(raw_value).strip():
                raw = json.dumps(raw_value, ensure_ascii=False, separators=(",", ":")) if isinstance(raw_value, (dict, list)) else str(raw_value).strip()
                if _is_safe_ref(raw):
                    credential_ref = raw
                else:
                    credential_value = raw
        auth_method = _normalize_auth_method(auth_method, credential_ref)
        resource_type = _infer_resource_type(provider_id, auth_method, item, request)
        resource_profile = _resource_profile(provider_id, item, request, provider_base_url=provider_base_url, resource_type=resource_type, auth_method=auth_method)
        raw_credential_kind = str(_first_deep_value(item, ("credential_kind", "credentialKind")) or "").strip()
        credential_kind = _normalize_credential_kind(raw_credential_kind, auth_method=auth_method, raw_credential_field=raw_credential_field)
        if raw_credential_field or (raw_credential_kind and raw_credential_kind != credential_kind):
            resource_profile["opensource_input_field"] = raw_credential_field or raw_credential_kind
            resource_profile["input_material_policy"] = "imported_as_agent_provider_material" if credential_kind == "agent_provider" else "imported_as_web_cookie_material"

        account_id_text = str(account_id or "").strip()
        if not credential_ref and not credential_value and auth_method == "self_hosted_endpoint" and provider_base_url:
            credential_ref = f"endpoint://providers/{provider_id}/{account_id_text or 'default'}"
            provider_config.setdefault("self_hosted_endpoint_url", provider_base_url)
        if not credential_ref and not credential_value:
            raise ValueError("CREDENTIAL_REF_OR_VALUE_REQUIRED")

        return {
            "provider_id": provider_id,
            "account_id": account_id_text or None,
            "label": str(label).strip(),
            "resource_type": resource_type,
            "resource_profile": resource_profile,
            "provider_base_url": str(provider_base_url).strip() if provider_base_url else None,
            "provider_config": provider_config,
            "auth_method": auth_method,
            "credential_value": credential_value,
            "credential_ref": credential_ref or None,
            "credential_secret_id": item.get("credential_secret_id"),
            "credential_kind": credential_kind,
            "supported_operations": [str(value) for value in (supported_operations or _normalize_operations(request.get("supported_operations")))],
            "supported_provider_models": [str(value) for value in (supported_provider_models or _string_list_value(request.get("supported_provider_models")))],
            "quota_buckets": quota_buckets,
            "concurrency_limit": _int_value(_first_deep_value(item, ("concurrency_limit", "concurrencyLimit", "concurrency", "max_concurrency", "maxConcurrency")) or request.get("concurrency_limit"), 1),
            "region": str(_first_deep_value(item, ("region",)) or request.get("region") or ""),
            "plan": str(_first_deep_value(item, ("plan", "tier")) or request.get("plan") or ""),
            "status": str(item.get("status") or request.get("status") or "active"),
            "upsert": bool(request.get("upsert", True)),
            "auto_create_mappings": bool(request.get("auto_create_mappings", True)),
            "sync_capabilities": bool(request.get("sync_capabilities", False)),
            "run_health_check": bool(request.get("run_health_check", False)),
        }
