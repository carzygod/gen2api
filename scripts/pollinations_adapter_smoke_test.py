from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from media2api.main import app


HEADERS = {"Authorization": "Bearer dev-admin-key"}
POLLINATIONS_KEY = "polli-test-key"


def png_bytes(color: tuple[int, int, int] = (52, 123, 214)) -> bytes:
    image = Image.new("RGB", (48, 32), color=color)
    buf = BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


class FakePollinationsHandler(BaseHTTPRequestHandler):
    uploaded = 0
    image_calls = 0
    upload_calls = 0
    last_query: dict[str, list[str]] = {}

    def _authorized(self) -> bool:
        return self.headers.get("authorization") == f"Bearer {POLLINATIONS_KEY}"

    def _write_json(self, status: int, body: dict) -> None:
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/v1/models":
            if not self._authorized():
                self._write_json(401, {"error": "unauthorized"})
                return
            self._write_json(200, {"data": [{"id": "seedream"}, {"id": "gpt-image-2"}]})
            return
        if parsed.path.startswith("/image/"):
            if not self._authorized():
                self._write_json(401, {"error": "unauthorized"})
                return
            FakePollinationsHandler.image_calls += 1
            FakePollinationsHandler.last_query = parse_qs(parsed.query)
            data = png_bytes((91, 172, 99))
            self.send_response(200)
            self.send_header("content-type", "image/png")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if parsed.path == "/media/uploaded.png":
            data = png_bytes((220, 188, 72))
            self.send_response(200)
            self.send_header("content-type", "image/png")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self._write_json(404, {"error": "not_found"})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/upload":
            if not self._authorized():
                self._write_json(401, {"error": "unauthorized"})
                return
            FakePollinationsHandler.upload_calls += 1
            _ = self.rfile.read(int(self.headers.get("content-length") or 0))
            host = self.headers.get("host", "127.0.0.1")
            self._write_json(200, {"url": f"http://{host}/media/uploaded.png"})
            return
        self._write_json(404, {"error": "not_found"})

    def log_message(self, format: str, *args) -> None:
        return


def assert_ok(resp):
    if resp.status_code >= 400:
        raise AssertionError(f"{resp.status_code}: {resp.text}")
    return resp.json()


def configure_pollinations(client: TestClient, base_url: str) -> None:
    provider_payload = {
        "id": "pollinations",
        "name": "Pollinations Smoke",
        "adapter_type": "aggregator_adapter",
        "status": "active",
        "base_config": {"base_url": base_url, "credential_ref": "secret://secret_pollinations_smoke", "timeout_seconds": 20},
    }
    resp = client.post("/v1/admin/providers", headers=HEADERS, json=provider_payload)
    if resp.status_code == 409:
        assert_ok(client.patch("/v1/admin/providers/pollinations", headers=HEADERS, json=provider_payload))
    else:
        assert_ok(resp)

    account_payload = {
        "id": "acct_pollinations_smoke",
        "provider_id": "pollinations",
        "label": "Pollinations Smoke Account",
        "credential_ref": f"plain://{POLLINATIONS_KEY}",
        "credential_secret_id": "secret_pollinations_smoke",
        "supported_operations": ["text_to_image", "image_to_image"],
        "supported_provider_models": ["seedream"],
        "quota_buckets": [{"type": "external_account", "remaining_estimate": 100, "confidence": 1}],
        "concurrency_limit": 2,
        "status": "active",
    }
    resp = client.post("/v1/admin/accounts", headers=HEADERS, json=account_payload)
    if resp.status_code == 409:
        assert_ok(client.patch("/v1/admin/accounts/acct_pollinations_smoke", headers=HEADERS, json={**account_payload, "health_score": 1.0, "failure_score": 0.0}))
    else:
        assert_ok(resp)

    for payload in [
        {
            "id": "map_pollinations_smoke_t2i",
            "logical_model": "t2i-fast",
            "provider_id": "pollinations",
            "provider_model": "seedream",
            "operations": ["text_to_image"],
            "priority": 0,
            "weight": 1,
            "cost_score": 0.7,
            "speed_score": 0.7,
            "quality_score": 0.75,
            "reliability_score": 0.8,
            "enabled": True,
        },
        {
            "id": "map_pollinations_smoke_i2i",
            "logical_model": "image-variation",
            "provider_id": "pollinations",
            "provider_model": "seedream",
            "operations": ["image_to_image"],
            "priority": 0,
            "weight": 1,
            "cost_score": 0.7,
            "speed_score": 0.7,
            "quality_score": 0.75,
            "reliability_score": 0.8,
            "enabled": True,
        },
    ]:
        resp = client.post("/v1/admin/model-mappings", headers=HEADERS, json=payload)
        if resp.status_code == 409:
            assert_ok(client.patch(f"/v1/admin/model-mappings/{payload['id']}", headers=HEADERS, json=payload))
        else:
            assert_ok(resp)


