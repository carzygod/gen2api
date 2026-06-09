from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "var" / "web-cookie-agent-smoke.db"
ASSET_DIR = ROOT / "var" / "web-cookie-agent-smoke-assets"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
if DB_PATH.exists():
    DB_PATH.unlink()
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH.as_posix()}"
os.environ["ASSET_DIR"] = ASSET_DIR.as_posix()
sys.path.insert(0, str(ROOT))

from media2api import models
from media2api.catalog import TARGET_MODEL_TABLE
from media2api.database import SessionLocal, init_db
from media2api.main import app, dumps
from media2api.provider_templates import PROVIDER_TEMPLATES
from media2api.security import hash_api_key
from media2api.services_connector_registry import ConnectorRegistryService, REFERENCE_AUTH_TYPES


HEADERS = {"Authorization": "Bearer dev-admin-key"}
LEGACY_AUTH_METHODS = [
    "subscription_url",
    "oauth_reference",
    "cli_credential_reference",
    "web_session_reference",
    "mcp_config_reference",
    "self_hosted_endpoint",
    "token_reference",
    "secret_json",
]


def assert_ok(resp):
    if resp.status_code >= 400:
        raise AssertionError(f"{resp.status_code}: {resp.text}")
    return resp.json()


def assert_legacy_auth_rejected(resp, legacy_auth_method: str, context: str) -> None:
    assert resp.status_code == 400 and "AUTH_METHOD_UNSUPPORTED" in resp.text, (context, legacy_auth_method, resp.text)
    body = resp.json()
    allowed = set(body.get("allowed_auth_methods") or [])
    assert allowed == {"cookie_secret", "agent_provider_credential"}, (context, legacy_auth_method, body)


def seed() -> None:
    init_db()
    with SessionLocal() as db:
        db.merge(models.User(id="usr_admin", email="admin@media2api.local", status="active", tier="admin", wallet_balance=100000))
        db.merge(models.ApiKey(id="key_dev_admin", user_id="usr_admin", name="dev admin", key_hash=hash_api_key("dev-admin-key"), status="active"))
        for provider_id, name in [
            ("openai_image", "OpenAI Image"),
            ("gemini", "Gemini"),
            ("midjourney", "Midjourney"),
            ("jimeng", "Jimeng"),
            ("kling", "Kling"),
            ("seedream_proxy", "Seedream Proxy"),
            ("runway", "Runway"),
            ("pollinations", "Pollinations"),
            ("openrouter_image", "OpenRouter Image"),
            ("fal_replicate", "fal / Replicate"),
            ("flux_stability", "Flux / Stability"),
        ]:
            db.merge(
                models.Provider(
                    id=provider_id,
                    name=name,
                    adapter_type="http_adapter",
                    status="active",
                    base_config_json=dumps({}),
                    notes="web cookie / agent smoke provider",
                )
            )
        db.commit()


