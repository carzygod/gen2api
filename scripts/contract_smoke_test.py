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


def tiny_png_b64() -> str:
    image = Image.new("RGB", (32, 32), color=(84, 185, 129))
    buf = BytesIO()
    image.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


class ContractConnectorHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        body = json.dumps({"status": "ok", "contract": "ready"}).encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        length = int(self.headers.get("content-length") or "0")
        self.rfile.read(length)
        body = json.dumps({"id": "contract_task", "status": "completed", "data": [{"b64_json": tiny_png_b64(), "mime_type": "image/png"}]}).encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:
        return


def assert_ok(resp):
    if resp.status_code >= 400:
        raise AssertionError(f"{resp.status_code}: {resp.text}")
    return resp.json()


def upsert_connector(client: TestClient, port: int) -> None:
    provider = {
        "id": "contract_connector",
        "name": "Contract Connector",
        "adapter_type": "http_adapter",
        "status": "active",
        "base_config": {"base_url": f"http://127.0.0.1:{port}", "timeout_seconds": 10},
        "notes": "Provider contract smoke connector",
    }
    resp = client.post("/v1/admin/providers", headers=headers, json=provider)
    if resp.status_code == 409:
        assert_ok(client.patch("/v1/admin/providers/contract_connector", headers=headers, json=provider))
    else:
        assert_ok(resp)

    account = {
        "id": "acct_contract_connector",
        "provider_id": "contract_connector",
        "label": "Contract Connector Account",
        "credential_ref": "plain://contract",
        "supported_operations": ["text_to_image"],
        "supported_provider_models": ["contract-image"],
        "quota_buckets": [{"type": "credits", "remaining_estimate": 1000, "confidence": 1}],
        "concurrency_limit": 1,
        "status": "active",
    }
    resp = client.post("/v1/admin/accounts", headers=headers, json=account)
    if resp.status_code == 409:
        assert_ok(client.patch("/v1/admin/accounts/acct_contract_connector", headers=headers, json={k: v for k, v in account.items() if k not in {"id", "provider_id"}}))
    else:
        assert_ok(resp)

    mapping = {
        "id": "map_contract_connector_t2i",
        "logical_model": "t2i-fast",
        "provider_id": "contract_connector",
        "provider_model": "contract-image",
        "operations": ["text_to_image"],
        "priority": 99,
        "weight": 1,
        "cost_score": 0.5,
        "speed_score": 0.5,
        "quality_score": 0.5,
        "reliability_score": 0.9,
        "enabled": True,
    }
    resp = client.post("/v1/admin/model-mappings", headers=headers, json=mapping)
    if resp.status_code == 409:
        assert_ok(client.patch("/v1/admin/model-mappings/map_contract_connector_t2i", headers=headers, json={"enabled": True, "priority": 99}))
    else:
        assert_ok(resp)


def main() -> None:
    server = HTTPServer(("127.0.0.1", 0), ContractConnectorHandler)
    port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with TestClient(app) as client:
            mock_result = assert_ok(client.post("/v1/admin/providers/mock/contract-test", headers=headers, json={"operation": "text_to_image", "run_submit": True}))
            assert mock_result["status"] == "passed", mock_result
            assert any(check["name"] == "submit_assets" and check["status"] == "passed" for check in mock_result["checks"])
            assert any(check["name"] == "effective_capabilities_models" and check["status"] == "passed" for check in mock_result["checks"])
            assert any(check["name"] == "operation_profile_output_kind" and check["status"] == "passed" for check in mock_result["checks"])

            upsert_connector(client, port)
            connector_result = assert_ok(
                client.post(
                    "/v1/admin/providers/contract_connector/contract-test",
                    headers=headers,
                    json={"operation": "text_to_image", "provider_model": "contract-image", "run_submit": True},
                )
            )
            assert connector_result["status"] == "passed", connector_result
            assert any(check["name"] == "effective_provider_model_declared" and check["status"] == "passed" for check in connector_result["checks"])
            assert any(check["name"] == "operation_profile_max_input_assets" and check["status"] == "passed" for check in connector_result["checks"])
            matrix = assert_ok(client.get("/v1/admin/provider-contract-matrix", headers=headers))
            row = [item for item in matrix["data"] if item["provider_id"] == "contract_connector"][0]
            assert row["contract_status"] == "passed", row
            suite = assert_ok(
                client.post(
                    "/v1/admin/provider-contract-suite",
                    headers=headers,
                    json={"provider_ids": ["contract_connector"], "operations": ["text_to_image"], "active_only": False, "run_submit": True},
                )
            )
            assert suite["object"] == "media2api.provider_contract_suite" and suite["status"] == "passed", suite
            assert suite["summary"]["providers_selected"] == 1 and suite["summary"]["passed"] == 1 and suite["summary"]["failed"] == 0, suite
            results = assert_ok(client.get("/v1/admin/provider-contracts?provider_id=contract_connector", headers=headers))
            assert results["data"] and results["data"][0]["status"] == "passed"
            assert "media2api_provider_contract_results_total" in client.get("/metrics").text
            assert_ok(client.patch("/v1/admin/model-mappings/map_contract_connector_t2i", headers=headers, json={"enabled": False}))
        print("contract smoke ok")
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
