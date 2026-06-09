from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "var" / "mixed_media_connector_acceptance.db"
ASSET_DIR = ROOT / "var" / "mixed-media-connector-acceptance-assets"
VIDEO_PATH = ROOT / "var" / "mixed-media-connector-acceptance.mp4"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
if DB_PATH.exists():
    DB_PATH.unlink()
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH.as_posix()}"
os.environ["ASSET_DIR"] = ASSET_DIR.as_posix()
os.environ["MEDIA2API_INLINE_ASYNC"] = "true"
sys.path.insert(0, str(ROOT))

from media2api.catalog import seed_defaults
from media2api.database import SessionLocal, init_db
from media2api.main import app
from media2api.providers import TINY_MP4_BASE64


HEADERS = {"Authorization": "Bearer dev-admin-key"}
CONNECTOR_TOKEN = "mixed-media-connector-acceptance-token"
PROVIDER_ID = "mixed_media_reference"
ACCOUNT_ID = "acct_mixed_media_reference"
SECRET_ID = "secret_mixed_media_reference"
REQUIRED_OPERATIONS = ["text_to_image", "image_edit", "text_to_video", "image_to_video"]
PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGNkaGAAAAACAAH0nWNTAAAAAElFTkSuQmCC"


def assert_ok(resp):
    if resp.status_code >= 400:
        raise AssertionError(f"{resp.status_code}: {resp.text}")
    return resp.json()


def request(client: TestClient, method: str, path: str, **kwargs):
    return assert_ok(getattr(client, method)(path, headers=HEADERS, **kwargs))


def direct_json(method: str, url: str, payload: dict | None = None) -> dict:
    body = json.dumps(payload or {}).encode("utf-8") if payload is not None else None
    req = Request(url, data=body, method=method, headers={"Authorization": f"Bearer {CONNECTOR_TOKEN}", "Content-Type": "application/json"})
    with urlopen(req, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def generated_video_b64() -> str:
    VIDEO_PATH.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "color=c=black:s=32x18:d=1",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(VIDEO_PATH),
    ]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
        data = VIDEO_PATH.read_bytes()
        if len(data) > 100:
            return base64.b64encode(data).decode("ascii")
    except Exception:
        pass
    return TINY_MP4_BASE64


class MixedMediaConnectorServer(ThreadingHTTPServer):
    token: str
    video_b64: str
    requests: list[dict[str, Any]]

    def __init__(self, server_address: tuple[str, int], token: str) -> None:
        super().__init__(server_address, MixedMediaConnectorHandler)
        self.token = token
        self.video_b64 = generated_video_b64()
        self.requests = []