def cleanup_pollinations(client: TestClient) -> None:
    for mapping_id in ["map_pollinations_smoke_t2i", "map_pollinations_smoke_i2i"]:
        client.patch(f"/v1/admin/model-mappings/{mapping_id}", headers=HEADERS, json={"enabled": False})
    client.patch("/v1/admin/accounts/acct_pollinations_smoke", headers=HEADERS, json={"status": "disabled"})
    client.patch("/v1/admin/providers/pollinations", headers=HEADERS, json={"status": "disabled"})


def main() -> None:
    server = HTTPServer(("127.0.0.1", 0), FakePollinationsHandler)
    port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with TestClient(app) as client:
            try:
                configure_pollinations(client, f"http://127.0.0.1:{port}")
                health = assert_ok(client.post("/v1/admin/providers/pollinations/health-check", headers=HEADERS))
                assert health["status"] == "ok" and health["detail"]["model_count"] >= 1, health

                image = assert_ok(
                    client.post(
                        "/v1/images/generations",
                        headers=HEADERS,
                        json={
                            "model": "t2i-fast",
                            "prompt": "pollinations adapter smoke image",
                            "provider_preference": ["pollinations"],
                            "providers": ["pollinations"],
                            "response_format": "url",
                        },
                    )
                )
                assert image["data"][0]["asset_id"] and image["job_id"], image
                image_job = assert_ok(client.get(f"/v1/media-jobs/{image['job_id']}", headers=HEADERS))
                assert image_job["provider"] == "pollinations" and image_job["outputs"][0]["source"] == "provider_result", image_job

                uploaded = assert_ok(
                    client.post(
                        "/v1/assets",
                        headers=HEADERS,
                        json={
                            "b64_json": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGNkYPgPAAEDAQC2dH0NAAAAAElFTkSuQmCC",
                            "filename": "reference.png",
                            "kind": "image",
                            "purpose": "reference",
                            "mime_type": "image/png",
                        },
                    )
                )
                i2i = assert_ok(
                    client.post(
                        "/v1/media-jobs",
                        headers=HEADERS,
                        json={
                            "operation": "image_to_image",
                            "model": "image-variation",
                            "prompt": "pollinations adapter smoke reference",
                            "image": uploaded["id"],
                            "provider_preference": ["pollinations"],
                            "providers": ["pollinations"],
                            "wait": True,
                        },
                    )
                )
                assert i2i["status"] == "completed" and i2i["provider"] == "pollinations", i2i
                assert FakePollinationsHandler.upload_calls >= 1, FakePollinationsHandler.upload_calls
                assert FakePollinationsHandler.last_query.get("image"), FakePollinationsHandler.last_query

                account = assert_ok(client.get("/v1/accounts", headers=HEADERS))
                polli = [item for item in account["data"] if item["id"] == "acct_pollinations_smoke"][0]
                assert polli["credential_ref"] == "secret://secret_pollinations_smoke", polli
                assert polli["credential_ref_type"] == "secret", polli

                external_acceptance = assert_ok(
                    client.post(
                        "/v1/admin/provider-templates/pollinations/external-acceptance",
                        headers=HEADERS,
                        json={
                            "base_url": f"http://127.0.0.1:{port}",
                            "credential_value": json.dumps({"POLLINATIONS_KEY": POLLINATIONS_KEY}),
                            "credential_secret_id": "secret_pollinations_external_acceptance",
                            "operations": ["text_to_image"],
                            "run_samples": True,
                            "max_samples": 1,
                            "run_health_check": True,
                            "run_contract_tests": True,
                            "run_quota_sync": True,
                            "require_production_ready": False,
                        },
                    )
                )
                assert external_acceptance["status"] == "passed", external_acceptance
                assert external_acceptance["samples"] and external_acceptance["samples"][0]["ok"] is True, external_acceptance
                assert external_acceptance["samples"][0]["output_assets"][0]["download_ok"] is True, external_acceptance
                print("pollinations adapter smoke ok")
            finally:
                cleanup_pollinations(client)
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    main()
