from __future__ import annotations

import base64
from io import BytesIO
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen

from fastapi.testclient import TestClient
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from media2api.main import app


headers = {"Authorization": "Bearer dev-admin-key"}
temp_media_hits = 0


def tiny_png() -> bytes:
    image = Image.new("RGB", (32, 32), color=(219, 103, 72))
    buf = BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def tiny_png_b64() -> str:
    return base64.b64encode(tiny_png()).decode("ascii")


class ResilienceHandler(BaseHTTPRequestHandler):
    def _json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        length = int(self.headers.get("content-length") or "0")
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            payload = {}
        prompt = str(payload.get("prompt") or "")
        if prompt == "resilience timeout":
            self._json({"id": "task_resilience_timeout", "status": "queued"})
            return
        if prompt == "resilience temp url":
            self._json(
                {
                    "status": "completed",
                    "data": [{"image_url": f"http://127.0.0.1:{self.server.server_port}/media/temp-once.png"}],
                }
            )
            return
        self._json({"status": "completed", "data": [{"b64_json": tiny_png_b64(), "mime_type": "image/png"}]})

    def do_GET(self) -> None:
        global temp_media_hits
        if self.path.startswith("/tasks/task_resilience_timeout"):
            self._json({"id": "task_resilience_timeout", "status": "queued"})
            return
        if self.path.startswith("/media/temp-once.png"):
            temp_media_hits += 1
            if temp_media_hits > 1:
                self._json({"error": "temporary url expired"}, status=410)
                return
            body = tiny_png()
            self.send_response(200)
            self.send_header("content-type", "image/png")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self._json({"status": "ok"})

    def log_message(self, format: str, *args) -> None:
        return


def assert_ok(resp):
    if resp.status_code >= 400:
        raise AssertionError(f"{resp.status_code}: {resp.text}")
    return resp.json()


def upsert_provider(client: TestClient, provider_id: str, port: int, extra_config: dict | None = None) -> None:
    config = {
        "base_url": f"http://127.0.0.1:{port}",
        "timeout_seconds": 10,
        "poll_endpoint": "/tasks/{task_id}",
        "poll_interval_seconds": 0.05,
        "task_id_paths": ["id"],
        "status_paths": ["status"],
        "output_paths": ["data"],
    }
    if extra_config:
        config.update(extra_config)
    payload = {
        "id": provider_id,
        "name": provider_id,
        "adapter_type": "http_adapter",
        "status": "active",
        "base_config": config,
        "notes": "Resilience smoke test provider",
    }
    resp = client.post("/v1/admin/providers", headers=headers, json=payload)
    if resp.status_code == 409:
        assert_ok(client.patch(f"/v1/admin/providers/{provider_id}", headers=headers, json=payload))
    else:
        assert_ok(resp)


def upsert_account(client: TestClient, provider_id: str, account_id: str, provider_model: str) -> None:
    payload = {
        "id": account_id,
        "provider_id": provider_id,
        "label": account_id,
        "credential_ref": "plain://resilience-smoke",
        "supported_operations": ["text_to_image"],
        "supported_provider_models": [provider_model],
        "quota_buckets": [{"type": "credits", "remaining_estimate": 1000, "confidence": 1}],
        "concurrency_limit": 1,
        "status": "active",
    }
    resp = client.post("/v1/admin/accounts", headers=headers, json=payload)
    if resp.status_code == 409:
        assert_ok(
            client.patch(
                f"/v1/admin/accounts/{account_id}",
                headers=headers,
                json={**{k: v for k, v in payload.items() if k not in {"id", "provider_id"}}, "health_score": 1.0, "failure_score": 0.0, "status": "active"},
            )
        )
    else:
        assert_ok(resp)
    breaker_id = f"cb_account_{account_id}"
    resp = client.patch(f"/v1/admin/circuit-breakers/{breaker_id}", headers=headers, json={"status": "closed", "clear_block_until": True})
    if resp.status_code not in {200, 404}:
        raise AssertionError(resp.text)