def main() -> None:
    seed()
    client = TestClient(app)

    requirements = assert_ok(client.get("/v1/admin/platform-input-requirements?provider_id=openai_image", headers=HEADERS))
    row = requirements["data"][0]
    assert row["primary_resource_type"] == "web_cookie_provider"
    assert any(item["name"] == "cookie_header_or_cookie_jar" for item in row["user_inputs"])
    print("PASS platform input requirements: openai_image")

    all_requirements = assert_ok(client.get("/v1/admin/platform-input-requirements", headers=HEADERS))
    covered = {item["provider_id"] for item in all_requirements["data"]}
    expected = {row[0] for row in TARGET_MODEL_TABLE}
    missing = sorted(expected - covered)
    assert not missing, missing
    for item in all_requirements["data"]:
        assert item["primary_resource_type"] in {"web_cookie_provider", "agent_provider"}, item
        assert set(item["product_resource_scope"]).issubset({"web_cookie_provider", "agent_provider"}), item
        assert isinstance(item["runtime_base_url_allowed"], bool), item
        for field in item.get("user_inputs", []):
            if field.get("name") in {"connector_base_url", "runner_endpoint", "channel_base_url", "sdk_runtime_endpoint", "self_hosted_endpoint"}:
                assert field.get("required") is False and field.get("when"), field
    print(f"PASS platform input requirements coverage: {len(covered)} providers")

    conformance = assert_ok(client.get("/v1/admin/platform-input-conformance", headers=HEADERS))
    assert conformance["summary"]["providers"] == len(expected), conformance
    conformance_by_provider = {item["provider_id"]: item for item in conformance["data"]}
    runtime_input_names = {"connector_base_url", "runner_endpoint", "channel_base_url", "sdk_runtime_endpoint", "self_hosted_endpoint", "agent_runtime_endpoint"}
    missing_evidence = [
        (item["provider_id"], field.get("name"))
        for item in conformance["data"]
        for field in item.get("user_inputs", [])
        if not field.get("evidence")
    ]
    assert not missing_evidence, missing_evidence
    for item in conformance["data"]:
        for field in item.get("user_inputs", []):
            if field.get("name") in runtime_input_names:
                assert field.get("required") is False and field.get("when") and field.get("evidence"), field
    openai_inputs = {item["name"]: item for item in conformance_by_provider["openai_image"]["user_inputs"]}
    assert "codex-proxy" in openai_inputs["connector_base_url"]["evidence"], openai_inputs
    gemini_inputs = {item["name"]: item for item in conformance_by_provider["gemini"]["user_inputs"]}
    assert {"gemini_credentials", "google_application_credentials", "gemini_oauth_creds_base64", "gemini_oauth_creds_file", "gemini_project_id"}.issubset(set(gemini_inputs)), gemini_inputs
    assert gemini_inputs["gemini_credentials"]["any_of_group"] == "gemini_oauth_material", gemini_inputs
    assert "GEMINI_CREDENTIALS" in gemini_inputs["gemini_credentials"]["label"], gemini_inputs
    assert "GOOGLE_APPLICATION_CREDENTIALS" in gemini_inputs["google_application_credentials"]["label"], gemini_inputs
    qwen_inputs = {item["name"]: item for item in conformance_by_provider["qwen"]["user_inputs"]}
    assert {"qwen_oauth_creds_file", "qwen_oauth_cache_path", "qwen_oauth_credentials"}.issubset(set(qwen_inputs)), qwen_inputs
    assert qwen_inputs["qwen_oauth_creds_file"]["any_of_group"] == "qwen_oauth_material", qwen_inputs
    assert "~/.qwen/oauth_creds.json" in qwen_inputs["qwen_oauth_cache_path"]["label"], qwen_inputs
    jimeng_inputs = {item["name"]: item for item in conformance_by_provider["jimeng"]["user_inputs"]}
    assert jimeng_inputs["api_key"]["require_named_field"] is True and "apiKey" in jimeng_inputs["api_key"]["label"], jimeng_inputs
    seedream_inputs = {item["name"]: item for item in conformance_by_provider["seedream_proxy"]["user_inputs"]}
    assert seedream_inputs["api_key"]["require_named_field"] is True and "api_key" in seedream_inputs["api_key"]["label"], seedream_inputs
    luma_inputs = {item["name"]: item for item in conformance_by_provider["luma"]["user_inputs"]}
    assert luma_inputs["luma_api_key"]["require_named_field"] is True and "LUMA_API_KEY" in luma_inputs["luma_api_key"]["label"], luma_inputs
    runway_inputs = {item["name"]: item for item in conformance_by_provider["runway"]["user_inputs"]}
    assert {"useapi_api_key", "runway_email", "runway_password"}.issubset(set(runway_inputs)), runway_inputs
    assert runway_inputs["useapi_api_key"]["require_named_field"] is True and "apiKey" in runway_inputs["useapi_api_key"]["label"], runway_inputs
    pollinations_inputs = {item["name"]: item for item in conformance_by_provider["pollinations"]["user_inputs"]}
    assert pollinations_inputs["pollinations_key"]["require_named_field"] is True and "POLLINATIONS_KEY" in pollinations_inputs["pollinations_key"]["label"], pollinations_inputs
    openrouter_inputs = {item["name"]: item for item in conformance_by_provider["openrouter_image"]["user_inputs"]}
    assert {"openrouter_api_key", "openrouter_api_key_n", "anthropic_auth_token", "anthropic_api_key"}.issubset(set(openrouter_inputs)), openrouter_inputs
    assert openrouter_inputs["openrouter_api_key"]["any_of_group"] == "openrouter_key_material", openrouter_inputs
    fal_inputs = {item["name"]: item for item in conformance_by_provider["fal_replicate"]["user_inputs"]}
    assert {"fal_key", "replicate_api_token"}.issubset(set(fal_inputs)), fal_inputs
    assert fal_inputs["fal_key"]["any_of_group"] == "fal_replicate_key_material", fal_inputs
    flux_inputs = {item["name"]: item for item in conformance_by_provider["flux_stability"]["user_inputs"]}
    assert {"comfyui_workflow_api_json", "model_config_json", "meigen_mcp_config"}.issubset(set(flux_inputs)), flux_inputs
    assert flux_inputs["comfyui_workflow_api_json"]["any_of_group"] == "flux_stability_runner_material", flux_inputs
    fixture_root = ROOT / "var" / "auth-normalization-fixture"
    fixture_repo = fixture_root / "example__oauth-subscription-api-key"
    if fixture_root.exists():
        shutil.rmtree(fixture_root)
    fixture_repo.mkdir(parents=True)
    (fixture_repo / "README.md").write_text(
        "Example connector with OAuth device login, subscription_url import, API key, bearer token, and browser cookie support.",
        encoding="utf-8",
    )
    classified = ConnectorRegistryService(ROOT).classify_repo(fixture_repo)
    assert set(classified["auth_types"]).issubset(set(REFERENCE_AUTH_TYPES)), classified
    assert "aggregator_api_key" not in classified["auth_types"] and "oauth_reference" not in classified["auth_types"], classified
    raw_hints = classified["evidence"]["classification"]["raw_auth_hints"]
    assert {"aggregator_api_key", "oauth_reference", "subscription_url"}.issubset(set(raw_hints)), classified
    assert conformance_by_provider["gemini"]["runtime_base_url_allowed"] is True
    assert "agent_runtime_endpoint" in conformance_by_provider["gemini"]["runtime_base_url_input_fields"]
    assert conformance_by_provider["midjourney"]["runtime_base_url_allowed"] is False
    assert conformance_by_provider["midjourney"]["accepted_auth_methods"] == ["cookie_secret"]
    assert {"discord_session_or_user_token", "discord_bot_token"}.issubset(set(conformance_by_provider["midjourney"]["credential_input_fields"]))
    assert {"guild_id", "channel_id", "discord_server", "discord_cdn", "discord_wss", "discord_user_agent"}.issubset(set(conformance_by_provider["midjourney"]["dynamic_profile_fields"]))
    assert not conformance_by_provider["midjourney"]["runtime_base_url_input_fields"]
    midjourney_inputs = {item["name"]: item for item in conformance_by_provider["midjourney"]["user_inputs"]}
    assert "PlexPt__midjourney-proxy" in midjourney_inputs["guild_id"]["evidence"], midjourney_inputs
    assert not ({"provider_base_url", "base_url", "connector_base_url"} & set(midjourney_inputs)), midjourney_inputs
    for provider_id in ["jimeng", "kling", "seedream_proxy", "runway"]:
        row = conformance_by_provider[provider_id]
        assert row["primary_resource_type"] == "agent_provider", row
        assert row["accepted_auth_methods"] == ["agent_provider_credential"], row
        assert row["runtime_base_url_allowed"] is False, row
        assert not row["runtime_base_url_input_fields"], row
    kling_inputs = {item["name"]: item for item in conformance_by_provider["kling"]["user_inputs"]}
    assert {"kling_access_key", "kling_secret_key", "mcp_agent_config_ref"}.issubset(set(kling_inputs)), kling_inputs
    assert "KLING_ACCESS_KEY" in kling_inputs["kling_access_key"]["label"], kling_inputs
    assert "KLING_SECRET_KEY" in kling_inputs["kling_secret_key"]["label"], kling_inputs
    runtime_blocked_providers = [
        provider_id
        for provider_id, row in conformance_by_provider.items()
        if row["runtime_base_url_allowed"] is False
    ]
    for provider_id in runtime_blocked_providers:
        row = conformance_by_provider[provider_id]
        rejected_runtime_plan = client.post(
            "/v1/admin/account-onboarding/plan",
            headers=HEADERS,
            json={
                "provider_id": provider_id,
                "auth_method": row["accepted_auth_methods"][0],
                "resource_type": row["primary_resource_type"],
                "provider_base_url": "http://127.0.0.1:18091",
            },
        )
        assert rejected_runtime_plan.status_code == 400 and "PROVIDER_BASE_URL_NOT_ALLOWED" in rejected_runtime_plan.text, (provider_id, rejected_runtime_plan.text)
    with SessionLocal() as db:
        db.add(
            models.AccountSubscriptionSource(
                id="subsrc_legacy_auth_method",
                provider_id="gemini",
                name="legacy auth method source",
                auth_method="subscription_url",
                subscription_url="",
                content_json='{"accounts":[]}',
            )
        )
        db.add(
            models.AccountSubscriptionSource(
                id="subsrc_default_auth_method",
                provider_id="gemini",
                name="default auth method source",
                subscription_url="",
                content_json='{"accounts":[]}',
            )
        )
        db.commit()
    init_db()
    with SessionLocal() as db:
        legacy_source = db.get(models.AccountSubscriptionSource, "subsrc_legacy_auth_method")
        default_source = db.get(models.AccountSubscriptionSource, "subsrc_default_auth_method")
        assert legacy_source and legacy_source.auth_method == "agent_provider_credential", legacy_source.auth_method if legacy_source else None
        assert default_source and default_source.auth_method == "agent_provider_credential", default_source.auth_method if default_source else None
    print("PASS platform input conformance: runtime/base_url and profile fields")

    gemini_guide = assert_ok(client.get("/v1/admin/account-guides/gemini", headers=HEADERS))
    assert gemini_guide["runtime_base_url_allowed"] is True
    assert "agent_runtime_endpoint" in gemini_guide["runtime_base_url_input_fields"]
    midjourney_guide = assert_ok(client.get("/v1/admin/account-guides/midjourney", headers=HEADERS))
    assert midjourney_guide["runtime_base_url_allowed"] is False
    assert "provider_base_url" not in midjourney_guide["payload_template"], midjourney_guide["payload_template"]
    assert "provider_base_url" not in midjourney_guide["curl"], midjourney_guide["curl"]
    assert "proxy 地址" not in json.dumps(midjourney_guide, ensure_ascii=False), midjourney_guide
    assert "PlexPt__midjourney-proxy" in json.dumps(midjourney_guide["input_requirements"], ensure_ascii=False), midjourney_guide
    for provider_id in ["jimeng", "kling", "seedream_proxy", "runway"]:
        guide = assert_ok(client.get(f"/v1/admin/account-guides/{provider_id}", headers=HEADERS))
        assert guide["recommended_auth_methods"] == ["agent_provider_credential"], guide
        assert guide["payload_template"]["resource_type"] == "agent_provider", guide["payload_template"]
        assert guide["credential_ref_example"].startswith("agent://"), guide
        assert "provider_base_url" not in guide["payload_template"], guide["payload_template"]
        assert "provider_base_url" not in guide["curl"], guide["curl"]
    login_response = client.post("/admin/login", data={"username": "admin", "password": "dev-admin-key"}, follow_redirects=False)
    assert login_response.status_code in {302, 303}, login_response.text
    admin_html = client.get("/admin").text
    assert "证据：" in admin_html, admin_html
    assert "proxy 地址仅在使用外部 proxy 时填写" not in admin_html, admin_html
    assert "syncResourceEntryPanels" in admin_html, admin_html[:500]
    assert "cookie-provider-fields" in admin_html, admin_html
    assert "agent-provider-fields" in admin_html, admin_html
    assert "renderProviderProfileFields(providerId, 'cookie-provider-fields')" in admin_html, admin_html
    assert "renderProviderProfileFields(providerId, 'agent-provider-fields')" in admin_html, admin_html
    assert "collectProviderProfileFields(providerId, 'cookie-provider-fields')" in admin_html, admin_html
    assert "collectProviderProfileFields(providerId, 'agent-provider-fields')" in admin_html, admin_html
    assert "!item.auth_method && !item.store_as" in admin_html, admin_html
    assert "providerCredentialRequirements" in admin_html, admin_html
    assert "syncCredentialInputHints" in admin_html, admin_html
    assert "subscriptionImportRequirementExample" in admin_html, admin_html
    assert "syncBulkImportHint" in admin_html, admin_html
    assert "Credential fields: " in admin_html and "resource_profile fields: " in admin_html, admin_html
    assert "resource_profile: resourceProfile" in admin_html, admin_html
    assert "provider_config: {}" in admin_html, admin_html
    assert set(REFERENCE_AUTH_TYPES) == {"cookie_secret", "agent_provider_credential"}, REFERENCE_AUTH_TYPES
    for legacy_auth in [
        "subscription_url",
        "oauth_reference",
        "cli_credential_reference",
        "web_session_reference",
        "mcp_config_reference",
        "self_hosted_endpoint",
        "aggregator_api_key",
        "token_reference",
        "secret_json",
    ]:
        assert f'<option value="{legacy_auth}"' not in admin_html, legacy_auth
        assert f"{legacy_auth}: '" not in admin_html, legacy_auth
    assert "document.getElementById('bulk-auth-method')?.addEventListener('change', syncBulkImportHint)" in admin_html, admin_html
    assert "cookie-secret-label" in admin_html and "agent-secret-label" in admin_html and "wizard-credential-label" in admin_html, admin_html
    assert "cookie-secret-hint" in admin_html and "agent-secret-hint" in admin_html and "wizard-credential-hint" in admin_html, admin_html
    assert "Discord/Midjourney session 或 user token" in admin_html, admin_html
    assert "GEMINI_CREDENTIALS JSON" in admin_html and "GOOGLE_APPLICATION_CREDENTIALS file/ref" in admin_html, admin_html
    for runtime_input_id in [
        "cookie-runner-url",
        "agent-runtime-endpoint",
        "oauth-base-url",
        "wizard-base-url",
        "bulk-base-url",
        "connector-base-url",
    ]:
        marker = f'id="{runtime_input_id}"'
        pos = admin_html.index(marker)
        assert 'class="field-hidden"' in admin_html[max(0, pos - 180) : pos], runtime_input_id
    assert "agent://providers/kling/acct_01" in admin_html, admin_html
    assert "agent://providers/jimeng/acct_01" in admin_html, admin_html
    assert "agent://providers/runway/acct_01" in admin_html, admin_html
    assert "agent://providers/seedream_proxy/acct_01" in admin_html, admin_html
    for stale in [
        "secret://providers/kling/session_01",
        "secret://providers/jimeng/session_01",
        "secret://providers/runway/session_01",
        "secret://providers/seedream_proxy/session_01",
        "Dreamina/Jimeng Web cookie/session",
        "Runway Web cookie/session",
        "Seedream/Dreamina Web cookie/session",
    ]:
        assert stale not in admin_html, stale
    legacy_admin_html = client.get("/admin-legacy?admin_key=dev-admin-key").text
    assert "templateRuntimeBaseUrlAllowed" in legacy_admin_html, legacy_admin_html[:500]
    assert "template-base-url-row" in legacy_admin_html, legacy_admin_html[:500]
    assert '<div id="template-base-url-row" class="field-hidden">' in legacy_admin_html, legacy_admin_html[:500]
    assert "base_url: templateBaseUrlValue()" in legacy_admin_html, legacy_admin_html[:500]
    assert '"midjourney": false' in legacy_admin_html, legacy_admin_html[:500]
    external_acceptance_script = (ROOT / "scripts" / "external_provider_acceptance.py").read_text(encoding="utf-8")
    assert 'parser.add_argument("--credential-kind", default="agent_provider")' in external_acceptance_script
    assert 'parser.add_argument("--credential-kind", default="api_key")' not in external_acceptance_script
    rejected_plan = client.post(
        "/v1/admin/account-onboarding/plan",
        headers=HEADERS,
        json={"provider_id": "midjourney", "provider_base_url": "http://127.0.0.1:18091"},
    )
    assert rejected_plan.status_code == 400 and "PROVIDER_BASE_URL_NOT_ALLOWED" in rejected_plan.text, rejected_plan.text
    rejected_jimeng_cookie_plan = client.post(
        "/v1/admin/account-onboarding/plan",
        headers=HEADERS,
        json={"provider_id": "jimeng", "auth_method": "cookie_secret"},
    )
    assert rejected_jimeng_cookie_plan.status_code == 400 and "PROVIDER_AUTH_METHOD_NOT_ALLOWED" in rejected_jimeng_cookie_plan.text, rejected_jimeng_cookie_plan.text
    for legacy_auth_method in LEGACY_AUTH_METHODS:
        rejected_legacy_auth_plan = client.post(
            "/v1/admin/account-onboarding/plan",
            headers=HEADERS,
            json={"provider_id": "gemini", "auth_method": legacy_auth_method},
        )
        assert_legacy_auth_rejected(rejected_legacy_auth_plan, legacy_auth_method, "account-onboarding plan")
        for path, payload, context in [
            (
                "/v1/admin/account-setup-workflows/gemini/run",
                {"step": "plan", "auth_method": legacy_auth_method, "include_preflight": False, "dry_run": True},
                "account setup workflow",
            ),
            (
                "/v1/admin/account-setup-quickstart",
                {"provider_id": "gemini", "auth_method": legacy_auth_method, "dry_run": True, "apply_manifest": False, "run_preflight": False},
                "account setup quickstart",
            ),
            (
                "/v1/admin/authorized-resource-sessions",
                {"provider_id": "gemini", "auth_method": legacy_auth_method, "dry_run": True},
                "authorized resource session",
            ),
            (
                "/v1/admin/account-onboarding",
                {
                    "provider_id": "gemini",
                    "label": "Gemini Legacy Auth Rejection",
                    "auth_method": legacy_auth_method,
                    "supported_operations": ["text_to_image"],
                    "supported_provider_models": ["nano-banana-pro"],
                    "sync_capabilities": False,
                    "run_health_check": False,
                },
                "account onboarding",
            ),
        ]:
            rejected_legacy_auth = client.post(path, headers=HEADERS, json=payload)
            assert_legacy_auth_rejected(rejected_legacy_auth, legacy_auth_method, context)
    rejected_runway_resource_plan = client.post(
        "/v1/admin/account-onboarding/plan",
        headers=HEADERS,
        json={"provider_id": "runway", "auth_method": "agent_provider_credential", "resource_type": "web_cookie_provider"},
    )
    assert rejected_runway_resource_plan.status_code == 400 and "PROVIDER_RESOURCE_TYPE_NOT_ALLOWED" in rejected_runway_resource_plan.text, rejected_runway_resource_plan.text
    print("PASS account guide and plan base_url guard")

    templates = assert_ok(client.get("/v1/provider-templates", headers=HEADERS))
    template_by_provider = {item["id"]: item for item in templates["data"]}
    placeholder_base_urls = []
    for template_id, template in PROVIDER_TEMPLATES.items():
        value = str((template.default_config or {}).get("base_url") or "")
        if value.startswith(("http://127.0.0.1", "http://localhost", "http://0.0.0.0")) or "connector.example.com" in value:
            placeholder_base_urls.append((template_id, value))
    assert not placeholder_base_urls, placeholder_base_urls
    assert template_by_provider["gemini"]["runtime_base_url_allowed"] is True
    assert "base_url" not in template_by_provider["gemini"]["default_config"], template_by_provider["gemini"]
    assert template_by_provider["midjourney"]["runtime_base_url_allowed"] is False
    assert "base_url" not in template_by_provider["midjourney"]["default_config"], template_by_provider["midjourney"]

    gemini_manifest_template = assert_ok(client.get("/v1/admin/external-connector-manifest-template?provider_id=gemini", headers=HEADERS))
    assert "base_url" not in gemini_manifest_template["default_manifest"], gemini_manifest_template["default_manifest"]
    gemini_template_commands = json.dumps(gemini_manifest_template["commands"], ensure_ascii=False)
    assert "connector.example.com" not in gemini_template_commands, gemini_template_commands
    gemini_activate_without_base_url = assert_ok(
        client.post(
            "/v1/admin/provider-templates/gemini/activate",
            headers=HEADERS,
            json={
                "credential_ref": "agent://providers/gemini/acct_template_plan",
                "credential_kind": "agent_provider",
                "dry_run": True,
                "run_health_check": False,
                "run_contract_tests": False,
            },
        )
    )
    assert "base_url" not in gemini_activate_without_base_url["plan"], gemini_activate_without_base_url
    gemini_manifest_without_base_url = assert_ok(
        client.post(
            "/v1/admin/external-connector-manifest",
            headers=HEADERS,
            json={
                "provider_id": "gemini",
                "credential_ref": "agent://providers/gemini/acct_manifest_plan",
                "credential_kind": "agent_provider",
                "dry_run": True,
                "run_health_check": False,
                "run_contract_tests": False,
                "include_preflight": False,
            },
        )
    )
    assert "base_url" not in gemini_manifest_without_base_url["manifest"], gemini_manifest_without_base_url
    gemini_install_without_base_url = assert_ok(
        client.post(
            "/v1/admin/provider-templates/gemini/install",
            headers=HEADERS,
            json={
                "credential_ref": "agent://providers/gemini/acct_template_install",
                "credential_kind": "agent_provider",
                "resource_type": "agent_provider",
                "status": "active",
                "account_id": "acct_gemini_template_install",
                "overwrite_config": True,
            },
        )
    )
    assert "base_url" not in gemini_install_without_base_url["provider"]["base_config"], gemini_install_without_base_url
    gemini_session_without_base_url = assert_ok(
        client.post(
            "/v1/admin/authorized-resource-sessions",
            headers=HEADERS,
            json={
                "provider_id": "gemini",
                "auth_method": "agent_provider_credential",
                "resource_type": "agent_provider",
                "dry_run": False,
            },
        )
    )
    assert gemini_session_without_base_url["status"] == "planned", gemini_session_without_base_url
    assert gemini_session_without_base_url["connector_base_url"] == "", gemini_session_without_base_url

    midjourney_manifest_template = assert_ok(client.get("/v1/admin/external-connector-manifest-template?provider_id=midjourney", headers=HEADERS))
    assert "base_url" not in midjourney_manifest_template["default_manifest"], midjourney_manifest_template["default_manifest"]
    assert midjourney_manifest_template["default_resource_type"] == "web_cookie_provider", midjourney_manifest_template
    assert midjourney_manifest_template["default_auth_method"] == "cookie_secret", midjourney_manifest_template
    assert midjourney_manifest_template["default_manifest"]["credential_ref"].startswith("secret://"), midjourney_manifest_template["default_manifest"]
    assert midjourney_manifest_template["default_manifest"]["resource_profile"]["guild_id"] == "<required>", midjourney_manifest_template["default_manifest"]
    assert midjourney_manifest_template["resource_profile_template"]["channel_id"] == "<required>", midjourney_manifest_template
    rejected_placeholder_manifest = client.post(
        "/v1/admin/external-connector-manifest",
        headers=HEADERS,
        json=midjourney_manifest_template["default_manifest"],
    )
    assert rejected_placeholder_manifest.status_code == 400 and "PROVIDER_REQUIRED_INPUT_MISSING" in rejected_placeholder_manifest.text, rejected_placeholder_manifest.text
    rejected_template_activate = client.post(
        "/v1/admin/provider-templates/midjourney/activate",
        headers=HEADERS,
        json={
            "base_url": "http://127.0.0.1:18098",
            "credential_ref": "secret://providers/midjourney/discord_session_01",
            "dry_run": True,
            "run_health_check": False,
            "run_contract_tests": False,
        },
    )
    assert rejected_template_activate.status_code == 400 and "PROVIDER_BASE_URL_NOT_ALLOWED" in rejected_template_activate.text, rejected_template_activate.text
    rejected_template_agent = client.post(
        "/v1/admin/provider-templates/midjourney/activate",
        headers=HEADERS,
        json={
            "credential_ref": "agent://providers/midjourney/bad_template",
            "credential_kind": "agent_provider",
            "dry_run": True,
            "run_health_check": False,
            "run_contract_tests": False,
        },
    )
    assert rejected_template_agent.status_code == 400 and "PROVIDER_RESOURCE_TYPE_NOT_ALLOWED" in rejected_template_agent.text, rejected_template_agent.text

    rejected_manifest = client.post(
        "/v1/admin/external-connector-manifest",
        headers=HEADERS,
        json={
            "provider_id": "midjourney",
            "base_url": "http://127.0.0.1:18098",
            "credential_ref": "secret://providers/midjourney/discord_session_01",
            "dry_run": True,
            "run_health_check": False,
            "run_contract_tests": False,
            "operations": ["text_to_image"],
        },
    )
    assert rejected_manifest.status_code == 400 and "PROVIDER_BASE_URL_NOT_ALLOWED" in rejected_manifest.text, rejected_manifest.text

    rejected_acceptance = client.post(
        "/v1/admin/provider-templates/midjourney/external-acceptance",
        headers=HEADERS,
        json={
            "base_url": "http://127.0.0.1:18098",
            "credential_ref": "secret://providers/midjourney/discord_session_01",
            "dry_run": True,
            "run_health_check": False,
            "run_contract_tests": False,
            "operations": ["text_to_image"],
        },
    )
    assert rejected_acceptance.status_code == 400 and "PROVIDER_BASE_URL_NOT_ALLOWED" in rejected_acceptance.text, rejected_acceptance.text

    midjourney_preflight = assert_ok(client.get("/v1/admin/external-connector-preflight?provider_id=midjourney", headers=HEADERS))
    midjourney_commands = json.dumps(midjourney_preflight["providers"][0]["commands"], ensure_ascii=False)
    assert "base_url" not in midjourney_commands and "connector.example.com" not in midjourney_commands, midjourney_commands
    go_live = assert_ok(client.get("/v1/admin/production-go-live-plan", headers=HEADERS))
    go_live_commands = json.dumps(
        [item.get("commands", {}) for item in go_live.get("all_candidates", [])],
        ensure_ascii=False,
    )
    assert "connector.example.com" not in go_live_commands and "<connector-base-url>" not in go_live_commands, go_live_commands

    rejected_provider_create = client.post(
        "/v1/admin/providers",
        headers=HEADERS,
        json={"id": "luma", "name": "Luma", "base_config": {"base_url": "http://127.0.0.1:18095"}},
    )
    assert rejected_provider_create.status_code == 400 and "PROVIDER_BASE_URL_NOT_ALLOWED" in rejected_provider_create.text, rejected_provider_create.text

    rejected_provider_patch = client.patch(
        "/v1/admin/providers/midjourney",
        headers=HEADERS,
        json={"base_config": {"base_url": "http://127.0.0.1:18098", "health_endpoint": "/health"}},
    )
    assert rejected_provider_patch.status_code == 400 and "PROVIDER_BASE_URL_NOT_ALLOWED" in rejected_provider_patch.text, rejected_provider_patch.text

    import_result = assert_ok(
        client.post(
            "/v1/admin/config-import",
            headers=HEADERS,
            json={
                "dry_run": True,
                "snapshot": {
                    "object": "media2api.config_snapshot",
                    "providers": [
                        {
                            "id": "midjourney",
                            "name": "Midjourney Imported",
                            "base_config": {"base_url": "http://127.0.0.1:18098"},
                        }
                    ],
                },
            },
        )
    )
    assert "PROVIDER_BASE_URL_NOT_ALLOWED" in json.dumps(import_result, ensure_ascii=False), import_result
    bad_account_import = assert_ok(
        client.post(
            "/v1/admin/config-import",
            headers=HEADERS,
            json={
                "dry_run": True,
                "snapshot": {
                    "object": "media2api.config_snapshot",
                    "accounts": [
                        {
                            "id": "acct_openai_bad_agent_ref_import",
                            "provider_id": "openai_image",
                            "label": "OpenAI Bad Agent Ref Import",
                            "resource_type": "web_cookie_provider",
                            "credential_ref": "agent://providers/openai_image/bad_import",
                            "supported_operations": ["text_to_image"],
                            "supported_provider_models": ["gpt-image-2"],
                        }
                    ],
                },
            },
        )
    )
    assert "ACCOUNT_CREDENTIAL_REF_RESOURCE_MISMATCH" in json.dumps(bad_account_import, ensure_ascii=False), bad_account_import

    with SessionLocal() as db:
        provider = db.get(models.Provider, "midjourney")
        assert provider is not None
        provider.base_config_json = dumps({"base_url": "http://legacy-runner.invalid", "health_endpoint": "/health"})
        db.commit()
    providers = assert_ok(client.get("/v1/providers", headers=HEADERS))
    midjourney_provider = next(item for item in providers["data"] if item["id"] == "midjourney")
    assert "base_url" not in midjourney_provider["base_config"], midjourney_provider
    runtime = assert_ok(client.get("/v1/admin/providers/midjourney/connector-runtime", headers=HEADERS))
    assert runtime["summary"]["base_url_configured"] is False, runtime
    assert runtime["runtime_contract"]["base_url"] == "", runtime
    sync_result = client.post(
        "/v1/admin/providers/midjourney/sync-capabilities",
        headers=HEADERS,
        json={"endpoint": "capabilities"},
    )
    assert sync_result.status_code == 400 and "No runner base_url" in sync_result.text, sync_result.text
    print("PASS provider template and manifest base_url guard: midjourney")

    with SessionLocal() as db:
        db.merge(
            models.Provider(
                id="luma",
                name="Luma",
                adapter_type="http_adapter",
                status="active",
                base_config_json=dumps({}),
                notes="web cookie / agent smoke provider",
            )
        )
        db.commit()

    rejected_luma_raw_key = client.post(
        "/v1/admin/account-onboarding",
        headers=HEADERS,
        json={
            "provider_id": "luma",
            "account_id": "acct_luma_raw_key",
            "label": "Luma Raw Key",
            "resource_type": "agent_provider",
            "auth_method": "agent_provider_credential",
            "credential_kind": "agent_provider",
            "credential_value": "raw-luma-key",
            "run_health_check": False,
        },
    )
    assert rejected_luma_raw_key.status_code == 400 and "luma_api_key" in rejected_luma_raw_key.text, rejected_luma_raw_key.text
    luma_named_key = assert_ok(
        client.post(
            "/v1/admin/account-onboarding",
            headers=HEADERS,
            json={
                "provider_id": "luma",
                "account_id": "acct_luma_named_key",
                "label": "Luma Named Key",
                "resource_type": "agent_provider",
                "auth_method": "agent_provider_credential",
                "credential_kind": "agent_provider",
                "credential_value": '{"LUMA_API_KEY":"luma-smoke"}',
                "run_health_check": False,
            },
        )
    )
    assert luma_named_key["account"]["credential_ref"].startswith("secret://"), luma_named_key
    rejected_luma_raw_secret = client.post(
        "/v1/admin/credential-secrets",
        headers=HEADERS,
        json={
            "id": "secret_luma_raw_key_guard",
            "name": "Luma Raw Key Guard",
            "value": "raw-luma-secret-ref",
            "kind": "agent_provider",
            "provider_id": "luma",
        },
    )
    assert rejected_luma_raw_secret.status_code == 400 and "luma_api_key" in rejected_luma_raw_secret.text, rejected_luma_raw_secret.text
    luma_secret = assert_ok(
        client.post(
            "/v1/admin/credential-secrets",
            headers=HEADERS,
            json={
                "id": "secret_luma_named_key_guard",
                "name": "Luma Named Key Guard",
                "value": '{"LUMA_API_KEY":"luma-secret-ref"}',
                "kind": "agent_provider",
                "provider_id": "luma",
            },
        )
    )
    luma_secret_account = assert_ok(
        client.post(
            "/v1/admin/account-onboarding",
            headers=HEADERS,
            json={
                "provider_id": "luma",
                "account_id": "acct_luma_secret_ref",
                "label": "Luma Secret Ref",
                "resource_type": "agent_provider",
                "auth_method": "agent_provider_credential",
                "credential_kind": "agent_provider",
                "credential_ref": luma_secret["ref"],
                "supported_operations": ["text_to_video"],
                "supported_provider_models": ["luma-dream-machine"],
                "sync_capabilities": False,
                "run_health_check": False,
            },
        )
    )
    assert luma_secret_account["account"]["credential_ref"] == luma_secret["ref"], luma_secret_account
    assert luma_secret_account["secret"] is None, luma_secret_account
    rejected_luma_plain_ref = client.post(
        "/v1/admin/account-onboarding",
        headers=HEADERS,
        json={
            "provider_id": "luma",
            "account_id": "acct_luma_plain_ref",
            "label": "Luma Plain Ref",
            "resource_type": "agent_provider",
            "auth_method": "agent_provider_credential",
            "credential_kind": "agent_provider",
            "credential_ref": "plain://raw-luma-inline",
            "supported_operations": ["text_to_video"],
            "supported_provider_models": ["luma-dream-machine"],
            "sync_capabilities": False,
            "run_health_check": False,
        },
    )
    assert rejected_luma_plain_ref.status_code == 400 and "luma_api_key" in rejected_luma_plain_ref.text, rejected_luma_plain_ref.text
    luma_bulk_ref = assert_ok(
        client.post(
            "/v1/admin/account-onboarding/bulk",
            headers=HEADERS,
            json={
                "provider_id": "luma",
                "auth_method": "agent_provider_credential",
                "items": [
                    {
                        "account_id": "acct_luma_bulk_secret_ref",
                        "label": "Luma Bulk Secret Ref",
                        "resource_type": "agent_provider",
                        "credential_kind": "agent_provider",
                        "credential_ref": luma_secret["ref"],
                        "supported_operations": ["text_to_video"],
                        "supported_provider_models": ["luma-dream-machine"],
                    }
                ],
            },
        )
    )
    assert luma_bulk_ref["created_or_updated"] == 1 and not luma_bulk_ref["errors"], luma_bulk_ref
    assert luma_bulk_ref["data"][0]["account"]["credential_ref"] == luma_secret["ref"], luma_bulk_ref
    assert luma_bulk_ref["data"][0]["secret"] is None, luma_bulk_ref
    print("PASS named credential field guard: luma")

    rejected_kling_cookie_account = client.post(
        "/v1/admin/account-onboarding",
        headers=HEADERS,
        json={
            "provider_id": "kling",
            "account_id": "acct_kling_bad_cookie",
            "label": "Kling Bad Cookie",
            "resource_type": "web_cookie_provider",
            "auth_method": "cookie_secret",
            "credential_kind": "cookie",
            "credential_value": "kling-session=smoke",
            "supported_operations": ["text_to_video"],
            "supported_provider_models": ["kling-2.1"],
            "sync_capabilities": False,
            "run_health_check": False,
        },
    )
    assert rejected_kling_cookie_account.status_code == 400 and "PROVIDER_AUTH_METHOD_NOT_ALLOWED" in rejected_kling_cookie_account.text, rejected_kling_cookie_account.text
    rejected_kling_resource_mismatch = client.post(
        "/v1/admin/account-onboarding",
        headers=HEADERS,
        json={
            "provider_id": "kling",
            "account_id": "acct_kling_bad_resource",
            "label": "Kling Bad Resource",
            "resource_type": "web_cookie_provider",
            "auth_method": "agent_provider_credential",
            "credential_kind": "agent_provider",
            "credential_value": '{"profile":"bad"}',
            "supported_operations": ["text_to_video"],
            "supported_provider_models": ["kling-2.1"],
            "sync_capabilities": False,
            "run_health_check": False,
        },
    )
    assert rejected_kling_resource_mismatch.status_code == 400 and "PROVIDER_RESOURCE_TYPE_NOT_ALLOWED" in rejected_kling_resource_mismatch.text, rejected_kling_resource_mismatch.text
    rejected_direct_kling_web_resource = client.post(
        "/v1/admin/accounts",
        headers=HEADERS,
        json={
            "id": "acct_kling_direct_bad_resource",
            "provider_id": "kling",
            "label": "Kling Direct Bad Resource",
            "resource_type": "web_cookie_provider",
            "credential_ref": "agent://providers/kling/acct_bad",
            "credential_kind": "agent_provider",
            "supported_operations": ["text_to_video"],
            "supported_provider_models": ["kling-2.1"],
        },
    )
    assert rejected_direct_kling_web_resource.status_code == 400 and "PROVIDER_RESOURCE_TYPE_NOT_ALLOWED" in rejected_direct_kling_web_resource.text, rejected_direct_kling_web_resource.text
    rejected_kling_workflow_cookie = client.post(
        "/v1/admin/account-setup-workflows/kling/run",
        headers=HEADERS,
        json={"step": "plan", "auth_method": "cookie_secret", "include_preflight": False, "dry_run": True},
    )
    assert rejected_kling_workflow_cookie.status_code == 400 and "PROVIDER_AUTH_METHOD_NOT_ALLOWED" in rejected_kling_workflow_cookie.text, rejected_kling_workflow_cookie.text
    rejected_runway_quickstart_cookie = client.post(
        "/v1/admin/account-setup-quickstart",
        headers=HEADERS,
        json={"provider_id": "runway", "auth_method": "cookie_secret", "dry_run": True, "apply_manifest": False},
    )
    assert rejected_runway_quickstart_cookie.status_code == 400 and "PROVIDER_AUTH_METHOD_NOT_ALLOWED" in rejected_runway_quickstart_cookie.text, rejected_runway_quickstart_cookie.text
    rejected_runway_cookie_session = client.post(
        "/v1/admin/authorized-resource-sessions",
        headers=HEADERS,
        json={"provider_id": "runway", "auth_method": "cookie_secret"},
    )
    assert rejected_runway_cookie_session.status_code == 400 and "PROVIDER_AUTH_METHOD_NOT_ALLOWED" in rejected_runway_cookie_session.text, rejected_runway_cookie_session.text
    rejected_kling_missing_secret = client.post(
        "/v1/admin/account-onboarding",
        headers=HEADERS,
        json={
            "provider_id": "kling",
            "account_id": "acct_kling_missing_secret_key",
            "label": "Kling Missing Secret Key",
            "resource_type": "agent_provider",
            "auth_method": "agent_provider_credential",
            "credential_value": '{"KLING_ACCESS_KEY":"ak_smoke"}',
            "supported_operations": ["text_to_video"],
            "supported_provider_models": ["kling-2.1"],
            "sync_capabilities": False,
            "run_health_check": False,
        },
    )
    assert rejected_kling_missing_secret.status_code == 400 and "kling_secret_key" in rejected_kling_missing_secret.text, rejected_kling_missing_secret.text
    kling_direct_keys = assert_ok(
        client.post(
            "/v1/admin/account-onboarding",
            headers=HEADERS,
            json={
                "provider_id": "kling",
                "account_id": "acct_kling_direct_keys",
                "label": "Kling Direct Keys",
                "resource_type": "agent_provider",
                "auth_method": "agent_provider_credential",
                "credential_value": '{"KLING_ACCESS_KEY":"ak_smoke","KLING_SECRET_KEY":"sk_smoke"}',
                "supported_operations": ["text_to_video"],
                "supported_provider_models": ["kling-2.1"],
                "sync_capabilities": False,
                "run_health_check": False,
            },
        )
    )
    assert kling_direct_keys["account"]["resource_type"] == "agent_provider", kling_direct_keys
    assert kling_direct_keys["secret"]["kind"] == "agent_provider", kling_direct_keys
    print("PASS provider auth method guard: agent-only platforms")

    rejected_midjourney_missing_fields = client.post(
        "/v1/admin/account-onboarding",
        headers=HEADERS,
        json={
            "provider_id": "midjourney",
            "account_id": "acct_midjourney_missing_required",
            "label": "Midjourney Missing Required",
            "resource_type": "web_cookie_provider",
            "auth_method": "cookie_secret",
            "credential_kind": "cookie",
            "credential_value": "discord-session=missing-fields",
            "supported_operations": ["text_to_image"],
            "supported_provider_models": ["mj-v7"],
            "sync_capabilities": False,
            "run_health_check": False,
        },
    )
    assert rejected_midjourney_missing_fields.status_code == 400 and "PROVIDER_REQUIRED_INPUT_MISSING" in rejected_midjourney_missing_fields.text and "guild_id" in rejected_midjourney_missing_fields.text and "channel_id" in rejected_midjourney_missing_fields.text, rejected_midjourney_missing_fields.text
    rejected_direct_midjourney_missing_fields = client.post(
        "/v1/admin/accounts",
        headers=HEADERS,
        json={
            "id": "acct_midjourney_direct_missing_required",
            "provider_id": "midjourney",
            "label": "Midjourney Direct Missing Required",
            "resource_type": "web_cookie_provider",
            "credential_ref": "secret://providers/midjourney/session_missing_required",
            "credential_kind": "cookie",
            "supported_operations": ["text_to_image"],
            "supported_provider_models": ["mj-v7"],
        },
    )
    assert rejected_direct_midjourney_missing_fields.status_code == 400 and "PROVIDER_REQUIRED_INPUT_MISSING" in rejected_direct_midjourney_missing_fields.text, rejected_direct_midjourney_missing_fields.text
    rejected_import_midjourney_missing_fields = client.post(
        "/v1/admin/account-subscriptions/preview",
        headers=HEADERS,
        json={
            "provider_id": "midjourney",
            "auth_method": "cookie_secret",
            "content": '{"accounts":[{"account_id":"acct_midjourney_import_missing_required","label":"Missing","credential_ref":"secret://providers/midjourney/session_missing_required","resource_type":"web_cookie_provider","models":[{"id":"mj-v7","operations":["text_to_image"]}]}]}',
        },
    )
    assert rejected_import_midjourney_missing_fields.status_code == 400 and "PROVIDER_REQUIRED_INPUT_MISSING" in rejected_import_midjourney_missing_fields.text, rejected_import_midjourney_missing_fields.text
    print("PASS provider required input guard: midjourney")

    rejected_cookie_agent_ref = client.post(
        "/v1/admin/account-onboarding",
        headers=HEADERS,
        json={
            "provider_id": "openai_image",
            "account_id": "acct_openai_bad_agent_ref_cookie",
            "label": "OpenAI Bad Agent Ref Cookie",
            "resource_type": "web_cookie_provider",
            "auth_method": "cookie_secret",
            "credential_ref": "agent://providers/openai_image/bad_cookie",
            "supported_operations": ["text_to_image"],
            "supported_provider_models": ["gpt-image-2"],
            "sync_capabilities": False,
            "run_health_check": False,
        },
    )
    assert rejected_cookie_agent_ref.status_code == 400 and "ACCOUNT_CREDENTIAL_REF_RESOURCE_MISMATCH" in rejected_cookie_agent_ref.text, rejected_cookie_agent_ref.text
    rejected_direct_cookie_agent_ref = client.post(
        "/v1/admin/accounts",
        headers=HEADERS,
        json={
            "id": "acct_openai_direct_bad_agent_ref_cookie",
            "provider_id": "openai_image",
            "label": "OpenAI Direct Bad Agent Ref Cookie",
            "resource_type": "web_cookie_provider",
            "credential_ref": "agent://providers/openai_image/bad_direct_cookie",
            "credential_kind": "custom",
            "supported_operations": ["text_to_image"],
            "supported_provider_models": ["gpt-image-2"],
        },
    )
    assert rejected_direct_cookie_agent_ref.status_code == 400 and "ACCOUNT_CREDENTIAL_REF_RESOURCE_MISMATCH" in rejected_direct_cookie_agent_ref.text, rejected_direct_cookie_agent_ref.text
    rejected_agent_websession_ref = client.post(
        "/v1/admin/authorized-resource-sessions",
        headers=HEADERS,
        json={"provider_id": "openai_image", "auth_method": "agent_provider_credential", "resource_type": "agent_provider", "dry_run": True},
    )
    assert rejected_agent_websession_ref.status_code == 200, rejected_agent_websession_ref.text
    rejected_agent_websession_callback = client.post(
        f"/v1/admin/authorized-resource-sessions/{rejected_agent_websession_ref.json()['id']}/callback",
        headers=HEADERS,
        json={
            "status": "completed",
            "credential_ref": "websession://providers/openai_image/bad_agent",
            "auth_method": "agent_provider_credential",
            "resource_type": "agent_provider",
            "account": {
                "id": "acct_openai_bad_websession_agent",
                "supported_operations": ["text_to_image"],
                "supported_provider_models": ["gpt-image-2"],
            },
        },
    )
    assert rejected_agent_websession_callback.status_code == 400 and "ACCOUNT_CREDENTIAL_REF_RESOURCE_MISMATCH" in rejected_agent_websession_callback.text, rejected_agent_websession_callback.text
    cookie_secret = assert_ok(
        client.post(
            "/v1/admin/credential-secrets",
            headers=HEADERS,
            json={
                "id": "secret_cookie_kind_guard",
                "name": "Cookie Kind Guard",
                "value": "session-token=kind-guard",
                "kind": "cookie",
                "provider_id": "openai_image",
                "account_id": "acct_cookie_kind_guard",
            },
        )
    )
    rejected_agent_from_cookie_secret = client.post(
        "/v1/admin/account-onboarding",
        headers=HEADERS,
        json={
            "provider_id": "openai_image",
            "account_id": "acct_openai_bad_cookie_secret_agent",
            "label": "OpenAI Bad Cookie Secret Agent",
            "resource_type": "agent_provider",
            "auth_method": "agent_provider_credential",
            "credential_kind": "custom",
            "credential_ref": cookie_secret["ref"],
            "supported_operations": ["text_to_image"],
            "supported_provider_models": ["gpt-image-2"],
            "sync_capabilities": False,
            "run_health_check": False,
        },
    )
    assert rejected_agent_from_cookie_secret.status_code == 400 and "ACCOUNT_CREDENTIAL_REF_RESOURCE_MISMATCH" in rejected_agent_from_cookie_secret.text, rejected_agent_from_cookie_secret.text
    agent_secret = assert_ok(
        client.post(
            "/v1/admin/credential-secrets",
            headers=HEADERS,
            json={
                "id": "secret_agent_kind_guard",
                "name": "Agent Kind Guard",
                "value": '{"profile":"kind-guard"}',
                "kind": "agent_provider",
                "provider_id": "openai_image",
                "account_id": "acct_agent_kind_guard",
            },
        )
    )
    rejected_cookie_from_agent_secret = client.post(
        "/v1/admin/account-onboarding",
        headers=HEADERS,
        json={
            "provider_id": "openai_image",
            "account_id": "acct_openai_bad_agent_secret_cookie",
            "label": "OpenAI Bad Agent Secret Cookie",
            "resource_type": "web_cookie_provider",
            "auth_method": "cookie_secret",
            "credential_kind": "custom",
            "credential_ref": agent_secret["ref"],
            "supported_operations": ["text_to_image"],
            "supported_provider_models": ["gpt-image-2"],
            "sync_capabilities": False,
            "run_health_check": False,
        },
    )
    assert rejected_cookie_from_agent_secret.status_code == 400 and "ACCOUNT_CREDENTIAL_REF_RESOURCE_MISMATCH" in rejected_cookie_from_agent_secret.text, rejected_cookie_from_agent_secret.text
    print("PASS credential ref/resource type guard: openai_image")

    bulk_legacy_agent = assert_ok(
        client.post(
            "/v1/admin/accounts/bulk-upsert",
            headers=HEADERS,
            json={
                "accounts": [
                    {
                        "id": "acct_gemini_bulk_legacy_api_key",
                        "provider_id": "gemini",
                        "label": "Gemini Bulk Legacy API Key",
                        "credential_value": "legacy-api-key-as-agent-material",
                        "credential_kind": "api_key",
                        "supported_operations": ["text_to_image"],
                        "supported_provider_models": ["nano-banana-pro"],
                    }
                ]
            },
        )
    )
    assert bulk_legacy_agent["created_accounts"] == 0 and bulk_legacy_agent["errors"], bulk_legacy_agent
    assert "gemini_oauth_material" in json.dumps(bulk_legacy_agent, ensure_ascii=False), bulk_legacy_agent
    bulk_real_agent = assert_ok(
        client.post(
            "/v1/admin/accounts/bulk-upsert",
            headers=HEADERS,
            json={
                "accounts": [
                    {
                        "id": "acct_gemini_bulk_oauth_material",
                        "provider_id": "gemini",
                        "label": "Gemini Bulk OAuth Material",
                        "credential_value": '{"GEMINI_CREDENTIALS":{"client_id":"bulk-client","refresh_token":"bulk-refresh"}}',
                        "credential_kind": "agent_provider",
                        "supported_operations": ["text_to_image"],
                        "supported_provider_models": ["nano-banana-pro"],
                    }
                ]
            },
        )
    )
    assert bulk_real_agent["created_accounts"] == 1 and not bulk_real_agent["errors"], bulk_real_agent
    bulk_row = bulk_real_agent["data"][0]
    assert bulk_row["account"]["resource_type"] == "agent_provider", bulk_row
    assert bulk_row["account"]["resource_profile"]["credential_kind"] == "agent_provider", bulk_row
    assert bulk_row["secret"]["kind"] == "agent_provider", bulk_row
    rejected_midjourney_bulk_agent = assert_ok(
        client.post(
            "/v1/admin/accounts/bulk-upsert",
            headers=HEADERS,
            json={
                "accounts": [
                    {
                        "id": "acct_midjourney_bulk_bad_agent",
                        "provider_id": "midjourney",
                        "label": "Midjourney Bad Bulk Agent",
                        "credential_ref": "agent://providers/midjourney/bad_bulk",
                        "credential_kind": "agent_provider",
                        "supported_operations": ["text_to_image"],
                        "supported_provider_models": ["mj-v7"],
                    }
                ]
            },
        )
    )
    assert rejected_midjourney_bulk_agent["created_accounts"] == 0 and rejected_midjourney_bulk_agent["errors"], rejected_midjourney_bulk_agent
    assert "PROVIDER_RESOURCE_TYPE_NOT_ALLOWED" in json.dumps(rejected_midjourney_bulk_agent, ensure_ascii=False), rejected_midjourney_bulk_agent
    rejected_midjourney_bulk_missing_credential = assert_ok(
        client.post(
            "/v1/admin/accounts/bulk-upsert",
            headers=HEADERS,
            json={
                "accounts": [
                    {
                        "id": "acct_midjourney_bulk_missing_credential",
                        "provider_id": "midjourney",
                        "label": "Midjourney Missing Bulk Credential",
                        "resource_type": "web_cookie_provider",
                        "credential_kind": "cookie",
                        "resource_profile": {"guild_id": "guild-bulk", "channel_id": "channel-bulk"},
                        "supported_operations": ["text_to_image"],
                        "supported_provider_models": ["mj-v7"],
                    }
                ]
            },
        )
    )
    assert rejected_midjourney_bulk_missing_credential["created_accounts"] == 0 and rejected_midjourney_bulk_missing_credential["errors"], rejected_midjourney_bulk_missing_credential
    assert "PROVIDER_REQUIRED_INPUT_MISSING" in json.dumps(rejected_midjourney_bulk_missing_credential, ensure_ascii=False), rejected_midjourney_bulk_missing_credential
    print("PASS bulk account resource kind normalization")

    cookie_account = assert_ok(
        client.post(
            "/v1/admin/account-onboarding",
            headers=HEADERS,
            json={
                "provider_id": "openai_image",
                "account_id": "acct_chatgpt_cookie_smoke",
                "label": "ChatGPT Cookie Smoke",
                "resource_type": "web_cookie_provider",
                "resource_profile": {"cookie_domain_scope": "chatgpt.com", "session_expires_at": "2026-07-01T00:00:00Z"},
                "auth_method": "cookie_secret",
                "credential_kind": "cookie",
                "credential_value": "session-token=smoke; path=/; secure",
                "supported_operations": ["text_to_image", "image_edit"],
                "supported_provider_models": ["gpt-image-2"],
                "concurrency_limit": 1,
                "sync_capabilities": False,
                "run_health_check": False,
            },
        )
    )
    account = cookie_account["account"]
    assert account["resource_type"] == "web_cookie_provider"
    assert account["credential_ref"].startswith("secret://")
    assert account["resource_profile"]["cookie_domain_scope"] == "chatgpt.com"
    print("PASS web cookie account: encrypted profile")

    rejected_gemini_project_only = client.post(
        "/v1/admin/account-onboarding",
        headers=HEADERS,
        json={
            "provider_id": "gemini",
            "account_id": "acct_gemini_project_only",
            "label": "Gemini Project Only",
            "resource_type": "agent_provider",
            "resource_profile": {"agent_runtime_endpoint": "http://127.0.0.1:19091"},
            "auth_method": "agent_provider_credential",
            "credential_kind": "agent_provider",
            "credential_value": '{"GEMINI_PROJECT_ID":"project-only"}',
            "supported_operations": ["text_to_image", "text_to_video"],
            "supported_provider_models": ["nano-banana-pro", "veo-3.1"],
            "sync_capabilities": False,
            "run_health_check": False,
        },
    )
    assert rejected_gemini_project_only.status_code == 400 and "gemini_oauth_material" in rejected_gemini_project_only.text, rejected_gemini_project_only.text
    agent_account = assert_ok(
        client.post(
            "/v1/admin/account-onboarding",
            headers=HEADERS,
            json={
                "provider_id": "gemini",
                "account_id": "acct_gemini_agent_smoke",
                "label": "Gemini Agent Smoke",
                "resource_type": "agent_provider",
                "resource_profile": {"agent_runtime_endpoint": "http://127.0.0.1:19091", "workspace_policy": "isolated"},
                "auth_method": "agent_provider_credential",
                "credential_kind": "agent_provider",
                "credential_value": '{"GEMINI_CREDENTIALS":{"client_id":"smoke-client","refresh_token":"smoke-refresh"},"GEMINI_PROJECT_ID":"smoke-project"}',
                "supported_operations": ["text_to_image", "text_to_video"],
                "supported_provider_models": ["nano-banana-pro", "veo-3.1"],
                "concurrency_limit": 1,
                "sync_capabilities": False,
                "run_health_check": False,
            },
        )
    )
    account = agent_account["account"]
    assert account["resource_type"] == "agent_provider"
    assert account["credential_ref"].startswith("secret://")
    assert account["resource_profile"]["agent_runtime_endpoint"] == "http://127.0.0.1:19091"
    print("PASS agent provider account: encrypted profile")

    with SessionLocal() as db:
        provider = db.get(models.Provider, "midjourney")
        assert provider is not None
        provider.base_config_json = dumps({"base_url": "http://legacy-runner.invalid", "legacy_flag": True})
        db.commit()

    midjourney_account = assert_ok(
        client.post(
            "/v1/admin/account-onboarding",
            headers=HEADERS,
            json={
                "provider_id": "midjourney",
                "account_id": "acct_midjourney_cookie_smoke",
                "label": "Midjourney Cookie Smoke",
                "resource_type": "web_cookie_provider",
                "provider_config": {"guild_id": "guild_smoke", "channel_id": "channel_smoke", "discord_server": "discord.com"},
                "auth_method": "cookie_secret",
                "credential_kind": "cookie",
                "credential_value": "discord-session=smoke",
                "supported_operations": ["text_to_image"],
                "supported_provider_models": ["mj-v7"],
                "concurrency_limit": 1,
                "sync_capabilities": False,
                "run_health_check": False,
            },
        )
    )
    profile = midjourney_account["account"]["resource_profile"]
    assert profile["guild_id"] == "guild_smoke" and profile["channel_id"] == "channel_smoke" and profile["discord_server"] == "discord.com", profile
    assert "connector_base_url" not in profile, profile
    with SessionLocal() as db:
        provider = db.get(models.Provider, "midjourney")
        provider_config = json.loads(provider.base_config_json)
        assert "base_url" not in provider_config, provider_config
        assert provider_config["legacy_flag"] is True, provider_config
    print("PASS provider-specific profile fields: midjourney")

    rejected_unknown_profile_field = client.post(
        "/v1/admin/account-onboarding",
        headers=HEADERS,
        json={
            "provider_id": "midjourney",
            "account_id": "acct_midjourney_unknown_profile",
            "label": "Midjourney Unknown Profile",
            "resource_type": "web_cookie_provider",
            "resource_profile": {"guild_id": "guild_smoke", "channel_id": "channel_smoke", "unexpected_profile_field": "x"},
            "auth_method": "cookie_secret",
            "credential_kind": "cookie",
            "credential_value": "discord-session=smoke",
            "supported_operations": ["text_to_image"],
            "supported_provider_models": ["mj-v7"],
            "sync_capabilities": False,
            "run_health_check": False,
        },
    )
    assert rejected_unknown_profile_field.status_code == 400 and "PROVIDER_INPUT_FIELD_NOT_ALLOWED" in rejected_unknown_profile_field.text, rejected_unknown_profile_field.text

    rejected_unknown_provider_config_field = client.post(
        "/v1/admin/account-onboarding",
        headers=HEADERS,
        json={
            "provider_id": "midjourney",
            "account_id": "acct_midjourney_unknown_config",
            "label": "Midjourney Unknown Config",
            "resource_type": "web_cookie_provider",
            "provider_config": {"guild_id": "guild_smoke", "channel_id": "channel_smoke", "unexpected_provider_config": "x"},
            "auth_method": "cookie_secret",
            "credential_kind": "cookie",
            "credential_value": "discord-session=smoke",
            "supported_operations": ["text_to_image"],
            "supported_provider_models": ["mj-v7"],
            "sync_capabilities": False,
            "run_health_check": False,
        },
    )
    assert rejected_unknown_provider_config_field.status_code == 400 and "PROVIDER_INPUT_FIELD_NOT_ALLOWED" in rejected_unknown_provider_config_field.text, rejected_unknown_provider_config_field.text
    print("PASS provider-specific profile field whitelist: midjourney")

    rejected_base_url = client.post(
        "/v1/admin/account-onboarding",
        headers=HEADERS,
        json={
            "provider_id": "midjourney",
            "account_id": "acct_midjourney_bad_base_url",
            "label": "Midjourney Bad Base URL",
            "resource_type": "web_cookie_provider",
            "provider_base_url": "http://127.0.0.1:18091",
            "provider_config": {"guild_id": "guild_smoke", "channel_id": "channel_smoke"},
            "auth_method": "cookie_secret",
            "credential_kind": "cookie",
            "credential_value": "discord-session=smoke",
            "supported_operations": ["text_to_image"],
            "supported_provider_models": ["mj-v7"],
            "sync_capabilities": False,
            "run_health_check": False,
        },
    )
    assert rejected_base_url.status_code == 400, rejected_base_url.text
    rejected_body = rejected_base_url.json()
    assert "PROVIDER_BASE_URL_NOT_ALLOWED" in str(rejected_body), rejected_body
    print("PASS provider base_url guard: midjourney")

    rejected_config_base_url = client.post(
        "/v1/admin/account-onboarding",
        headers=HEADERS,
        json={
            "provider_id": "midjourney",
            "account_id": "acct_midjourney_bad_config_base_url",
            "label": "Midjourney Bad Config Base URL",
            "resource_type": "web_cookie_provider",
            "provider_config": {"base_url": "http://127.0.0.1:18091", "guild_id": "guild_smoke"},
            "auth_method": "cookie_secret",
            "credential_kind": "cookie",
            "credential_value": "discord-session=smoke",
            "supported_operations": ["text_to_image"],
            "supported_provider_models": ["mj-v7"],
            "sync_capabilities": False,
            "run_health_check": False,
        },
    )
    assert rejected_config_base_url.status_code == 400 and "provider_config.base_url" in rejected_config_base_url.text, rejected_config_base_url.text

    rejected_profile_base_url = client.post(
        "/v1/admin/account-onboarding",
        headers=HEADERS,
        json={
            "provider_id": "midjourney",
            "account_id": "acct_midjourney_bad_profile_base_url",
            "label": "Midjourney Bad Profile Base URL",
            "resource_type": "web_cookie_provider",
            "resource_profile": {"connector_base_url": "http://127.0.0.1:18091", "guild_id": "guild_smoke"},
            "auth_method": "cookie_secret",
            "credential_kind": "cookie",
            "credential_value": "discord-session=smoke",
            "supported_operations": ["text_to_image"],
            "supported_provider_models": ["mj-v7"],
            "sync_capabilities": False,
            "run_health_check": False,
        },
    )
    assert rejected_profile_base_url.status_code == 400 and "resource_profile.connector_base_url" in rejected_profile_base_url.text, rejected_profile_base_url.text
    print("PASS nested runtime/base_url guards: midjourney")

    accounts = assert_ok(client.get("/v1/accounts", headers=HEADERS))
    resource_types = {item["id"]: item["resource_type"] for item in accounts["data"]}
    assert resource_types["acct_chatgpt_cookie_smoke"] == "web_cookie_provider"
    assert resource_types["acct_gemini_agent_smoke"] == "agent_provider"
    assert resource_types["acct_midjourney_cookie_smoke"] == "web_cookie_provider"
    print("web cookie / agent provider smoke ok")


if __name__ == "__main__":
    main()