class MixedMediaConnectorHandler(BaseHTTPRequestHandler):
    server: MixedMediaConnectorServer

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("content-length") or "0")
        if length <= 0:
            return {}
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            return payload if isinstance(payload, dict) else {}
        except json.JSONDecodeError:
            return {}

    def _headers_dict(self) -> dict[str, str]:
        return {str(key).lower(): str(value) for key, value in self.headers.items()}

    def _record(self, payload: dict[str, Any] | None = None) -> None:
        parsed = urlparse(self.path)
        self.server.requests.append(
            {
                "method": self.command,
                "path": parsed.path,
                "headers": self._headers_dict(),
                "payload": payload or {},
            }
        )

    def _authorized(self) -> bool:
        expected = f"Bearer {self.server.token}"
        return not self.server.token or self.headers.get("Authorization") == expected

    def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _reject_if_unauthorized(self) -> bool:
        if self._authorized():
            return False
        self._send_json({"status": "failed", "error": "AUTH_REQUIRED"}, 401)
        return True

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if self._reject_if_unauthorized():
            return
        self._record()
        if path == "/health":
            self._send_json({"status": "ok", "service": "mixed-media-reference", "time": int(time.time())})
            return
        if path == "/capabilities":
            self._send_json(
                {
                    "operations": REQUIRED_OPERATIONS,
                    "models": ["ref-image", "ref-video"],
                    "operation_capabilities": {
                        "text_to_image": {"output_kind": "image", "max_input_assets": 0, "params": ["prompt", "model", "n", "size", "seed"]},
                        "image_edit": {"output_kind": "image", "input_asset_fields": ["image", "images", "mask"], "max_input_assets": 5, "params": ["prompt", "image", "mask", "model"]},
                        "text_to_video": {"output_kind": "video", "max_input_assets": 0, "duration_seconds": {"min": 1, "max": 10}, "params": ["prompt", "duration", "aspect_ratio", "model"]},
                        "image_to_video": {"output_kind": "video", "input_asset_fields": ["image", "images"], "max_input_assets": 4, "duration_seconds": {"min": 1, "max": 10}, "params": ["prompt", "image", "duration", "aspect_ratio", "model"]},
                    },
                }
            )
            return
        if path == "/quota":
            query = parse_qs(parsed.query)
            operations = query.get("operation") or REQUIRED_OPERATIONS
            self._send_json(
                {
                    "status": "ok",
                    "quota_buckets": [
                        {
                            "type": "credits",
                            "remaining_estimate": 1000,
                            "confidence": 0.99,
                            "operations": operations,
                            "provider_models": ["ref-image", "ref-video"],
                        }
                    ],
                }
            )
            return
        self._send_json({"status": "failed", "error": "NOT_FOUND", "path": path}, 404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if self._reject_if_unauthorized():
            return
        payload = self._read_json()
        self._record(payload)
        if path in {"/v1/images/generations", "/v1/images/edits", "/v1/videos/generations"}:
            operation = self._operation_from_path(path, payload)
            self._send_json(self._completed_response(operation))
            return
        self._send_json({"status": "failed", "error": "NOT_FOUND", "path": path}, 404)

    def _operation_from_path(self, path: str, payload: dict[str, Any]) -> str:
        if payload.get("operation"):
            return str(payload["operation"])
        if path == "/v1/videos/generations":
            return "image_to_video" if payload.get("image") or payload.get("images") else "text_to_video"
        if path == "/v1/images/edits":
            return "image_edit"
        return "text_to_image"

    def _completed_response(self, operation: str) -> dict[str, Any]:
        task_id = f"task_{operation}_{int(time.time() * 1000)}"
        if operation in {"text_to_video", "image_to_video", "video_extend"}:
            return {
                "id": task_id,
                "status": "completed",
                "data": [{"video_base64": self.server.video_b64, "mime_type": "video/mp4"}],
            }
        return {
            "id": task_id,
            "status": "completed",
            "data": [{"b64_json": PNG_B64, "mime_type": "image/png", "revised_prompt": "mixed media connector output"}],
        }

    def log_message(self, format: str, *args: Any) -> None:
        return


def create_server(host: str, port: int, token: str) -> MixedMediaConnectorServer:
    return MixedMediaConnectorServer((host, port), token)


def seed_database() -> None:
    init_db()
    with SessionLocal() as db:
        seed_defaults(db)
        db.commit()


def install_provider(client: TestClient, port: int) -> None:
    provider_payload = {
        "id": PROVIDER_ID,
        "name": "Mixed Media Reference Connector",
        "adapter_type": "http_adapter",
        "status": "active",
        "base_config": {
            "base_url": f"http://127.0.0.1:{port}",
            "credential_ref": f"secret://{SECRET_ID}",
            "api_key_header": "Authorization",
            "health_endpoint": "/health",
            "capabilities_endpoint": "/capabilities",
            "quota_endpoint": "/quota",
            "timeout_seconds": 10,
            "endpoints": {
                "text_to_image": "/v1/images/generations",
                "image_edit": "/v1/images/edits",
                "text_to_video": "/v1/videos/generations",
                "image_to_video": "/v1/videos/generations",
            },
            "task_id_paths": ["id"],
            "status_paths": ["status"],
            "output_paths": ["data", "assets", "result.assets"],
        },
        "notes": "Smoke provider for production mixed-media external connector acceptance.",
    }
    request(client, "post", "/v1/admin/providers", json=provider_payload)
    secret = request(
        client,
        "post",
        "/v1/admin/credential-secrets",
        json={
            "id": SECRET_ID,
            "name": "Mixed Media Reference Connector Token",
            "value": CONNECTOR_TOKEN,
            "kind": "agent_provider",
            "provider_id": PROVIDER_ID,
            "account_id": ACCOUNT_ID,
            "metadata": {"source": "mixed_media_connector_acceptance_test"},
        },
    )
    assert secret["ref"] == f"secret://{SECRET_ID}" and "value" not in secret, secret
    request(
        client,
        "post",
        "/v1/admin/accounts",
        json={
            "id": ACCOUNT_ID,
            "provider_id": PROVIDER_ID,
            "label": "Mixed Media Reference Account",
            "credential_ref": f"agent://providers/{PROVIDER_ID}/{ACCOUNT_ID}",
            "supported_operations": REQUIRED_OPERATIONS,
            "supported_provider_models": ["ref-image", "ref-video"],
            "quota_buckets": [{"type": "credits", "remaining_estimate": 1000, "confidence": 0.99}],
            "concurrency_limit": 4,
            "region": "local",
            "plan": "acceptance",
            "status": "active",
        },
    )

    mappings = [
        ("map_mixed_media_t2i", "t2i-fast", "ref-image", ["text_to_image"], 5),
        ("map_mixed_media_image_edit", "image-edit", "ref-image", ["image_edit"], 5),
        ("map_mixed_media_t2v", "t2v-general", "ref-video", ["text_to_video"], 5),
        ("map_mixed_media_i2v", "i2v-fast", "ref-video", ["image_to_video"], 5),
    ]
    for mapping_id, logical_model, provider_model, operations, priority in mappings:
        request(
            client,
            "post",
            "/v1/admin/model-mappings",
            json={
                "id": mapping_id,
                "logical_model": logical_model,
                "provider_id": PROVIDER_ID,
                "provider_model": provider_model,
                "operations": operations,
                "priority": priority,
                "weight": 1,
                "cost_score": 0.8,
                "speed_score": 0.9,
                "quality_score": 0.7,
                "reliability_score": 0.95,
                "enabled": True,
            },
        )


def assert_connector_forwarding(server: MixedMediaConnectorServer) -> None:
    media_posts = [
        item
        for item in server.requests
        if item["method"] == "POST" and item["path"] in {"/v1/images/generations", "/v1/images/edits", "/v1/videos/generations"}
    ]
    observed_operations = {str(item["payload"].get("operation") or "") for item in media_posts}
    assert set(REQUIRED_OPERATIONS).issubset(observed_operations), observed_operations
    for item in media_posts:
        operation = str(item["payload"].get("operation") or "")
        if operation not in REQUIRED_OPERATIONS:
            continue
        headers = item["headers"]
        payload = item["payload"]
        account = payload.get("account") if isinstance(payload.get("account"), dict) else {}
        assert headers.get("authorization") == f"Bearer {CONNECTOR_TOKEN}", headers
        assert headers.get("x-media2api-provider-id") == PROVIDER_ID, headers
        assert headers.get("x-media2api-account-id") == ACCOUNT_ID, headers
        assert headers.get("x-media2api-credential-ref") == f"agent://providers/{PROVIDER_ID}/{ACCOUNT_ID}", headers
        assert headers.get("x-media2api-credential-reference-only") == "true", headers
        assert account.get("credential_ref") == f"agent://providers/{PROVIDER_ID}/{ACCOUNT_ID}", account
        assert account.get("credential_ref_type") == "agent", account
        assert account.get("credential_reference_only") is True, account


def main() -> None:
    seed_database()
    server = create_server("127.0.0.1", 0, CONNECTOR_TOKEN)
    port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{port}"
    try:
        health = direct_json("GET", f"{base_url}/health")
        assert health["status"] == "ok", health
        capabilities = direct_json("GET", f"{base_url}/capabilities")
        assert set(REQUIRED_OPERATIONS).issubset(set(capabilities["operations"])), capabilities

        with TestClient(app) as client:
            install_provider(client, port)
            health_check = request(client, "post", f"/v1/admin/providers/{PROVIDER_ID}/health-check", json={})
            assert health_check["status"] == "ok", health_check
            capability_sync = request(client, "post", f"/v1/admin/providers/{PROVIDER_ID}/sync-capabilities", json={})
            assert capability_sync["status"] == "ok", capability_sync
            assert set(REQUIRED_OPERATIONS).issubset(set(capability_sync["capabilities"]["operations"])), capability_sync

            contract = request(
                client,
                "post",
                "/v1/admin/provider-contract-suite",
                json={"provider_ids": [PROVIDER_ID], "operations": REQUIRED_OPERATIONS, "active_only": False, "run_submit": False, "max_results": 20},
            )
            assert contract["status"] == "passed" and contract["summary"]["passed"] == len(REQUIRED_OPERATIONS), contract

            preflight = request(
                client,
                "get",
                f"/v1/admin/external-connector-preflight?provider_id={PROVIDER_ID}&account_id={ACCOUNT_ID}&operations={','.join(REQUIRED_OPERATIONS)}",
            )
            assert preflight["status"] == "ready", preflight
            assert preflight["summary"]["aggregate_missing_operations"] == [], preflight["summary"]
            assert PROVIDER_ID in preflight["summary"]["ready_provider_ids"], preflight["summary"]

            acceptance = request(
                client,
                "post",
                "/v1/admin/account-acceptance-suite",
                json={
                    "dry_run": False,
                    "provider_ids": [PROVIDER_ID],
                    "account_ids": [ACCOUNT_ID],
                    "external_only": True,
                    "active_only": True,
                    "operations": REQUIRED_OPERATIONS,
                    "run_health_check": True,
                    "run_contract_tests": True,
                    "contract_run_submit": False,
                    "run_quota_sync": True,
                    "run_samples": True,
                    "max_samples": 4,
                    "max_accounts": 5,
                    "require_production_ready": False,
                },
            )
            assert acceptance["status"] == "passed" and acceptance["ok"] is True, acceptance
            samples = acceptance["results"][0]["samples"]
            sample_operations = {sample.get("operation") for sample in samples if sample.get("ok")}
            assert set(REQUIRED_OPERATIONS).issubset(sample_operations), samples

            go_live = request(client, "get", "/v1/admin/production-go-live-plan")
            assert go_live["external_mixed_media"]["ready"] is True, go_live["external_mixed_media"]
            assert PROVIDER_ID in go_live["external_mixed_media"]["ready_provider_ids"], go_live["external_mixed_media"]

        assert_connector_forwarding(server)
        print("PASS mixed media preflight: ready")
        print("PASS mixed media account acceptance samples: 4")
        print("PASS connector account forwarding: agent reference only")
        print("mixed media connector acceptance ok")
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