def upsert_mapping(client: TestClient, provider_id: str, provider_model: str, priority: int, enabled: bool = True) -> None:
    mapping_id = f"map_{provider_id}_t2i"
    payload = {
        "id": mapping_id,
        "logical_model": "t2i-fast",
        "provider_id": provider_id,
        "provider_model": provider_model,
        "operations": ["text_to_image"],
        "priority": priority,
        "weight": 1,
        "cost_score": 0.2,
        "speed_score": 0.2,
        "quality_score": 0.2,
        "reliability_score": 0.8,
        "enabled": enabled,
    }
    resp = client.post("/v1/admin/model-mappings", headers=headers, json=payload)
    if resp.status_code == 409:
        assert_ok(client.patch(f"/v1/admin/model-mappings/{mapping_id}", headers=headers, json={"enabled": enabled, "priority": priority, "reliability_score": 0.8}))
    else:
        assert_ok(resp)


def main() -> None:
    global temp_media_hits
    server = HTTPServer(("127.0.0.1", 0), ResilienceHandler)
    port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with TestClient(app) as client:
            upsert_provider(client, "resilience_timeout", port, {"poll_timeout_seconds": 0.18})
            upsert_account(client, "resilience_timeout", "acct_resilience_timeout", "resilience-timeout-image")
            upsert_mapping(client, "resilience_timeout", "resilience-timeout-image", priority=0)

            result = assert_ok(
                client.post(
                    "/v1/images/generations",
                    headers=headers,
                    json={
                        "model": "t2i-fast",
                        "prompt": "resilience timeout",
                        "n": 1,
                        "providers": ["resilience_timeout", "mock"],
                        "provider_preference": ["resilience_timeout"],
                    },
                )
            )
            assert result["data"][0]["asset_id"], result
            job = assert_ok(client.get(f"/v1/media-jobs/{result['job_id']}", headers=headers))
            assert job["status"] == "completed" and job["provider"] == "mock", job
            attempts = assert_ok(client.get(f"/v1/media-jobs/{job['id']}/attempts", headers=headers))
            timeout_attempt = [item for item in attempts["data"] if item["provider_id"] == "resilience_timeout"]
            assert timeout_attempt and timeout_attempt[0]["status"] == "failed" and timeout_attempt[0]["error_code"] == "PROVIDER_TIMEOUT", attempts
            events = assert_ok(client.get(f"/v1/media-jobs/{job['id']}/events", headers=headers))
            assert any(item["event_type"] == "fallback_queued" and item["metadata"].get("error_code") == "PROVIDER_TIMEOUT" for item in events["data"]), events
            metrics = client.get("/metrics")
            assert metrics.status_code == 200 and 'media2api_provider_poll_timeout_total{provider="resilience_timeout"' in metrics.text, metrics.text

            upsert_provider(client, "resilience_temp_url", port)
            upsert_account(client, "resilience_temp_url", "acct_resilience_temp_url", "resilience-temp-url-image")
            upsert_mapping(client, "resilience_temp_url", "resilience-temp-url-image", priority=0)
            temp_media_hits = 0
            temp_result = assert_ok(
                client.post(
                    "/v1/images/generations",
                    headers=headers,
                    json={
                        "model": "t2i-fast",
                        "prompt": "resilience temp url",
                        "n": 1,
                        "providers": ["resilience_temp_url"],
                        "provider_preference": ["resilience_temp_url"],
                    },
                )
            )
            temp_asset_id = temp_result["data"][0]["asset_id"]
            temp_job = assert_ok(client.get(f"/v1/media-jobs/{temp_result['job_id']}", headers=headers))
            assert temp_job["provider"] == "resilience_temp_url" and temp_job["outputs"][0]["source"] == "provider_result", temp_job
            expired_source = urlopen(f"http://127.0.0.1:{port}/media/temp-once.png")
            raise AssertionError(f"temporary source unexpectedly still served: {expired_source.status}")
    except Exception as exc:
        if "temporary source unexpectedly" in str(exc):
            raise
        # urlopen raises HTTPError for the expected 410 once the connector URL has expired.
        if exc.__class__.__name__ != "HTTPError":
            raise
        with TestClient(app) as client:
            asset = assert_ok(client.get(f"/v1/admin/assets/{temp_asset_id}", headers=headers))
            parsed = urlparse(asset["url"])
            content = client.get(f"{parsed.path}?{parsed.query}")
            assert content.status_code == 200 and content.content.startswith(b"\x89PNG"), content.status_code
            upsert_mapping(client, "resilience_timeout", "resilience-timeout-image", priority=0, enabled=False)
            upsert_mapping(client, "resilience_temp_url", "resilience-temp-url-image", priority=0, enabled=False)
            print("resilience smoke ok")
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
