from __future__ import annotations

import os
import sys
from pathlib import Path

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "var" / "account_setup_workflow_smoke.db"
ASSET_DIR = ROOT / "var" / "account-setup-workflow-smoke-assets"
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


HEADERS = {"Authorization": "Bearer dev-admin-key"}


def assert_ok(resp):
    if resp.status_code >= 400:
        raise AssertionError(f"{resp.status_code}: {resp.text}")
    return resp.json()


def request(client: TestClient, method: str, path: str, **kwargs):
    return assert_ok(getattr(client, method)(path, headers=HEADERS, **kwargs))


def seed_admin_and_project() -> None:
    with SessionLocal() as db:
        db.merge(models.User(id="usr_admin", email="admin@media2api.local", status="active", tier="admin", wallet_balance=100000))
        db.merge(models.ApiKey(id="key_dev_admin", user_id="usr_admin", name="dev admin", key_hash=hash_api_key("dev-admin-key"), status="active"))
        db.merge(
            models.OpenSourceConnectorProject(
                id="testorg__gemini-media-connector",
                repo_url="https://github.com/testorg/gemini-media-connector",
                owner="testorg",
                repo="gemini-media-connector",
                local_path="source-repo/gemini-media-connector",
                project_type="web_to_api",
                status="evaluated",
                risk_level="medium",
                provider_ids_json=dumps(["gemini"]),
                platforms_json=dumps(["Gemini", "Google AI Studio"]),
                models_json=dumps(["nano-banana-pro", "veo-3.1"]),
                operations_json=dumps(["text_to_image", "image_to_image", "text_to_video", "image_to_video"]),
                auth_types_json=dumps(["agent_provider_credential"]),
                downstream_auth_json=dumps(["agent_provider_credential"]),
                evidence_json=dumps(
                    {
                        "reason": "account setup workflow smoke",
                        "classification": {"raw_auth_hints": ["oauth_reference", "cli_credential_reference"]},
                    }
                ),
                maintenance_status="unknown",
                license="MIT",
                notes="Seeded for account setup workflow smoke.",
            )
        )
        db.merge(
            models.OpenSourceConnectorProject(
                id="testorg__midjourney-proxy-fields",
                repo_url="https://github.com/testorg/midjourney-proxy-fields",
                owner="testorg",
                repo="midjourney-proxy-fields",
                local_path="source-repo/midjourney-proxy-fields",
                project_type="web_to_api",
                status="evaluated",
                risk_level="medium",
                provider_ids_json=dumps(["midjourney"]),
                platforms_json=dumps(["Midjourney", "Discord"]),
                models_json=dumps(["mj-v7"]),
                operations_json=dumps(["text_to_image", "image_to_image"]),
                auth_types_json=dumps(["cookie_secret"]),
                downstream_auth_json=dumps(["cookie_secret"]),
                evidence_json=dumps({"reason": "account setup workflow base_url guard"}),
                maintenance_status="unknown",
                license="MIT",
                notes="Seeded for account setup workflow smoke.",
            )
        )
        db.commit()


