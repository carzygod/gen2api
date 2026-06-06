from __future__ import annotations

import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from media2api import models
from media2api.database import SessionLocal
from media2api.main import app
from media2api.services_core import JobRuntime
from media2api.utils import dumps


headers = {"Authorization": "Bearer dev-admin-key"}


class RateLimitHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get("content-length") or "0")
        self.rfile.read(length)
        body = json.dumps({"error": "rate limited"}).encode("utf-8")
        self.send_response(429)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        body = json.dumps({"status": "ok"}).encode("utf-8")
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


def upsert_provider(client: TestClient, port: int) -> None:
    payload = {
        "id": "routing_rate_limit",
        "name": "Routing Rate Limit",
        "adapter_type": "http_adapter",
        "status": "active",
        "base_config": {"base_url": f"http://127.0.0.1:{port}", "timeout_seconds": 10},
        "notes": "Routing fallback smoke test provider",
    }
    resp = client.post("/v1/admin/providers", headers=headers, json=payload)
    if resp.status_code == 409:
        assert_ok(client.patch("/v1/admin/providers/routing_rate_limit", headers=headers, json=payload))
    else:
        assert_ok(resp)


def upsert_account(client: TestClient) -> None:
    payload = {
        "id": "acct_routing_rate_limit",
        "provider_id": "routing_rate_limit",
        "label": "Routing Rate Limit Account",
        "credential_ref": "plain://smoke",
        "supported_operations": ["text_to_image"],
        "supported_provider_models": ["routing-rate-limit-image"],
        "quota_buckets": [{"type": "credits", "remaining_estimate": 1000, "confidence": 1}],
        "concurrency_limit": 1,
        "status": "active",
    }
    resp = client.post("/v1/admin/accounts", headers=headers, json=payload)
    if resp.status_code == 409:
        assert_ok(
            client.patch(
                "/v1/admin/accounts/acct_routing_rate_limit",
                headers=headers,
                json={
                    **{k: v for k, v in payload.items() if k not in {"id", "provider_id"}},
                    "health_score": 1.0,
                    "failure_score": 0.0,
                    "status": "active",
                },
            )
        )
    else:
        assert_ok(resp)


def reset_governance(client: TestClient) -> None:
    for breaker_id in ["cb_account_acct_routing_rate_limit", "cb_provider_routing_rate_limit"]:
        resp = client.patch(f"/v1/admin/circuit-breakers/{breaker_id}", headers=headers, json={"status": "closed", "clear_block_until": True})
        if resp.status_code not in {200, 404}:
            raise AssertionError(f"{resp.status_code}: {resp.text}")


def upsert_mapping(client: TestClient, enabled: bool) -> None:
    payload = {
        "id": "map_routing_rate_limit_t2i",
        "logical_model": "t2i-fast",
        "provider_id": "routing_rate_limit",
        "provider_model": "routing-rate-limit-image",
        "operations": ["text_to_image"],
        "priority": 0,
        "weight": 1,
        "cost_score": 0.1,
        "speed_score": 0.1,
        "quality_score": 0.1,
        "reliability_score": 0.3,
        "enabled": enabled,
    }
    resp = client.post("/v1/admin/model-mappings", headers=headers, json=payload)
    if resp.status_code == 409:
        assert_ok(client.patch("/v1/admin/model-mappings/map_routing_rate_limit_t2i", headers=headers, json={"enabled": enabled, "priority": 0, "reliability_score": 0.3}))
    else:
        assert_ok(resp)


