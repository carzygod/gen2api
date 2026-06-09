from __future__ import annotations

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "var" / "oauth_session_smoke.db"
ASSET_DIR = ROOT / "var" / "oauth-session-smoke-assets"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
if DB_PATH.exists():
    DB_PATH.unlink()
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH.as_posix()}"
os.environ["ASSET_DIR"] = ASSET_DIR.as_posix()
sys.path.insert(0, str(ROOT))

from media2api import models
from media2api.database import SessionLocal, init_db
from media2api.main import app, dumps
from media2api.security import hash_api_key
from media2api.services_connector_registry import PLATFORM_INPUT_REQUIREMENTS


HEADERS = {"Authorization": "Bearer dev-admin-key"}


class OAuthSidecarHandler(BaseHTTPRequestHandler):
    start_payload: dict = {}
    start_response: dict | None = None

    def _json(self, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("content-length") or "0")
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return {}

    def do_POST(self) -> None:
        if self.path.startswith("/oauth/start"):
            OAuthSidecarHandler.start_payload = self._read_json()
            if OAuthSidecarHandler.start_response is not None:
                self._json(OAuthSidecarHandler.start_response)
                return
            self._json(
                {
                    "status": "pending",
                    "connector_session_id": "sidecar_sess_01",
                    "authorize_url": f"http://127.0.0.1:{self.server.server_port}/login/sidecar_sess_01",
                    "account": {
                        "id": "acct_oauth_smoke",
                        "label": "OAuth Smoke Account",
                        "auth_method": "web_session",
                        "supported_operations": ["text_to_image", "text_to_video"],
                        "supported_provider_models": ["oauth-smoke-image", "oauth-smoke-video"],
                    },
                }
            )
            return
        self._json({"status": "not_found"})

    def do_GET(self) -> None:
        if self.path.startswith("/oauth/sessions/sidecar_sess_01"):
            self._json(
                {
                    "status": "completed",
                    "account": {
                        "id": "acct_oauth_smoke",
                        "label": "OAuth Smoke Account",
                        "credential_ref": "websession://providers/oauth_smoke/acct_01",
                        "auth_method": "web_session",
                        "supported_operations": ["text_to_image", "text_to_video"],
                        "supported_provider_models": ["oauth-smoke-image", "oauth-smoke-video"],
                        "quota_buckets": [{"type": "credits", "remaining_estimate": 88, "confidence": 0.9}],
                        "concurrency_limit": 3,
                        "region": "us",
                        "plan": "pro",
                    },
                }
            )
            return
        self._json({"status": "ok"})

    def log_message(self, format: str, *args) -> None:
        return


def assert_ok(resp):
    if resp.status_code >= 400:
        raise AssertionError(f"{resp.status_code}: {resp.text}")
    return resp.json()


def request(client: TestClient, method: str, path: str, **kwargs):
    return assert_ok(getattr(client, method)(path, headers=HEADERS, **kwargs))


def seed_admin_and_provider(base_url: str) -> None:
    with SessionLocal() as db:
        db.merge(models.User(id="usr_admin", email="admin@media2api.local", status="active", tier="admin", wallet_balance=100000))
        db.merge(models.ApiKey(id="key_dev_admin", user_id="usr_admin", name="dev admin", key_hash=hash_api_key("dev-admin-key"), status="active"))
        db.merge(
            models.Provider(
                id="oauth_smoke",
                name="OAuth Smoke",
                adapter_type="http_adapter",
                status="active",
                base_config_json=dumps({"base_url": base_url, "oauth_timeout_seconds": 5}),
                notes="OAuth session smoke provider",
            )
        )
        db.merge(
            models.Provider(
                id="midjourney",
                name="Midjourney Stale Base URL",
                adapter_type="http_adapter",
                status="active",
                base_config_json=dumps({"base_url": base_url, "oauth_timeout_seconds": 5}),
                notes="stale base_url must not bypass platform input requirements",
            )
        )
        db.merge(
            models.Provider(
                id="runway",
                name="Runway Agent Only",
                adapter_type="http_adapter",
                status="active",
                base_config_json=dumps({}),
                notes="agent-only authorized resource guard",
            )
        )
        db.merge(
            models.Provider(
                id="oauth_required_sync",
                name="Required Sync OAuth",
                adapter_type="http_adapter",
                status="active",
                base_config_json=dumps({"base_url": base_url, "oauth_timeout_seconds": 5}),
                notes="sync completion must satisfy platform required fields",
            )
        )
        db.commit()