def main() -> None:
    init_db()
    seed_admin_and_project()
    client = TestClient(app)
    checks: list[tuple[str, str]] = []

    rows = request(client, "get", "/v1/admin/account-setup-workflows?provider_id=gemini&include_preflight=false")
    assert rows["object"] == "media2api.account_setup_workflows"
    assert rows["summary"]["providers"] == 1
    assert rows["data"][0]["summary"]["preflight_status"] == "skipped"
    checks.append(("workflow list", rows["data"][0]["status"]))

    detail = request(client, "get", "/v1/admin/account-setup-workflows/gemini?include_preflight=false")
    assert detail["provider_id"] == "gemini"
    assert "apply_manifest" in detail["commands"]
    assert any(check["id"] == "preflight" and check["ok"] for check in detail["checks"])
    assert "input_requirements" in detail["summary"], detail["summary"]
    assert "dynamic_profile_fields" in detail["summary"], detail["summary"]
    assert "resource_profile_template" in detail["summary"], detail["summary"]
    checks.append(("workflow detail", detail["next_action"]["step"]))

    plan = request(client, "post", "/v1/admin/account-setup-workflows/gemini/run", json={"step": "plan", "include_preflight": False, "dry_run": True})
    assert plan["object"] == "media2api.account_setup_workflow"
    checks.append(("run plan", plan["status"]))

    blueprint_payload = {
        "step": "project_blueprint",
        "project_id": "testorg__gemini-media-connector",
        "base_url": "http://127.0.0.1:18091",
        "auth_method": "agent_provider_credential",
        "resource_type": "agent_provider",
        "resource_profile": {"workspace_policy": "isolated"},
        "credential_ref": "agent://providers/gemini/acct_01",
        "operations": ["text_to_image", "text_to_video"],
        "supported_provider_models": ["nano-banana-pro", "veo-3.1"],
        "include_preflight": False,
        "dry_run": True,
    }
    blueprint = request(client, "post", "/v1/admin/account-setup-workflows/gemini/run", json=blueprint_payload)
    assert blueprint["object"] == "media2api.connector_project_blueprint"
    assert blueprint["provider_id"] == "gemini"
    assert blueprint["external_connector_manifest"]["payload"]["resource_profile"]["workspace_policy"] == "isolated", blueprint
    assert blueprint["authorized_resource_session"]["recommended"] is True, blueprint
    assert blueprint["oauth_session"]["compatibility_alias"] is True, blueprint
    assert "start_authorized_resource_session" in blueprint["commands"], blueprint
    checks.append(("project blueprint", blueprint["status"]))

    rejected_legacy_blueprint_auth = client.get(
        "/v1/admin/connector-registry/testorg__gemini-media-connector/blueprint?provider_id=gemini&auth_method=subscription_url",
        headers=HEADERS,
    )
    assert rejected_legacy_blueprint_auth.status_code == 400 and "AUTH_METHOD_UNSUPPORTED" in rejected_legacy_blueprint_auth.text, rejected_legacy_blueprint_auth.text
    assert set(rejected_legacy_blueprint_auth.json().get("allowed_auth_methods") or []) == {"cookie_secret", "agent_provider_credential"}, rejected_legacy_blueprint_auth.text
    checks.append(("project blueprint legacy auth guard", "passed"))

    midjourney_blueprint = request(
        client,
        "get",
        "/v1/admin/connector-registry/testorg__midjourney-proxy-fields/blueprint?provider_id=midjourney",
    )
    assert midjourney_blueprint["provider_id"] == "midjourney"
    assert midjourney_blueprint["status"] == "action_required", midjourney_blueprint
    assert midjourney_blueprint["resource_profile_template"]["guild_id"] == "<required>", midjourney_blueprint
    assert midjourney_blueprint["resource_profile_template"]["channel_id"] == "<required>", midjourney_blueprint
    assert any(item["check"] == "required_platform_profile_inputs" for item in midjourney_blueprint["action_items"]), midjourney_blueprint
    assert "base_url" not in midjourney_blueprint["external_connector_manifest"]["payload"], midjourney_blueprint
    midjourney_workflow = request(client, "get", "/v1/admin/account-setup-workflows/midjourney?include_preflight=false")
    assert midjourney_workflow["summary"]["resource_profile_template"]["guild_id"] == "<required>", midjourney_workflow
    assert any(item["check"] == "required_platform_profile_inputs" for item in midjourney_workflow["action_items"]), midjourney_workflow
    midjourney_profile_blueprint = request(
        client,
        "post",
        "/v1/admin/account-setup-workflows/midjourney/run",
        json={
            "step": "project_blueprint",
            "project_id": "testorg__midjourney-proxy-fields",
            "auth_method": "cookie_secret",
            "resource_type": "web_cookie_provider",
            "resource_profile": {"guild_id": "guild_workflow", "channel_id": "channel_workflow"},
            "credential_ref": "secret://providers/midjourney/discord_session_01",
            "operations": ["text_to_image"],
            "supported_provider_models": ["mj-v7"],
            "include_preflight": False,
            "dry_run": True,
        },
    )
    assert midjourney_profile_blueprint["external_connector_manifest"]["payload"]["resource_profile"]["guild_id"] == "guild_workflow", midjourney_profile_blueprint
    assert not any(item["check"] == "required_platform_profile_inputs" for item in midjourney_profile_blueprint["action_items"]), midjourney_profile_blueprint
    bad_midjourney_blueprint = client.get(
        "/v1/admin/connector-registry/testorg__midjourney-proxy-fields/blueprint?provider_id=midjourney&base_url=http://127.0.0.1:18098",
        headers=HEADERS,
    )
    assert bad_midjourney_blueprint.status_code == 400 and "PROVIDER_BASE_URL_NOT_ALLOWED" in bad_midjourney_blueprint.text, bad_midjourney_blueprint.text
    checks.append(("midjourney blueprint base_url guard", "passed"))

    manifest_payload = {
        "step": "apply_manifest",
        "base_url": "http://127.0.0.1:18091",
        "account_id": "acct_gemini_01",
        "account_label": "Gemini production account 01",
        "auth_method": "agent_provider_credential",
        "resource_type": "agent_provider",
        "credential_ref": "agent://providers/gemini/acct_01",
        "operations": ["text_to_image", "text_to_video"],
        "supported_provider_models": ["nano-banana-pro", "veo-3.1"],
        "include_preflight": False,
    }
    manifest_preview = request(client, "post", "/v1/admin/account-setup-workflows/gemini/run", json={**manifest_payload, "dry_run": True})
    assert manifest_preview["object"] == "media2api.external_connector_manifest"
    assert manifest_preview["status"] == "planned"
    checks.append(("manifest dry-run", manifest_preview["status"]))

    manifest_installed = request(client, "post", "/v1/admin/account-setup-workflows/gemini/run", json={**manifest_payload, "dry_run": False})
    assert manifest_installed["status"] == "installed"
    checks.append(("manifest installed", manifest_installed["status"]))

    after_apply = request(client, "get", "/v1/admin/account-setup-workflows?provider_id=gemini&include_preflight=false")
    assert after_apply["summary"]["ready"] == 1, after_apply["data"][0]["checks"]
    checks.append(("workflow ready without preflight", after_apply["data"][0]["status"]))

    source_payload = {
        "step": "create_subscription_source",
        "source_id": "gemini_source_01",
        "source_name": "Gemini source 01",
        "subscription_url": "https://resource-list.example/accounts/gemini.json",
        "include_preflight": False,
    }
    source_preview = request(client, "post", "/v1/admin/account-setup-workflows/gemini/run", json={**source_payload, "dry_run": True})
    assert source_preview["object"] == "media2api.account_setup_workflow_step"
    assert source_preview["status"] == "planned"
    checks.append(("source dry-run", source_preview["status"]))

    source_created = request(client, "post", "/v1/admin/account-setup-workflows/gemini/run", json={**source_payload, "dry_run": False})
    assert source_created["object"] == "media2api.account_setup_workflow_step"
    assert source_created["status"] == "created"
    assert source_created["source"]["id"] == "gemini_source_01"
    checks.append(("source created", source_created["status"]))

    preflight = request(
        client,
        "post",
        "/v1/admin/account-setup-workflows/gemini/run",
        json={"step": "preflight", "operations": ["text_to_image", "text_to_video"], "include_preflight": False, "dry_run": True},
    )
    assert preflight["object"] == "media2api.external_connector_preflight"
    checks.append(("preflight", preflight["status"]))

    admin = client.get("/admin?admin_key=dev-admin-key")
    assert admin.status_code == 200
    assert "load-account-setup-workflow" in admin.text
    assert "connector-workflow-step" in admin.text
    assert "connector-provider-fields" in admin.text
    assert "renderProviderProfileFields(providerId, 'connector-provider-fields')" in admin.text
    assert "collectProviderProfileFields(providerId, 'connector-provider-fields')" in admin.text
    assert "connector-credential-label" in admin.text and "connector-credential-hint" in admin.text
    assert "/blueprint/apply', 'POST', payload" in admin.text
    checks.append(("admin controls", "ok"))

    workbench = request(client, "get", "/v1/admin/operator-workbench-report")
    assert any(module.get("module") == "AccountSetupWorkflows" for module in workbench.get("modules", []))
    checks.append(("workbench module", "ok"))

    delivery = request(client, "get", "/v1/admin/delivery-package")
    assert any(route.get("name") == "account_setup_workflows" for route in delivery.get("admin_reports", []))
    assert "account_setup_workflows" in delivery.get("acceptance_commands", {})
    checks.append(("delivery package", "ok"))

    for name, value in checks:
        print(f"PASS {name}: {value}")
    print("account setup workflow smoke ok")


if __name__ == "__main__":
    main()