def upsert_quota_empty_provider(client: TestClient, port: int) -> None:
    provider = {
        "id": "routing_quota_empty",
        "name": "Routing Quota Empty",
        "adapter_type": "http_adapter",
        "status": "active",
        "base_config": {"base_url": f"http://127.0.0.1:{port}", "timeout_seconds": 10},
        "notes": "Routing quota exhaustion smoke test provider",
    }
    resp = client.post("/v1/admin/providers", headers=headers, json=provider)
    if resp.status_code == 409:
        assert_ok(client.patch("/v1/admin/providers/routing_quota_empty", headers=headers, json=provider))
    else:
        assert_ok(resp)

    account = {
        "id": "acct_routing_quota_empty",
        "provider_id": "routing_quota_empty",
        "label": "Routing Quota Empty Account",
        "credential_ref": "plain://smoke",
        "supported_operations": ["text_to_image"],
        "supported_provider_models": ["routing-quota-empty-image"],
        "quota_buckets": [{"type": "credits", "operation": "text_to_image", "remaining_estimate": 0, "confidence": 1}],
        "concurrency_limit": 1,
        "status": "active",
    }
    resp = client.post("/v1/admin/accounts", headers=headers, json=account)
    if resp.status_code == 409:
        assert_ok(
            client.patch(
                "/v1/admin/accounts/acct_routing_quota_empty",
                headers=headers,
                json={
                    **{k: v for k, v in account.items() if k not in {"id", "provider_id"}},
                    "health_score": 1.0,
                    "failure_score": 0.0,
                    "status": "active",
                },
            )
        )
    else:
        assert_ok(resp)

    mapping = {
        "id": "map_routing_quota_empty_t2i",
        "logical_model": "t2i-fast",
        "provider_id": "routing_quota_empty",
        "provider_model": "routing-quota-empty-image",
        "operations": ["text_to_image"],
        "priority": 0,
        "weight": 1,
        "cost_score": 1,
        "speed_score": 1,
        "quality_score": 1,
        "reliability_score": 1,
        "enabled": True,
    }
    resp = client.post("/v1/admin/model-mappings", headers=headers, json=mapping)
    if resp.status_code == 409:
        assert_ok(client.patch("/v1/admin/model-mappings/map_routing_quota_empty_t2i", headers=headers, json={"enabled": True, "priority": 0}))
    else:
        assert_ok(resp)


def upsert_concurrency_guard(client: TestClient) -> None:
    provider = {
        "id": "concurrency_guard",
        "name": "Concurrency Guard",
        "adapter_type": "http_adapter",
        "status": "active",
        "base_config": {"base_url": "http://127.0.0.1:1"},
        "notes": "Scheduler concurrency guard smoke",
    }
    resp = client.post("/v1/admin/providers", headers=headers, json=provider)
    if resp.status_code == 409:
        assert_ok(client.patch("/v1/admin/providers/concurrency_guard", headers=headers, json=provider))
    else:
        assert_ok(resp)

    account = {
        "id": "acct_concurrency_guard",
        "provider_id": "concurrency_guard",
        "label": "Concurrency Guard Account",
        "credential_ref": "plain://guard",
        "supported_operations": ["text_to_image"],
        "supported_provider_models": ["concurrency-guard-image"],
        "quota_buckets": [{"type": "credits", "remaining_estimate": 100, "confidence": 1}],
        "concurrency_limit": 1,
        "status": "active",
    }
    resp = client.post("/v1/admin/accounts", headers=headers, json=account)
    if resp.status_code == 409:
        assert_ok(
            client.patch(
                "/v1/admin/accounts/acct_concurrency_guard",
                headers=headers,
                json={
                    **{k: v for k, v in account.items() if k not in {"id", "provider_id"}},
                    "current_leases": 0,
                    "health_score": 1.0,
                    "failure_score": 0.0,
                    "status": "active",
                },
            )
        )
    else:
        assert_ok(resp)

    mapping = {
        "id": "map_concurrency_guard_t2i",
        "logical_model": "t2i-fast",
        "provider_id": "concurrency_guard",
        "provider_model": "concurrency-guard-image",
        "operations": ["text_to_image"],
        "priority": 0,
        "weight": 1,
        "cost_score": 1,
        "speed_score": 1,
        "quality_score": 1,
        "reliability_score": 1,
        "enabled": False,
    }
    resp = client.post("/v1/admin/model-mappings", headers=headers, json=mapping)
    if resp.status_code == 409:
        assert_ok(client.patch("/v1/admin/model-mappings/map_concurrency_guard_t2i", headers=headers, json={"enabled": False, "priority": 0}))
    else:
        assert_ok(resp)


