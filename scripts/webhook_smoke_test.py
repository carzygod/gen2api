from __future__ import annotations

import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from media2api.config import settings
from media2api.main import app


headers = {"Authorization": "Bearer dev-admin-key"}
received: list[dict] = []
attempts_by_path: dict[str, int] = {}


class WebhookHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        attempts_by_path[self.path] = attempts_by_path.get(self.path, 0) + 1
        length = int(self.headers.get("content-length") or "0")
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        if self.path == "/flaky" and attempts_by_path[self.path] == 1:
            self.send_response(500)
            self.end_headers()
            return
        received.append(payload)
        self.send_response(204)
        self.end_headers()

    def log_message(self, format: str, *args) -> None:
        return


def assert_ok(resp):
    if resp.status_code >= 400:
        raise AssertionError(f"{resp.status_code}: {resp.text}")
    return resp.json()


def main() -> None:
    server = HTTPServer(("127.0.0.1", 0), WebhookHandler)
    port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with TestClient(app) as client:
            original_allowed_hosts = set(settings.webhook_url_allowed_hosts)
            original_allow_private = settings.webhook_url_allow_private
            settings.webhook_url_allowed_hosts = set()
            settings.webhook_url_allow_private = False
            try:
                blocked = assert_ok(
                    client.post(
                        "/v1/media-jobs",
                        headers=headers,
                        json={
                            "operation": "text_to_image",
                            "model": "t2i-fast",
                            "prompt": "webhook private target smoke",
                            "params": {"webhook": f"http://127.0.0.1:{port}/blocked"},
                            "wait": True,
                        },
                    )
                )
                assert blocked["status"] == "completed", blocked
                deliveries = assert_ok(client.get("/v1/webhooks", headers=headers))
                blocked_delivery = next((item for item in deliveries["data"] if item["job_id"] == blocked["id"]), None)
                assert blocked_delivery and blocked_delivery["status"] == "failed", blocked_delivery
                assert blocked_delivery["last_error"] == "WEBHOOK_URL_PRIVATE_ADDRESS_BLOCKED", blocked_delivery
                assert not received, received

                settings.webhook_url_allowed_hosts = {"127.0.0.1"}
                result = assert_ok(
                    client.post(
                        "/v1/media-jobs",
                        headers=headers,
                        json={
                            "operation": "text_to_video",
                            "model": "t2v-general",
                            "prompt": "webhook smoke",
                            "params": {"duration": 3, "webhook": f"http://127.0.0.1:{port}/hook"},
                            "wait": True,
                        },
                    )
                )
                assert result["status"] == "completed", result
                for _ in range(10):
                    if received:
                        break
                    time.sleep(0.1)
                assert received and received[0]["job"]["id"] == result["id"], received
                deliveries = assert_ok(client.get("/v1/webhooks", headers=headers))
                assert any(item["job_id"] == result["id"] and item["status"] == "delivered" for item in deliveries["data"])
                flaky = assert_ok(
                    client.post(
                        "/v1/media-jobs",
                        headers=headers,
                        json={
                            "operation": "text_to_image",
                            "model": "t2i-fast",
                            "prompt": "webhook retry smoke",
                            "params": {"webhook": f"http://127.0.0.1:{port}/flaky"},
                            "wait": True,
                        },
                    )
                )
                assert flaky["status"] == "completed", flaky
                retry_delivery = None
                for _ in range(10):
                    deliveries = assert_ok(client.get("/v1/webhooks", headers=headers))
                    retry_delivery = next((item for item in deliveries["data"] if item["job_id"] == flaky["id"]), None)
                    if retry_delivery and retry_delivery["status"] == "delivered":
                        break
                    time.sleep(0.1)
                assert retry_delivery and retry_delivery["status"] == "delivered" and retry_delivery["attempts"] >= 2, retry_delivery
                admin_deliveries = assert_ok(client.get(f"/v1/admin/webhooks?job_id={flaky['id']}", headers=headers))
                assert admin_deliveries["data"] and admin_deliveries["data"][0]["attempts"] >= 2, admin_deliveries
            finally:
                settings.webhook_url_allowed_hosts = original_allowed_hosts
                settings.webhook_url_allow_private = original_allow_private
        print("webhook smoke ok")
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