def main() -> None:
    init_db()
    PLATFORM_INPUT_REQUIREMENTS["oauth_required_sync"] = {
        "primary_resource_type": "web_cookie_provider",
        "accepted_resource_types": ["web_cookie_provider"],
        "opensource_basis": ["oauth-required-sync-smoke"],
        "user_inputs": [
            {"name": "session_or_cookie", "label": "Session or cookie", "required": True, "auth_method": "cookie_secret", "store_as": "encrypted_secret", "evidence": "oauth_session_smoke_test"},
            {"name": "guild_id", "label": "Guild ID", "required": True, "evidence": "oauth_session_smoke_test"},
            {"name": "runner_endpoint", "label": "Runner endpoint", "required": False, "evidence": "oauth_session_smoke_test"},
        ],
    }
    server = HTTPServer(("127.0.0.1", 0), OAuthSidecarHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    seed_admin_and_provider(base_url)
    client = TestClient(app)
    checks: list[tuple[str, str]] = []

    try:
        OAuthSidecarHandler.start_payload = {}
        disallowed_start = request(
            client,
            "post",
            "/v1/admin/authorized-resource-sessions",
            json={
                "provider_id": "midjourney",
                "auth_method": "cookie_secret",
                "supported_operations": ["text_to_image"],
                "supported_provider_models": ["mj-v7"],
            },
        )
        assert disallowed_start["status"] == "planned", disallowed_start
        assert not OAuthSidecarHandler.start_payload, OAuthSidecarHandler.start_payload
        rejected_callback = client.post(
            f"/v1/admin/authorized-resource-sessions/{disallowed_start['id']}/callback",
            headers=HEADERS,
            json={
                "status": "completed",
                "credential_ref": "secret://providers/midjourney/session_01",
                "base_url": base_url,
                "account": {
                    "id": "acct_midjourney_callback_rejected",
                    "auth_method": "cookie_secret",
                    "supported_operations": ["text_to_image"],
                    "supported_provider_models": ["mj-v7"],
                },
            },
        )
        assert rejected_callback.status_code == 400 and "PROVIDER_BASE_URL_NOT_ALLOWED" in rejected_callback.text, rejected_callback.text
        missing_required_start = request(
            client,
            "post",
            "/v1/admin/authorized-resource-sessions",
            json={
                "provider_id": "midjourney",
                "auth_method": "cookie_secret",
                "supported_operations": ["text_to_image"],
                "supported_provider_models": ["mj-v7"],
            },
        )
        missing_required_callback = client.post(
            f"/v1/admin/authorized-resource-sessions/{missing_required_start['id']}/callback",
            headers=HEADERS,
            json={
                "status": "completed",
                "credential_ref": "secret://providers/midjourney/session_missing_required",
                "auth_method": "cookie_secret",
                "account": {
                    "id": "acct_midjourney_callback_missing_required",
                    "supported_operations": ["text_to_image"],
                    "supported_provider_models": ["mj-v7"],
                },
            },
        )
        assert missing_required_callback.status_code == 400 and "PROVIDER_REQUIRED_INPUT_MISSING" in missing_required_callback.text, missing_required_callback.text
        missing_required_detail = request(client, "get", f"/v1/admin/authorized-resource-sessions/{missing_required_start['id']}")
        assert missing_required_detail["status"] == "planned" and not missing_required_detail["credential_ref"], missing_required_detail
        midjourney_session_secret = request(
            client,
            "post",
            "/v1/admin/credential-secrets",
            json={
                "id": "providers/midjourney/session_callback_ok",
                "name": "Midjourney Callback OK Session",
                "value": "mj-session=callback-ok; path=/; secure",
                "kind": "cookie",
                "provider_id": "midjourney",
                "account_id": "acct_midjourney_callback_ok",
            },
        )
        midjourney_ok_start = request(
            client,
            "post",
            "/v1/admin/authorized-resource-sessions",
            json={
                "provider_id": "midjourney",
                "auth_method": "cookie_secret",
                "account_id": "acct_midjourney_callback_ok",
                "supported_operations": ["text_to_image"],
                "supported_provider_models": ["mj-v7"],
            },
        )
        midjourney_callback = request(
            client,
            "post",
            f"/v1/admin/authorized-resource-sessions/{midjourney_ok_start['id']}/callback",
            json={
                "status": "completed",
                "credential_ref": midjourney_session_secret["ref"],
                "auth_method": "cookie_secret",
                "account": {
                    "id": "acct_midjourney_callback_ok",
                    "label": "Midjourney Callback OK",
                    "resource_profile": {"guild_id": "guild_callback", "channel_id": "channel_callback"},
                    "supported_operations": ["text_to_image"],
                    "supported_provider_models": ["mj-v7"],
                },
            },
        )
        assert midjourney_callback["session"]["status"] == "completed", midjourney_callback
        assert midjourney_callback["onboarding"]["account"]["resource_type"] == "web_cookie_provider", midjourney_callback
        assert midjourney_callback["onboarding"]["account"]["resource_profile"]["guild_id"] == "guild_callback", midjourney_callback
        assert midjourney_callback["onboarding"]["account"]["resource_profile"]["channel_id"] == "channel_callback", midjourney_callback
        checks.append(("callback required platform inputs", "guarded"))
        with SessionLocal() as db:
            db.add(
                models.ConnectorOAuthSession(
                    id="oauthsess_midjourney_stale",
                    provider_id="midjourney",
                    account_id="acct_midjourney_stale",
                    label="Midjourney Stale OAuth Session",
                    status="pending",
                    auth_method="cookie_secret",
                    connector_base_url=base_url,
                    requested_operations_json=dumps(["text_to_image"]),
                    requested_provider_models_json=dumps(["mj-v7"]),
                    metadata_json=dumps(
                        {
                            "request": {"provider_base_url": base_url, "resource_profile": {"base_url": base_url, "guild_id": "guild_smoke"}},
                            "completion": {"provider_base_url": base_url, "quota_buckets": []},
                            "provider_config_keys": ["base_url", "oauth_timeout_seconds"],
                        }
                    ),
                )
            )
            db.commit()
        stale_detail = request(client, "get", "/v1/admin/authorized-resource-sessions/oauthsess_midjourney_stale")
        assert stale_detail["connector_base_url"] == "", stale_detail
        assert stale_detail["provider_base_url"] == "", stale_detail
        assert "base_url" not in stale_detail["metadata"].get("provider_config_keys", []), stale_detail
        assert "provider_base_url" not in json.dumps(stale_detail["metadata"], ensure_ascii=False), stale_detail
        stale_list = request(client, "get", "/v1/admin/authorized-resource-sessions?provider_id=midjourney")
        stale_row = next(item for item in stale_list["data"] if item["id"] == "oauthsess_midjourney_stale")
        assert stale_row["connector_base_url"] == "" and stale_row["provider_base_url"] == "", stale_row
        rejected_runway_web_resource_start = client.post(
            "/v1/admin/authorized-resource-sessions",
            headers=HEADERS,
            json={"provider_id": "runway", "auth_method": "agent_provider_credential", "resource_type": "web_cookie_provider"},
        )
        assert rejected_runway_web_resource_start.status_code == 400 and "PROVIDER_RESOURCE_TYPE_NOT_ALLOWED" in rejected_runway_web_resource_start.text, rejected_runway_web_resource_start.text
        runway_start = request(
            client,
            "post",
            "/v1/admin/authorized-resource-sessions",
            json={"provider_id": "runway", "auth_method": "agent_provider_credential", "resource_type": "agent_provider", "dry_run": True},
        )
        rejected_runway_web_resource_callback = client.post(
            f"/v1/admin/authorized-resource-sessions/{runway_start['id']}/callback",
            headers=HEADERS,
            json={
                "status": "completed",
                "credential_ref": "agent://providers/runway/acct_bad_resource",
                "auth_method": "agent_provider_credential",
                "resource_type": "web_cookie_provider",
                "account": {
                    "id": "acct_runway_bad_resource",
                    "supported_operations": ["text_to_video"],
                    "supported_provider_models": ["runway-gen4"],
                },
            },
        )
        assert rejected_runway_web_resource_callback.status_code == 400 and "PROVIDER_RESOURCE_TYPE_NOT_ALLOWED" in rejected_runway_web_resource_callback.text, rejected_runway_web_resource_callback.text
        runway_raw_material_start = request(
            client,
            "post",
            "/v1/admin/authorized-resource-sessions",
            json={
                "provider_id": "runway",
                "auth_method": "agent_provider_credential",
                "resource_type": "agent_provider",
                "account_id": "acct_runway_raw_material",
                "dry_run": True,
            },
        )
        rejected_runway_raw_material = client.post(
            f"/v1/admin/authorized-resource-sessions/{runway_raw_material_start['id']}/callback",
            headers=HEADERS,
            json={
                "status": "completed",
                "credential_value": "raw-useapi-key",
                "auth_method": "agent_provider_credential",
                "resource_type": "agent_provider",
                "account": {
                    "id": "acct_runway_raw_material",
                    "supported_operations": ["text_to_video"],
                    "supported_provider_models": ["runway-gen4"],
                },
            },
        )
        assert rejected_runway_raw_material.status_code == 400 and "PROVIDER_REQUIRED_INPUT_MISSING" in rejected_runway_raw_material.text, rejected_runway_raw_material.text
        runway_material_start = request(
            client,
            "post",
            "/v1/admin/authorized-resource-sessions",
            json={
                "provider_id": "runway",
                "auth_method": "agent_provider_credential",
                "resource_type": "agent_provider",
                "account_id": "acct_runway_material_ok",
                "dry_run": True,
            },
        )
        runway_material_callback = request(
            client,
            "post",
            f"/v1/admin/authorized-resource-sessions/{runway_material_start['id']}/callback",
            json={
                "status": "completed",
                "credential_value": {"apiKey": "useapi-smoke-key"},
                "auth_method": "agent_provider_credential",
                "resource_type": "agent_provider",
                "account": {
                    "id": "acct_runway_material_ok",
                    "label": "Runway Material OK",
                    "supported_operations": ["text_to_video"],
                    "supported_provider_models": ["runway-gen4"],
                },
            },
        )
        assert runway_material_callback["session"]["status"] == "completed", runway_material_callback
        assert runway_material_callback["session"]["credential_ref"] == "secret://secret_acct_runway_material_ok", runway_material_callback
        assert runway_material_callback["onboarding"]["account"]["resource_type"] == "agent_provider", runway_material_callback
        assert runway_material_callback["onboarding"]["account"]["credential_ref"] == "secret://secret_acct_runway_material_ok", runway_material_callback
        assert "useapi-smoke-key" not in json.dumps(runway_material_callback, ensure_ascii=False), runway_material_callback
        with SessionLocal() as db:
            runway_secret = db.get(models.CredentialSecret, "secret_acct_runway_material_ok")
            assert runway_secret and runway_secret.kind == "agent_provider" and runway_secret.provider_id == "runway", runway_secret
        checks.append(("callback credential material", "validated and materialized"))
        checks.append(("stale provider base_url ignored", disallowed_start["status"]))

        OAuthSidecarHandler.start_response = {
            "status": "completed",
            "account": {
                "id": "acct_bad_sidecar_ref",
                "label": "Bad Sidecar Credential",
                "credential_ref": "agent://providers/oauth_smoke/bad_cookie_start",
                "auth_method": "web_session",
                "supported_operations": ["text_to_image"],
                "supported_provider_models": ["oauth-smoke-image"],
            },
        }
        bad_start = request(
            client,
            "post",
            "/v1/admin/authorized-resource-sessions",
            json={
                "provider_id": "oauth_smoke",
                "auth_method": "cookie_secret",
                "resource_type": "web_cookie_provider",
                "resource_profile": {"login_context": "operator-start-profile"},
                "supported_operations": ["text_to_image"],
                "supported_provider_models": ["oauth-smoke-image"],
            },
        )
        assert bad_start["status"] == "failed", bad_start
        assert not bad_start["credential_ref"], bad_start
        assert "AUTHORIZED_RESOURCE_CREDENTIAL_REF_RESOURCE_MISMATCH" in (bad_start.get("error_message") or ""), bad_start
        OAuthSidecarHandler.start_response = None
        checks.append(("start sidecar ref guard", bad_start["status"]))

        OAuthSidecarHandler.start_response = {
            "status": "completed",
            "credential_ref": "websession://providers/oauth_required_sync/missing_required",
            "auth_method": "cookie_secret",
            "account": {
                "id": "acct_oauth_required_sync_missing",
                "label": "Missing Required Sync",
                "supported_operations": ["text_to_image"],
                "supported_provider_models": ["oauth-required-image"],
            },
        }
        required_sync_missing = request(
            client,
            "post",
            "/v1/admin/authorized-resource-sessions",
            json={
                "provider_id": "oauth_required_sync",
                "auth_method": "cookie_secret",
                "resource_type": "web_cookie_provider",
                "supported_operations": ["text_to_image"],
                "supported_provider_models": ["oauth-required-image"],
            },
        )
        assert required_sync_missing["status"] == "failed" and required_sync_missing["error_code"] == "PROVIDER_REQUIRED_INPUT_MISSING", required_sync_missing
        assert not required_sync_missing["credential_ref"], required_sync_missing
        OAuthSidecarHandler.start_response = {
            "status": "completed",
            "credential_ref": "websession://providers/oauth_required_sync/ok",
            "auth_method": "cookie_secret",
            "account": {
                "id": "acct_oauth_required_sync_ok",
                "label": "Required Sync OK",
                "resource_profile": {"guild_id": "guild-sync-ok"},
                "supported_operations": ["text_to_image"],
                "supported_provider_models": ["oauth-required-image"],
            },
        }
        required_sync_ok = request(
            client,
            "post",
            "/v1/admin/authorized-resource-sessions",
            json={
                "provider_id": "oauth_required_sync",
                "auth_method": "cookie_secret",
                "resource_type": "web_cookie_provider",
                "resource_profile": {"input_requirements": PLATFORM_INPUT_REQUIREMENTS["oauth_required_sync"]["user_inputs"], "guild_id": ""},
                "supported_operations": ["text_to_image"],
                "supported_provider_models": ["oauth-required-image"],
            },
        )
        assert required_sync_ok["status"] == "completed" and required_sync_ok["credential_ref"] == "websession://providers/oauth_required_sync/ok", required_sync_ok
        assert required_sync_ok["metadata"]["completion"]["resource_profile"]["guild_id"] == "guild-sync-ok", required_sync_ok
        assert required_sync_ok["metadata"]["completion"]["resource_profile"]["input_requirements"], required_sync_ok
        required_sync_complete = request(
            client,
            "post",
            f"/v1/admin/authorized-resource-sessions/{required_sync_ok['id']}/complete",
            json={"create_account": True},
        )
        assert required_sync_complete["session"]["status"] == "completed", required_sync_complete
        assert required_sync_complete["onboarding"]["account"]["id"] == "acct_oauth_required_sync_ok", required_sync_complete
        assert required_sync_complete["onboarding"]["account"]["resource_profile"]["guild_id"] == "guild-sync-ok", required_sync_complete
        OAuthSidecarHandler.start_response = None
        checks.append(("start sync required platform inputs", "guarded"))

        start = request(
            client,
            "post",
            "/v1/admin/authorized-resource-sessions",
            json={
                "provider_id": "oauth_smoke",
                "auth_method": "cookie_secret",
                "resource_type": "web_cookie_provider",
                "resource_profile": {"login_context": "operator-start-profile"},
                "supported_operations": ["text_to_image"],
                "supported_provider_models": ["oauth-smoke-image"],
            },
        )
        assert start["status"] == "pending", start
        assert start["connector_session_id"] == "sidecar_sess_01", start
        assert "/v1/admin/authorized-resource-sessions/" in start["callback_url"], start
        assert OAuthSidecarHandler.start_payload["callback_url"].endswith(f"/{start['id']}/callback")
        assert OAuthSidecarHandler.start_payload["resource_type"] == "web_cookie_provider", OAuthSidecarHandler.start_payload
        assert OAuthSidecarHandler.start_payload["resource_profile"]["login_context"] == "operator-start-profile", OAuthSidecarHandler.start_payload
        checks.append(("start session", start["status"]))

        completed = request(client, "post", f"/v1/admin/authorized-resource-sessions/{start['id']}/complete", json={"create_account": True})
        assert completed["session"]["status"] == "completed", completed
        assert completed["session"]["auth_method"] == "cookie_secret", completed
        assert completed["onboarding"]["account"]["id"] == "acct_oauth_smoke", completed
        assert completed["onboarding"]["account"]["credential_ref"] == "secret://secret_acct_oauth_smoke", completed
        assert completed["onboarding"]["account"]["concurrency_limit"] == 3, completed
        assert completed["onboarding"]["account"]["region"] == "us", completed
        assert completed["onboarding"]["account"]["plan"] == "pro", completed
        checks.append(("complete creates account", completed["onboarding"]["account"]["id"]))

        callback_start = request(
            client,
            "post",
            "/v1/admin/authorized-resource-sessions",
            json={"provider_id": "oauth_smoke", "auth_method": "agent_provider_credential", "account_id": "acct_oauth_callback", "dry_run": True},
        )
        callback = request(
            client,
            "post",
            f"/v1/admin/authorized-resource-sessions/{callback_start['id']}/callback",
            json={
                "status": "completed",
                "credential_ref": "agent://providers/oauth_smoke/acct_callback",
                "auth_method": "agent_provider_credential",
                "account": {
                    "id": "acct_oauth_callback",
                    "label": "OAuth Callback Account",
                    "supported_operations": ["text_to_image"],
                    "supported_provider_models": ["oauth-smoke-image"],
                    "quota_buckets": [{"type": "daily", "remaining_estimate": 12, "confidence": 0.8}],
                },
            },
        )
        assert callback["session"]["status"] == "completed", callback
        assert callback["onboarding"]["account"]["id"] == "acct_oauth_callback", callback
        assert callback["onboarding"]["account"]["credential_ref"] == "agent://providers/oauth_smoke/acct_callback", callback
        checks.append(("callback creates account", callback["onboarding"]["account"]["id"]))

        switched_start = request(
            client,
            "post",
            "/v1/admin/authorized-resource-sessions",
            json={"provider_id": "oauth_smoke", "auth_method": "agent_provider_credential", "account_id": "acct_oauth_switch", "dry_run": True},
        )
        switched_callback = client.post(
            f"/v1/admin/authorized-resource-sessions/{switched_start['id']}/callback",
            headers=HEADERS,
            json={
                "status": "completed",
                "credential_ref": "websession://providers/oauth_smoke/bad_switch",
                "auth_method": "cookie_secret",
                "account": {
                    "id": "acct_oauth_switch",
                    "supported_operations": ["text_to_image"],
                    "supported_provider_models": ["oauth-smoke-image"],
                },
            },
        )
        assert switched_callback.status_code == 400 and "AUTHORIZED_RESOURCE_AUTH_METHOD_RESOURCE_MISMATCH" in switched_callback.text, switched_callback.text
        checks.append(("callback auth method switch guard", "rejected"))

        sessions = request(client, "get", "/v1/admin/authorized-resource-sessions?provider_id=oauth_smoke")
        assert sessions["object"] == "media2api.authorized_resource_sessions", sessions
        assert len(sessions["data"]) >= 2, sessions
        compat_sessions = request(client, "get", "/v1/admin/oauth-sessions?provider_id=oauth_smoke")
        assert compat_sessions["compat_object"] == "media2api.connector_oauth_sessions", compat_sessions
        assert len(compat_sessions["data"]) >= 2, compat_sessions
        accounts = request(client, "get", "/v1/accounts")
        account_ids = {item["id"] for item in accounts["data"]}
        assert {"acct_oauth_smoke", "acct_oauth_callback"}.issubset(account_ids), accounts
        checks.append(("accounts visible", str(len(account_ids))))

        admin = client.get("/admin?admin_key=dev-admin-key")
        assert admin.status_code == 200
        assert "oauth-connector-response" in admin.text
        assert "oauth-credential-value" in admin.text
        assert "credential_value: credentialValue" in admin.text
        assert "oauth-auth-method" in admin.text
        assert "oauth-session-start-provider-fields" in admin.text
        assert "oauth-session-provider-fields" in admin.text
        assert "collectProviderProfileFields(providerId, 'oauth-session-start-provider-fields')" in admin.text
        assert 'data-session-subtab="authorized-session-start-pane"' in admin.text
        assert 'data-session-subtab="authorized-session-complete-pane"' in admin.text
        assert 'data-session-subtab="authorized-session-history-pane"' in admin.text
        assert 'id="authorized-session-start-pane"' in admin.text
        assert 'id="authorized-session-complete-pane"' in admin.text
        assert 'id="authorized-session-history-pane"' in admin.text
        assert ".session-subtab { display:none; }" in admin.text
        assert ".session-subtab.active { display:block; }" in admin.text
        assert "document.querySelectorAll('.session-subnav-button')" in admin.text
        assert "button.dataset.sessionSubtab" in admin.text
        checks.append(("admin oauth controls", "ok"))

        workbench = request(client, "get", "/v1/admin/operator-workbench-report")
        oauth_module = next(item for item in workbench["modules"] if item["module"] == "AuthorizedResourceSessions")
        assert any(route["path"].endswith("/callback") and "authorized-resource-sessions" in route["path"] for route in oauth_module["routes"]), oauth_module
        delivery = request(client, "get", "/v1/admin/delivery-package")
        assert "callback_route" in delivery["authorized_resource_sessions"], delivery["authorized_resource_sessions"]
        assert "connector_authorized_resource_callback" in delivery["acceptance_commands"], delivery["acceptance_commands"]
        checks.append(("delivery callback contract", "ok"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    for name, value in checks:
        print(f"PASS {name}: {value}")
    print("oauth session smoke ok")


if __name__ == "__main__":
    main()
