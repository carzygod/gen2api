from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path
from urllib.request import Request, urlopen

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from examples.reference_connector import create_server
from media2api.main import app


HEADERS = {"Authorization": "Bearer dev-admin-key"}
CONNECTOR_TOKEN = "reference-connector-smoke-token"


def assert_ok(resp):
    if resp.status_code >= 400:
        raise AssertionError(f"{resp.status_code}: {resp.text}")
    return resp.json()


def direct_json(method: str, url: str, payload: dict | None = None) -> dict:
    body = json.dumps(payload or {}).encode("utf-8") if payload is not None else None
    req = Request(url, data=body, method=method, headers={"Authorization": f"Bearer {CONNECTOR_TOKEN}", "Content-Type": "application/json"})
    with urlopen(req, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def upsert_reference_provider(client: TestClient, provider_id: str, port: int) -> None:
    payload = {
        "id": provider_id,
        "name": "Reference Connector Smoke",
        "adapter_type": "http_adapter",
        "status": "active",
        "base_config": {
            "base_url": f"http://127.0.0.1:{port}",
            "health_endpoint": "/health",
            "quota_endpoint": "/quota?operation=text_to_image",
            "poll_endpoint": "/tasks/{task_id}",
            "cancel_endpoint": "/tasks/{task_id}/cancel",
            "poll_interval_seconds": 0.05,
            "poll_timeout_seconds": 5,
            "timeout_seconds": 10,
            "task_id_paths": ["id"],
            "status_paths": ["status"],
            "output_paths": ["data", "assets"],
        },
        "notes": "Smoke test for examples/reference_connector.py",
    }
    response = client.post("/v1/admin/providers", headers=HEADERS, json=payload)
    if response.status_code == 409:
        assert_ok(client.patch(f"/v1/admin/providers/{provider_id}", headers=HEADERS, json=payload))
    else:
        assert_ok(response)


def upsert_reference_secret(client: TestClient, provider_id: str, account_id: str, secret_id: str) -> None:
    payload = {
        "id": secret_id,
        "name": "Reference Connector Smoke Secret",
        "value": CONNECTOR_TOKEN,
        "kind": "bearer_token",
        "provider_id": provider_id,
        "account_id": account_id,
        "metadata": {"source": "reference_connector_smoke"},
    }
    response = client.post("/v1/admin/credential-secrets", headers=HEADERS, json=payload)
    if response.status_code == 409:
        secret = assert_ok(client.patch(f"/v1/admin/credential-secrets/{secret_id}", headers=HEADERS, json=payload))
    else:
        secret = assert_ok(response)
    assert secret["ref"] == f"secret://{secret_id}" and "value" not in secret, secret


def upsert_reference_account(client: TestClient, provider_id: str, account_id: str, secret_id: str) -> None:
    payload = {
        "id": account_id,
        "provider_id": provider_id,
        "label": "Reference Connector Smoke Account",
        "credential_ref": f"secret://{secret_id}",
        "supported_operations": ["text_to_image"],
        "supported_provider_models": ["reference-image"],
        "quota_buckets": [{"type": "credits", "remaining_estimate": 1000, "confidence": 1.0}],
        "concurrency_limit": 3,
        "status": "active",
    }
    response = client.post("/v1/admin/accounts", headers=HEADERS, json=payload)
    if response.status_code == 409:
        assert_ok(
            client.patch(
                f"/v1/admin/accounts/{account_id}",
                headers=HEADERS,
                json={k: v for k, v in payload.items() if k not in {"id", "provider_id"}},
            )
        )
    else:
        assert_ok(response)


def upsert_reference_mapping(client: TestClient, provider_id: str, mapping_id: str, enabled: bool = True) -> None:
    payload = {
        "id": mapping_id,
        "logical_model": "t2i-fast",
        "provider_id": provider_id,
        "provider_model": "reference-image",
        "operations": ["text_to_image"],
        "priority": 0,
        "weight": 1,
        "cost_score": 0.5,
        "speed_score": 0.9,
        "quality_score": 0.5,
        "reliability_score": 0.95,
        "enabled": enabled,
    }
    response = client.post("/v1/admin/model-mappings", headers=HEADERS, json=payload)
    if response.status_code == 409:
        assert_ok(client.patch(f"/v1/admin/model-mappings/{mapping_id}", headers=HEADERS, json={"enabled": enabled, "priority": 0}))
    else:
        assert_ok(response)


def main() -> None:
    server = create_server("127.0.0.1", 0, CONNECTOR_TOKEN)
    port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    suffix = str(int(time.time() * 1000))
    provider_id = f"reference_connector_{suffix}"
    account_id = f"acct_reference_connector_{suffix}"
    secret_id = f"secret_reference_connector_{suffix}"
    mapping_id = f"map_reference_connector_{suffix}"
    try:
        health = direct_json("GET", f"http://127.0.0.1:{port}/health")
        assert health["status"] == "ok", health
        capabilities = direct_json("GET", f"http://127.0.0.1:{port}/capabilities")
        assert "text_to_image" in capabilities["operations"], capabilities
        cancel = direct_json("POST", f"http://127.0.0.1:{port}/tasks/direct_cancel/cancel", {})
        assert cancel["status"] == "cancelled", cancel

        with TestClient(app) as client:
            upsert_reference_provider(client, provider_id, port)
            upsert_reference_secret(client, provider_id, account_id, secret_id)
            upsert_reference_account(client, provider_id, account_id, secret_id)

            initial_capability = assert_ok(client.get(f"/v1/admin/providers/{provider_id}/capabilities", headers=HEADERS))
            assert "reference-image" not in initial_capability["models"], initial_capability
            capability_sync = assert_ok(client.post(f"/v1/admin/providers/{provider_id}/sync-capabilities", headers=HEADERS, json={}))
            assert capability_sync["status"] == "ok", capability_sync
            assert "reference-image" in capability_sync["capabilities"]["models"], capability_sync
            assert "text_to_image" in capability_sync["capabilities"]["operations"], capability_sync

            upsert_reference_mapping(client, provider_id, mapping_id, enabled=True)

            health_check = assert_ok(client.post(f"/v1/admin/providers/{provider_id}/health-check", headers=HEADERS))
            assert health_check["status"] == "ok", health_check
            capability = assert_ok(client.get(f"/v1/admin/providers/{provider_id}/capabilities", headers=HEADERS))
            assert "reference-image" in capability["models"] and "text_to_image" in capability["operations"], capability

            sync_result = assert_ok(
                client.post(
                    "/v1/images/generations",
                    headers=HEADERS,
                    json={"model": "t2i-fast", "prompt": "reference connector sync", "n": 1, "provider_preference": [provider_id]},
                )
            )
            assert sync_result["data"][0]["asset_id"], sync_result
            sync_job = assert_ok(client.get(f"/v1/media-jobs/{sync_result['job_id']}", headers=HEADERS))
            assert sync_job["provider"] == provider_id and sync_job["account_id"] == account_id, sync_job

            async_result = assert_ok(
                client.post(
                    "/v1/images/generations",
                    headers=HEADERS,
                    json={"model": "t2i-fast", "prompt": "reference connector async", "n": 1, "provider_preference": [provider_id]},
                )
            )
            async_job = assert_ok(client.get(f"/v1/media-jobs/{async_result['job_id']}", headers=HEADERS))
            assert async_job["status"] == "completed" and async_job["provider"] == provider_id, async_job
            events = assert_ok(client.get(f"/v1/media-jobs/{async_result['job_id']}/events", headers=HEADERS))
            event_types = [item["event_type"] for item in events["data"]]
            for expected in ["provider_queued", "polling", "fetching_assets", "completed"]:
                assert expected in event_types, events

            quota = assert_ok(client.post(f"/v1/admin/accounts/{account_id}/sync-quota", headers=HEADERS))
            assert quota["status"] == "ok" and quota["quota_buckets"][0]["remaining_estimate"] == 1000.0, quota

            contract = assert_ok(
                client.post(
                    f"/v1/admin/providers/{provider_id}/contract-test",
                    headers=HEADERS,
                    json={"operation": "text_to_image", "provider_model": "reference-image", "run_submit": True},
                )
            )
            assert contract["status"] == "passed", contract
            upsert_reference_mapping(client, provider_id, mapping_id, enabled=False)
        print("reference connector smoke ok")
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