def assert_concurrency_guard() -> None:
    runtime = JobRuntime()
    with SessionLocal() as db:
        account = db.get(models.AccountResource, "acct_concurrency_guard")
        mapping = db.get(models.ProviderModelMapping, "map_concurrency_guard_t2i")
        api_key = db.query(models.ApiKey).filter(models.ApiKey.user_id == "usr_admin").first()
        assert account and mapping and api_key
        account.current_leases = 0
        account.concurrency_limit = 1
        account.status = "active"
        account.health_score = 1.0
        account.failure_score = 0.0
        db.query(models.AccountLease).filter(models.AccountLease.account_id == "acct_concurrency_guard").delete()
        job1_id = "job_concurrency_guard_1"
        job2_id = "job_concurrency_guard_2"
        for job_id in [job1_id, job2_id]:
            existing = db.get(models.MediaJob, job_id)
            if existing:
                db.delete(existing)
        db.flush()
        for job_id in [job1_id, job2_id]:
            db.add(
                models.MediaJob(
                    id=job_id,
                    user_id="usr_admin",
                    api_key_id=api_key.id,
                    operation="text_to_image",
                    logical_model="t2i-fast",
                    normalized_params_json=dumps({"prompt": "concurrency guard", "n": 1}),
                    input_asset_ids_json=dumps([]),
                    output_asset_ids_json=dumps([]),
                    status="queued",
                    cost_estimate=1,
                )
            )
        db.commit()
        mapping = db.get(models.ProviderModelMapping, "map_concurrency_guard_t2i")
        lease1 = runtime.scheduler.acquire(db, job1_id, mapping, "text_to_image")
        assert lease1.account_id == "acct_concurrency_guard"
        blocked = False
        try:
            runtime.scheduler.acquire(db, job2_id, mapping, "text_to_image")
        except RuntimeError as exc:
            blocked = str(exc) == "NO_ACCOUNT_AVAILABLE"
        assert blocked
        account = db.get(models.AccountResource, "acct_concurrency_guard")
        assert account.current_leases == 1, account.current_leases
        runtime.scheduler.release(db, lease1, success=False, neutral=True)
        db.commit()
        account = db.get(models.AccountResource, "acct_concurrency_guard")
        assert account.current_leases == 0, account.current_leases


def assert_job_claim_guard() -> None:
    runtime = JobRuntime()
    suffix = str(int(time.time() * 1000))
    job_id = f"job_claim_guard_{suffix}"
    with SessionLocal() as db:
        api_key = db.query(models.ApiKey).filter(models.ApiKey.user_id == "usr_admin").first()
        assert api_key is not None
        db.add(
            models.MediaJob(
                id=job_id,
                user_id="usr_admin",
                api_key_id=api_key.id,
                operation="text_to_image",
                logical_model="t2i-fast",
                normalized_params_json=dumps({"prompt": "claim guard", "n": 1}),
                input_asset_ids_json=dumps([]),
                output_asset_ids_json=dumps([]),
                status="queued",
                cost_estimate=1,
            )
        )
        db.commit()

    db1 = SessionLocal()
    db2 = SessionLocal()
    try:
        assert runtime.claim_queued_job(db1, job_id)
        db1.commit()
        assert not runtime.claim_queued_job(db2, job_id)
        db2.rollback()
    finally:
        db1.close()
        db2.close()

    with SessionLocal() as db:
        job = db.get(models.MediaJob, job_id)
        assert job and job.status == "admitted", job.status if job else None


