from __future__ import annotations

import base64
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from media2api.main import app


headers = {"Authorization": "Bearer dev-admin-key"}
CONNECTOR_SECRET_VALUE = "secret-smoke-token"


def tiny_png_b64() -> str:
    image = Image.new("RGB", (32, 32), color=(84, 185, 129))
    buf = BytesIO()
    image.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


class ConnectorHandler(BaseHTTPRequestHandler):
    def _authorized(self) -> bool:
        return self.headers.get("authorization") == f"Bearer {CONNECTOR_SECRET_VALUE}"

    def _unauthorized(self) -> None:
        body = b'{"error":"missing connector secret"}'
        self.send_response(401)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _png(self) -> None:
        body = base64.b64decode(tiny_png_b64())
        self.send_response(200)
        self.send_header("content-type", "image/png")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        if not self._authorized():
            self._unauthorized()
            return
        length = int(self.headers.get("content-length") or "0")
        raw_body = self.rfile.read(length)
        try:
            payload = json.loads(raw_body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            payload = {}
        if payload.get("prompt") == "connector async smoke":
            self._json({"id": "task_connector_async", "status": "queued"})
            return
        if payload.get("prompt") == "connector custom path smoke":
            self._json({"task": {"uid": "task_connector_custom", "state": "pending"}})
            return
        self._json(
            {
                "created": 1,
                "status": "completed",
                "api_key": "sk-should-not-leak",
                "token": "bearer should-not-leak",
                "authorization": "Bearer should-not-leak",
                "data": [{"b64_json": tiny_png_b64(), "mime_type": "image/png"}],
            }
        )

    def do_GET(self) -> None:
        if self.path.startswith("/media/custom.png"):
            self._png()
            return
        if not self._authorized():
            self._unauthorized()
            return
        if self.path.startswith("/quota"):
            self._json(
                {
                    "status": "ok",
                    "message": "quota smoke",
                    "quota_buckets": [
                        {
                            "type": "credits",
                            "remaining_estimate": 321,
                            "confidence": 0.95,
                            "operations": ["text_to_image"],
                            "provider_models": ["connector-smoke-image"],
                        }
                    ],
                    "api_key": "sk-should-not-leak",
                }
            )
        elif self.path.startswith("/tasks/task_connector_async") or self.path.startswith("/v1/images/generations/task_connector_async"):
            self._json(
                {
                    "id": "task_connector_async",
                    "status": "completed",
                    "data": [{"b64_json": tiny_png_b64(), "mime_type": "image/png"}],
                }
            )
        elif self.path.startswith("/tasks/task_connector_custom"):
            self._json(
                {
                    "task": {"uid": "task_connector_custom", "state": "done"},
                    "result": {"assets": [{"image_url": f"http://127.0.0.1:{self.server.server_port}/media/custom.png"}]},
                }
            )
        else:
            self._json({"status": "ok"})

    def log_message(self, format: str, *args) -> None:
        return


def assert_ok(resp):
    if resp.status_code >= 400:
        raise AssertionError(f"{resp.status_code}: {resp.text}")
    return resp.json()


def upsert_provider(client: TestClient, port: int) -> None:
    payload = {
        "id": "connector_smoke",
        "name": "Connector Smoke",
        "adapter_type": "http_adapter",
        "status": "active",
        "base_config": {
            "base_url": f"http://127.0.0.1:{port}",
            "timeout_seconds": 10,
            "quota_endpoint": "/quota",
            "poll_endpoint": "/tasks/{task_id}",
            "poll_interval_seconds": 0.1,
            "task_id_paths": ["id", "task.uid"],
            "status_paths": ["status", "task.state"],
            "output_paths": ["data", "result.assets"],
        },
        "notes": "Local connector contract smoke test",
    }
    resp = client.post("/v1/admin/providers", headers=headers, json=payload)
    if resp.status_code == 409:
        assert_ok(client.patch("/v1/admin/providers/connector_smoke", headers=headers, json=payload))
    else:
        assert_ok(resp)


def upsert_account(client: TestClient) -> None:
    secret_payload = {
        "id": "secret_connector_smoke",
        "name": "Connector Smoke Secret",
        "value": CONNECTOR_SECRET_VALUE,
        "kind": "bearer_token",
        "provider_id": "connector_smoke",
        "account_id": "acct_connector_smoke",
        "metadata": {"source": "connector_smoke"},
    }
    secret_resp = client.post("/v1/admin/credential-secrets", headers=headers, json=secret_payload)
    if secret_resp.status_code == 409:
        secret = assert_ok(client.patch("/v1/admin/credential-secrets/secret_connector_smoke", headers=headers, json=secret_payload))
    else:
        secret = assert_ok(secret_resp)
    assert secret["ref"] == "secret://secret_connector_smoke" and "value" not in secret

    payload = {
        "id": "acct_connector_smoke",
        "provider_id": "connector_smoke",
        "label": "Connector Smoke Account",
        "credential_ref": "secret://secret_connector_smoke",
        "supported_operations": ["text_to_image"],
        "supported_provider_models": ["connector-smoke-image"],
        "quota_buckets": [{"type": "credits", "remaining_estimate": 1000, "confidence": 1}],
        "concurrency_limit": 5,
        "status": "active",
    }
    resp = client.post("/v1/admin/accounts", headers=headers, json=payload)
    if resp.status_code == 409:
        assert_ok(
            client.patch(
                "/v1/admin/accounts/acct_connector_smoke",
                headers=headers,
                json={k: v for k, v in payload.items() if k not in {"id", "provider_id"}},
            )
        )
    else:
        assert_ok(resp)


def upsert_mapping(client: TestClient, enabled: bool) -> None:
    payload = {
        "id": "map_connector_smoke_t2i",
        "logical_model": "t2i-fast",
        "provider_id": "connector_smoke",
        "provider_model": "connector-smoke-image",
        "operations": ["text_to_image"],
        "priority": 0,
        "weight": 1,
        "cost_score": 0.5,
        "speed_score": 0.9,
        "quality_score": 0.5,
        "reliability_score": 0.9,
        "enabled": enabled,
    }
    resp = client.post("/v1/admin/model-mappings", headers=headers, json=payload)
    if resp.status_code == 409:
        assert_ok(client.patch("/v1/admin/model-mappings/map_connector_smoke_t2i", headers=headers, json={"enabled": enabled, "priority": 0}))
    else:
        assert_ok(resp)


def main() -> None:
    server = HTTPServer(("127.0.0.1", 0), ConnectorHandler)
    port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with TestClient(app) as client:
            upsert_provider(client, port)
            upsert_account(client)
            upsert_mapping(client, True)
            result = assert_ok(
                client.post(
                    "/v1/images/generations",
                    headers=headers,
                    json={"model": "t2i-fast", "prompt": "connector smoke", "n": 1},
                )
            )
            assert result["data"][0]["asset_id"]
            job = assert_ok(client.get(f"/v1/media-jobs/{result['job_id']}", headers=headers))
            assert job["provider"] == "connector_smoke", job
            attempts = assert_ok(client.get(f"/v1/media-jobs/{result['job_id']}/attempts", headers=headers))
            assert attempts["data"] and attempts["data"][0]["request_snapshot"]["params"]["prompt"] == "connector smoke", attempts
            raw_response = attempts["data"][0]["raw_response"]
            assert raw_response["api_key"] == "[redacted]" and raw_response["token"] == "[redacted]" and raw_response["authorization"] == "[redacted]", raw_response
            assert raw_response["data"][0]["mime_type"] == "image/png", raw_response
            events = assert_ok(client.get(f"/v1/media-jobs/{result['job_id']}/events", headers=headers))
            sync_event_types = [item["event_type"] for item in events["data"]]
            assert "fetching_assets" in sync_event_types and "completed" in sync_event_types, events
            sync_attempt = assert_ok(client.get(f"/v1/media-jobs/{result['job_id']}/attempts", headers=headers))["data"][0]
            assert sync_attempt["status"] == "completed", sync_attempt

            async_result = assert_ok(
                client.post(
                    "/v1/images/generations",
                    headers=headers,
                    json={"model": "t2i-fast", "prompt": "connector async smoke", "n": 1},
                )
            )
            assert async_result["data"][0]["asset_id"]
            async_events = assert_ok(client.get(f"/v1/media-jobs/{async_result['job_id']}/events", headers=headers))
            async_event_types = [item["event_type"] for item in async_events["data"]]
            for expected in ["provider_queued", "polling", "fetching_assets", "completed"]:
                assert expected in async_event_types, async_events
            async_attempt = assert_ok(client.get(f"/v1/media-jobs/{async_result['job_id']}/attempts", headers=headers))["data"][0]
            assert async_attempt["status"] == "completed" and async_attempt["provider_task_id"] == "task_connector_async", async_attempt

            custom_result = assert_ok(
                client.post(
                    "/v1/images/generations",
                    headers=headers,
                    json={"model": "t2i-fast", "prompt": "connector custom path smoke", "n": 1},
                )
            )
            assert custom_result["data"][0]["asset_id"]
            custom_job = assert_ok(client.get(f"/v1/media-jobs/{custom_result['job_id']}", headers=headers))
            assert custom_job["provider"] == "connector_smoke", custom_job
            custom_events = assert_ok(client.get(f"/v1/media-jobs/{custom_result['job_id']}/events", headers=headers))
            custom_event_types = [item["event_type"] for item in custom_events["data"]]
            for expected in ["provider_queued", "polling", "fetching_assets", "completed"]:
                assert expected in custom_event_types, custom_events
            custom_attempt = assert_ok(client.get(f"/v1/media-jobs/{custom_result['job_id']}/attempts", headers=headers))["data"][0]
            assert custom_attempt["provider_task_id"] == "task_connector_custom" and custom_attempt["status"] == "completed", custom_attempt

            quota_sync = assert_ok(client.post("/v1/admin/accounts/acct_connector_smoke/sync-quota", headers=headers))
            assert quota_sync["status"] == "ok" and quota_sync["quota_buckets"][0]["remaining_estimate"] == 321.0, quota_sync
            assert quota_sync["provider_result"]["detail"]["api_key"] == "[redacted]", quota_sync
            synced_account = quota_sync["account"]
            assert synced_account["quota_buckets"][0]["remaining_estimate"] == 321.0 and synced_account["last_health_check_at"], synced_account
            provider_sync = assert_ok(client.post("/v1/admin/providers/connector_smoke/sync-quotas", headers=headers))
            assert provider_sync["total"] >= 1 and provider_sync["synced"] >= 1 and provider_sync["failed"] == 0, provider_sync
            upsert_mapping(client, False)
        print("connector smoke ok")
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
