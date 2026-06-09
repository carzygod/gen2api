from __future__ import annotations

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "var" / "account_quickstart_smoke.db"
ASSET_DIR = ROOT / "var" / "account-quickstart-smoke-assets"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
if DB_PATH.exists():
    DB_PATH.unlink()
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH.as_posix()}"
os.environ["ASSET_DIR"] = ASSET_DIR.as_posix()
sys.path.insert(0, str(ROOT))

from media2api.catalog import seed_defaults
from media2api import models
from media2api.database import SessionLocal, init_db
from media2api.main import app
from media2api.services_connector_registry import PLATFORM_INPUT_REQUIREMENTS


HEADERS = {"Authorization": "Bearer dev-admin-key"}


class QuickstartOAuthHandler(BaseHTTPRequestHandler):
    start_response: dict | None = None

    def _json(self, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.send_header("connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        if self.path.startswith("/oauth/start"):
            self._json(QuickstartOAuthHandler.start_response or {"status": "pending", "connector_session_id": "quickstart_sidecar_sess"})
            return
        self._json({"status": "not_found"})

    def log_message(self, format: str, *args) -> None:
        return


def assert_ok(resp):
    if resp.status_code >= 400:
        raise AssertionError(f"{resp.status_code}: {resp.text}")
    return resp.json()


def request(client: TestClient, method: str, path: str, **kwargs):
    return assert_ok(getattr(client, method)(path, headers=HEADERS, **kwargs))


def seed_database(base_url: str) -> None:
    init_db()
    with SessionLocal() as db:
        seed_defaults(db)
        db.merge(
            models.Provider(
                id="oauth_required_quickstart",
                name="Required Quickstart OAuth",
                adapter_type="http_adapter",
                status="active",
                base_config_json=json.dumps({"base_url": base_url, "oauth_timeout_seconds": 5}),
                notes="quickstart sync completion must satisfy platform required fields",
            )
        )
        db.commit()


def main() -> None:
    PLATFORM_INPUT_REQUIREMENTS["oauth_required_quickstart"] = {
        "primary_resource_type": "web_cookie_provider",
        "accepted_resource_types": ["web_cookie_provider"],
        "opensource_basis": ["account-quickstart-sync-smoke"],
        "user_inputs": [
            {"name": "session_or_cookie", "label": "Session or cookie", "required": True, "auth_method": "cookie_secret", "store_as": "encrypted_secret", "evidence": "account_quickstart_smoke_test"},
            {"name": "guild_id", "label": "Guild ID", "required": True, "evidence": "account_quickstart_smoke_test"},
            {"name": "runner_endpoint", "label": "Runner endpoint", "required": False, "evidence": "account_quickstart_smoke_test"},
        ],
    }
    server = ThreadingHTTPServer(("127.0.0.1", 0), QuickstartOAuthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    seed_database(f"http://127.0.0.1:{server.server_port}")
    client = TestClient(app)
    checks: list[tuple[str, str]] = []

    dry_run = request(
        client,
        "post",
        "/v1/admin/account-setup-quickstart",
        json={
            "provider_id": "gemini",
            "mode": "auto",
            "base_url": "http://127.0.0.1:18091",
            "auth_method": "agent_provider_credential",
            "resource_type": "agent_provider",
            "credential_ref": "agent://providers/gemini/acct_quickstart",
            "account_id": "acct_gemini_quickstart",
            "operations": ["text_to_image", "text_to_video"],
            "supported_provider_models": ["nano-banana-pro", "veo-3.1"],
            "sync_capabilities": False,
            "run_health_check": False,
            "run_contract_tests": False,
            "run_preflight": False,
            "dry_run": True,
        },
    )
    assert dry_run["object"] == "media2api.account_setup_quickstart"
    assert dry_run["mode"] == "manifest" and dry_run["status"] == "planned", dry_run
    checks.append(("quickstart dry-run", dry_run["mode"]))

    installed = request(
        client,
        "post",
        "/v1/admin/account-setup-quickstart",
        json={
            "provider_id": "gemini",
            "mode": "manifest",
            "base_url": "http://127.0.0.1:18091",
            "auth_method": "agent_provider_credential",
            "resource_type": "agent_provider",
            "credential_ref": "agent://providers/gemini/acct_quickstart",
            "account_id": "acct_gemini_quickstart",
            "operations": ["text_to_image", "text_to_video"],
            "supported_provider_models": ["nano-banana-pro", "veo-3.1"],
            "sync_capabilities": False,
            "run_health_check": False,
            "run_contract_tests": False,
            "run_preflight": False,
            "dry_run": False,
        },
    )
    assert installed["status"] == "passed", installed
    assert "acct_gemini_quickstart" in installed["account_ids"], installed
    checks.append(("quickstart manifest", installed["status"]))

    subscription_payload = {
        "accounts": {
            "gemini_sub_quickstart": {
                "provider": "gemini",
                "label": "Gemini subscription quickstart",
                "auth": {"type": "agent", "ref": "agent://providers/gemini/sub_quickstart"},
                "models": [
                    {"id": "nano-banana-pro", "operations": ["t2i", "edit"]},
                    {"id": "veo-3.1", "operations": ["t2v", "i2v"]},
                ],
                "quota": {"type": "credits", "remaining": 88},
            }
        }
    }
    imported = request(
        client,
        "post",
        "/v1/admin/account-setup-quickstart",
        json={
            "provider_id": "gemini",
            "mode": "subscription",
            "apply_manifest": False,
            "auth_method": "agent_provider_credential",
            "subscription_content": json.dumps(subscription_payload),
            "operations": ["text_to_image", "image_edit", "text_to_video", "image_to_video"],
            "supported_provider_models": ["nano-banana-pro", "veo-3.1"],
            "sync_capabilities": False,
            "run_health_check": False,
            "run_preflight": False,
            "dry_run": False,
        },
    )
    assert imported["status"] == "passed", imported
    assert "gemini_sub_quickstart" in imported["account_ids"], imported
    checks.append(("quickstart subscription", imported["status"]))

    mappings = request(client, "get", "/v1/model-mappings")
    mapping_pairs = {(item["logical_model"], item["provider_model"]) for item in mappings["data"] if item["provider_id"] == "gemini"}
    assert ("t2i-fast", "nano-banana-pro") in mapping_pairs, mapping_pairs
    assert ("image-edit", "nano-banana-pro") in mapping_pairs, mapping_pairs
    assert ("t2v-general", "veo-3.1") in mapping_pairs, mapping_pairs
    assert ("i2v-fast", "veo-3.1") in mapping_pairs, mapping_pairs
    checks.append(("quickstart auto mappings", "4"))

    authorized_session = request(
        client,
        "post",
        "/v1/admin/account-setup-quickstart",
        json={
            "provider_id": "gemini",
            "mode": "authorized_session",
            "base_url": "http://127.0.0.1:18091",
            "account_id": "acct_gemini_oauth_quickstart",
            "operations": ["text_to_image", "text_to_video"],
            "supported_provider_models": ["nano-banana-pro", "veo-3.1"],
            "dry_run": True,
        },
    )
    assert authorized_session["mode"] == "authorized_session" and authorized_session["status"] == "planned", authorized_session
    checks.append(("quickstart authorized session", authorized_session["status"]))

    QuickstartOAuthHandler.start_response = {
        "status": "completed",
        "credential_ref": "websession://providers/oauth_required_quickstart/missing_required",
        "auth_method": "cookie_secret",
        "account": {
            "id": "acct_quickstart_required_missing",
            "label": "Quickstart Missing Required",
            "supported_operations": ["text_to_image"],
            "supported_provider_models": ["quickstart-image"],
        },
    }
    required_missing = request(
        client,
        "post",
        "/v1/admin/account-setup-quickstart",
        json={
            "provider_id": "oauth_required_quickstart",
            "mode": "authorized_session",
            "base_url": f"http://127.0.0.1:{server.server_port}",
            "auth_method": "cookie_secret",
            "resource_type": "web_cookie_provider",
            "account_id": "acct_quickstart_required_missing",
            "operations": ["text_to_image"],
            "supported_provider_models": ["quickstart-image"],
            "run_health_check": False,
            "run_preflight": False,
            "dry_run": False,
        },
    )
    start_step = next(step for step in required_missing["steps"] if step["step"] == "start_authorized_session")
    assert required_missing["status"] == "action_required", required_missing
    assert start_step["result"]["status"] == "failed" and start_step["result"]["error_code"] == "PROVIDER_REQUIRED_INPUT_MISSING", start_step
    checks.append(("quickstart sync required platform inputs", "guarded"))
    QuickstartOAuthHandler.start_response = None

    admin = client.get("/admin?admin_key=dev-admin-key")
    assert admin.status_code == 200
    assert "run-account-quickstart" in admin.text
    assert "/v1/admin/account-setup-quickstart" in admin.text
    checks.append(("admin quickstart controls", "ok"))

    workbench = request(client, "get", "/v1/admin/operator-workbench-report")
    module = next(item for item in workbench["modules"] if item["module"] == "AccountSetupWorkflows")
    assert any(route["path"] == "/v1/admin/account-setup-quickstart" and route["available"] for route in module["routes"])
    checks.append(("workbench quickstart route", "ok"))

    delivery = request(client, "get", "/v1/admin/delivery-package")
    assert any(route.get("name") == "account_setup_quickstart" for route in delivery.get("admin_reports", []))
    assert delivery["connector_registry"]["account_setup_quickstart_route"].endswith("/v1/admin/account-setup-quickstart")
    assert "gemini_account_setup_quickstart" in delivery.get("acceptance_commands", {})
    checks.append(("delivery quickstart route", "ok"))

    for name, value in checks:
        print(f"PASS {name}: {value}")
    print("account quickstart smoke ok")
    server.shutdown()
    thread.join(timeout=5)
    server.server_close()


if __name__ == "__main__":
    main()