def main() -> None:
    server = HTTPServer(("127.0.0.1", 0), RateLimitHandler)
    port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with TestClient(app) as client:
            upsert_provider(client, port)
            upsert_account(client)
            reset_governance(client)
            upsert_mapping(client, True)
            upsert_quota_empty_provider(client, port)
            upsert_concurrency_guard(client)
            assert_concurrency_guard()
            assert_job_claim_guard()
            quota_preview = assert_ok(
                client.post(
                    "/v1/router/preview",
                    headers=headers,
                    json={
                        "model": "t2i-fast",
                        "operation": "text_to_image",
                        "params": {"providers": ["routing_quota_empty", "mock"], "provider_preference": ["routing_quota_empty"]},
                    },
                )
            )
            assert quota_preview["data"] and quota_preview["data"][0]["provider_id"] == "mock", quota_preview
            assert quota_preview["data"][0]["routing"]["available_accounts"] >= 1 and "score" in quota_preview["data"][0]["routing"], quota_preview
            quota_result = assert_ok(
                client.post(
                    "/v1/images/generations",
                    headers=headers,
                    json={
                        "model": "t2i-fast",
                        "prompt": "routing quota exhausted smoke",
                        "n": 1,
                        "providers": ["routing_quota_empty", "mock"],
                        "provider_preference": ["routing_quota_empty"],
                    },
                )
            )
            quota_job = assert_ok(client.get(f"/v1/media-jobs/{quota_result['job_id']}", headers=headers))
            assert quota_job["status"] == "completed" and quota_job["provider"] == "mock", quota_job
            preview = assert_ok(
                client.post(
                    "/v1/router/preview",
                    headers=headers,
                    json={
                        "model": "t2i-fast",
                        "operation": "text_to_image",
                        "params": {"route_policy": "balanced", "provider_preference": ["routing_rate_limit"], "providers": ["routing_rate_limit", "mock"]},
                    },
                )
            )
            assert preview["data"][0]["provider_id"] == "routing_rate_limit", preview
            assert "recent_success_rate" in preview["data"][0]["routing"] and "provider_active_jobs" in preview["data"][0]["routing"], preview
            mappings_before = assert_ok(client.get("/v1/model-mappings", headers=headers))
            reliability_before = [item for item in mappings_before["data"] if item["id"] == "map_routing_rate_limit_t2i"][0]["reliability_score"]
            cheapest = assert_ok(
                client.post(
                    "/v1/router/preview",
                    headers=headers,
                    json={"model": "t2i-fast", "operation": "text_to_image", "params": {"route_policy": "lowest_cost"}},
                )
            )
            assert cheapest["data"][0]["provider_id"] == "mock", cheapest
            result = assert_ok(
                client.post(
                    "/v1/images/generations",
                    headers=headers,
                    json={
                        "model": "t2i-fast",
                        "prompt": "routing fallback smoke",
                        "n": 1,
                        "route_policy": "balanced",
                        "providers": ["routing_rate_limit", "mock"],
                        "provider_preference": ["routing_rate_limit"],
                    },
                )
            )
            job = assert_ok(client.get(f"/v1/media-jobs/{result['job_id']}", headers=headers))
            assert job["status"] == "completed" and job["provider"] == "mock", job
            attempts = assert_ok(client.get(f"/v1/media-jobs/{job['id']}/attempts", headers=headers))
            statuses = [(item["provider_id"], item["status"], item["error_code"]) for item in attempts["data"]]
            assert ("routing_rate_limit", "failed", "RATE_LIMITED") in statuses, statuses
            mappings_after = assert_ok(client.get("/v1/model-mappings", headers=headers))
            reliability_after = [item for item in mappings_after["data"] if item["id"] == "map_routing_rate_limit_t2i"][0]["reliability_score"]
            assert reliability_after < reliability_before, (reliability_before, reliability_after)
            events = assert_ok(client.get(f"/v1/media-jobs/{job['id']}/events", headers=headers))
            reliability_events = [item for item in events["data"] if item["event_type"] == "mapping_reliability_adjusted" and item["provider_id"] == "routing_rate_limit"]
            assert reliability_events and reliability_events[-1]["metadata"]["error_code"] == "RATE_LIMITED", reliability_events
            after_failure_preview = assert_ok(
                client.post(
                    "/v1/router/preview",
                    headers=headers,
                    json={
                        "model": "t2i-fast",
                        "operation": "text_to_image",
                        "params": {"providers": ["routing_rate_limit", "mock"], "provider_preference": ["routing_rate_limit"]},
                    },
                )
            )
            failed_candidate = [item for item in after_failure_preview["data"] if item["provider_id"] == "routing_rate_limit"]
            if failed_candidate:
                assert failed_candidate[0]["routing"]["recent_success_rate"] < 1, failed_candidate[0]
            account = assert_ok(client.get("/v1/accounts", headers=headers))
            routed_account = [item for item in account["data"] if item["id"] == "acct_routing_rate_limit"][0]
            assert routed_account["status"] == "rate_limited", routed_account
            assert routed_account["last_error_code"] == "RATE_LIMITED" and routed_account["last_failed_at"], routed_account
            alerts = assert_ok(client.get("/v1/admin/alerts?status=open", headers=headers))
            account_alerts = [item for item in alerts["data"] if item["account_id"] == "acct_routing_rate_limit" and item["event_type"] == "account_status"]
            assert account_alerts, alerts
            acknowledged = assert_ok(client.patch(f"/v1/admin/alerts/{account_alerts[0]['id']}", headers=headers, json={"status": "acknowledged"}))
            assert acknowledged["status"] == "acknowledged"

            bad_provider = {
                "id": "health_alert_smoke",
                "name": "Health Alert Smoke",
                "adapter_type": "http_adapter",
                "status": "active",
                "base_config": {},
                "notes": "Health alert smoke",
            }
            resp = client.post("/v1/admin/providers", headers=headers, json=bad_provider)
            if resp.status_code == 409:
                assert_ok(client.patch("/v1/admin/providers/health_alert_smoke", headers=headers, json=bad_provider))
            else:
                assert_ok(resp)
            health = assert_ok(client.post("/v1/admin/providers/health_alert_smoke/health-check", headers=headers))
            assert health["status"] == "failed"
            provider_alerts = assert_ok(client.get("/v1/admin/alerts?status=open", headers=headers))
            assert any(item["provider_id"] == "health_alert_smoke" and item["event_type"] == "provider_health" for item in provider_alerts["data"])
            upsert_mapping(client, False)
        print("routing smoke ok")
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
