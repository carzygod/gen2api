from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class Harness:
    def __init__(self, base_url: str | None, api_key: str) -> None:
        self.base_url = base_url.rstrip("/") if base_url else ""
        self.api_key = api_key
        self._client: TestClient | None = None
        self._http: httpx.Client | None = None

    def __enter__(self) -> Harness:
        if self.base_url:
            self._http = httpx.Client(base_url=self.base_url, timeout=120)
        else:
            from media2api.main import app

            self._client = TestClient(app)
            self._client.__enter__()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self._client:
            self._client.__exit__(exc_type, exc, tb)
        if self._http:
            self._http.close()

    def request(self, method: str, path: str, api_key: str | None = None, payload: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
        headers = {"Authorization": f"Bearer {api_key or self.api_key}"}
        if self._client:
            resp = self._client.request(method, path, headers=headers, json=payload)
        elif self._http:
            resp = self._http.request(method, path, headers=headers, json=payload)
        else:
            raise RuntimeError("HARNESS_NOT_STARTED")
        try:
            body = resp.json()
        except Exception:
            body = {"raw": resp.text}
        return resp.status_code, body

    def json(self, method: str, path: str, api_key: str | None = None, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        status, body = self.request(method, path, api_key=api_key, payload=payload)
        if status >= 400:
            raise AssertionError(f"{method} {path} failed: {status} {body}")
        return body


def create_stability_user(client: Harness, iterations: int) -> tuple[str, str, str]:
    suffix = str(int(time.time() * 1000))
    user_id = f"usr_stability_{suffix}"
    policy_id = f"limit_stability_{suffix}"
    user = client.json(
        "POST",
        "/v1/admin/users",
        payload={"id": user_id, "email": f"{user_id}@media2api.local", "wallet_balance": max(1000000, iterations * 50), "tier": "stability"},
    )
    policy = client.json(
        "POST",
        "/v1/admin/user-limit-policies",
        payload={
            "id": policy_id,
            "name": "Stability audit temporary policy",
            "user_id": user["id"],
            "requests_per_minute": max(2000, iterations + 100),
            "daily_job_limit": max(2000, iterations + 100),
            "concurrent_job_limit": 100,
            "high_cost_allowed": True,
            "enabled": True,
            "notes": "Temporary policy created by scripts/stability_audit.py",
        },
    )
    key = client.json("POST", "/v1/admin/api-keys", payload={"user_id": user["id"], "name": "stability-audit"})
    return user["id"], key["api_key"], policy["id"]


def run_mock_iterations(client: Harness, iterations: int, user_api_key: str) -> dict[str, Any]:
    started = time.time()
    job_ids: list[str] = []
    asset_ids: list[str] = []
    failures: list[dict[str, Any]] = []
    for index in range(iterations):
        status, body = client.request(
            "POST",
            "/v1/images/generations",
            api_key=user_api_key,
            payload={
                "model": "t2i-fast",
                "prompt": f"mock stability audit {index}",
                "n": 1,
                "provider_preference": ["mock"],
            },
        )
        if status >= 400:
            failures.append({"index": index, "status": status, "body": body})
            break
        item = (body.get("data") or [{}])[0]
        job_id = body.get("job_id")
        asset_id = item.get("asset_id")
        if not job_id or not asset_id:
            failures.append({"index": index, "status": status, "body": body})
            break
        job_ids.append(job_id)
        asset_ids.append(asset_id)
        if (index + 1) % 100 == 0:
            job = client.json("GET", f"/v1/media-jobs/{job_id}", api_key=user_api_key)
            if job.get("status") != "completed":
                failures.append({"index": index, "status": "job_not_completed", "job": job})
                break

    active_leases = client.json("GET", "/v1/admin/account-leases?account_id=acct_mock_default&status=active&limit=1000")
    leaked = [item for item in active_leases.get("data", []) if item.get("job_id") in set(job_ids)]
    return {
        "iterations_requested": iterations,
        "iterations_completed": len(job_ids),
        "asset_count": len(asset_ids),
        "duration_seconds": round(time.time() - started, 3),
        "failures": failures[:3],
        "active_lease_leaks": leaked[:5],
    }


def run_local_lease_expiry_check() -> dict[str, Any]:
    from media2api import models as db_models
    from media2api.database import SessionLocal
    from media2api.utils import dumps

    suffix = str(int(time.time() * 1000))
    job_id = f"job_stability_expired_{suffix}"
    attempt_id = f"attempt_stability_expired_{suffix}"
    lease_id = f"lease_stability_expired_{suffix}"

    with SessionLocal() as db:
        account = db.get(db_models.AccountResource, "acct_mock_default")
        if not account:
            raise AssertionError("acct_mock_default missing")
        active_before = int(
            db.query(db_models.AccountLease)
            .filter(db_models.AccountLease.account_id == "acct_mock_default", db_models.AccountLease.status == "active")
            .count()
        )
        account.current_leases = active_before + 1
        db.add(
            db_models.MediaJob(
                id=job_id,
                user_id="usr_admin",
                api_key_id="key_admin",
                operation="text_to_image",
                logical_model="t2i-fast",
                normalized_params_json=dumps({"model": "t2i-fast", "prompt": "stability expired lease", "n": 1}),
                input_asset_ids_json=dumps([]),
                output_asset_ids_json=dumps([]),
                provider_id="mock",
                provider_model="mock-image-fast",
                account_id="acct_mock_default",
                status="polling",
                cost_estimate=10,
            )
        )
        db.add(
            db_models.MediaJobAttempt(
                id=attempt_id,
                job_id=job_id,
                provider_id="mock",
                account_id="acct_mock_default",
                provider_model="mock-image-fast",
                status="polling",
                started_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=45),
                request_snapshot_json=dumps({"stability": True}),
            )
        )
        db.add(
            db_models.AccountLease(
                id=lease_id,
                job_id=job_id,
                account_id="acct_mock_default",
                provider_id="mock",
                provider_model="mock-image-fast",
                expires_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=1),
                status="active",
            )
        )
        db.commit()

    with Harness(None, "dev-admin-key") as client:
        sweep = client.json("POST", "/v1/admin/account-leases/release-expired")
        job = client.json("GET", f"/v1/media-jobs/{job_id}")
        attempts = client.json("GET", f"/v1/media-jobs/{job_id}/attempts")
        leases = client.json("GET", f"/v1/admin/account-leases?job_id={job_id}")

    with SessionLocal() as db:
        account_after = db.get(db_models.AccountResource, "acct_mock_default")
        after = int(account_after.current_leases) if account_after else None

    return {
        "sweep": sweep,
        "job_status": job.get("status"),
        "job_error": (job.get("error") or {}).get("code"),
        "attempt_status": attempts.get("data", [{}])[0].get("status"),
        "lease_status": leases.get("data", [{}])[0].get("status"),
        "account_leases_before": active_before,
        "account_leases_after": after,
    }


def run_remote_lease_expiry_check(base_url: str, api_key: str) -> dict[str, Any]:
    with Harness(base_url, api_key) as client:
        result = client.json("POST", "/v1/admin/account-leases/self-test-expiry")
    return {
        "self_test": result,
        "ok": result.get("ok") is True,
        "job_status": (result.get("job") or {}).get("status"),
        "job_error": ((result.get("job") or {}).get("error") or {}).get("code"),
        "attempt_status": (result.get("attempt") or {}).get("status"),
        "lease_status": (result.get("lease") or {}).get("status"),
        "account_leases_before": (result.get("account") or {}).get("current_leases_before"),
        "account_leases_after": (result.get("account") or {}).get("current_leases_after"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run stability checks for media2api.")
    parser.add_argument("--base-url", default="", help="Optional deployed base URL. Omit for local in-process checks.")
    parser.add_argument("--api-key", default="dev-admin-key")
    parser.add_argument("--iterations", type=int, default=1000)
    parser.add_argument("--skip-lease-expiry", action="store_true")
    args = parser.parse_args()

    results: dict[str, Any] = {"status": "passed", "checks": {}}
    with Harness(args.base_url or None, args.api_key) as client:
        health = client.json("GET", "/health")
        if health.get("status") != "ok":
            raise AssertionError(health)
        iterations = client.json("POST", "/v1/admin/stability/self-test-mock", payload={"iterations": args.iterations})
        results["checks"]["mock_iterations"] = iterations
        if (
            iterations.get("ok") is not True
            or iterations.get("iterations_completed") != args.iterations
            or iterations.get("failures")
            or ((iterations.get("leases") or {}).get("active_lease_leaks") or [])
        ):
            results["status"] = "failed"

    if not args.base_url and not args.skip_lease_expiry:
        lease_expiry = run_local_lease_expiry_check()
        results["checks"]["lease_expiry"] = lease_expiry
        if (
            lease_expiry["job_status"] != "expired"
            or lease_expiry["job_error"] != "LEASE_EXPIRED"
            or lease_expiry["attempt_status"] != "expired"
            or lease_expiry["lease_status"] != "expired"
            or lease_expiry["account_leases_after"] != lease_expiry["account_leases_before"]
        ):
            results["status"] = "failed"
    elif args.base_url and not args.skip_lease_expiry:
        lease_expiry = run_remote_lease_expiry_check(args.base_url, args.api_key)
        results["checks"]["lease_expiry"] = lease_expiry
        if (
            not lease_expiry["ok"]
            or lease_expiry["job_status"] != "expired"
            or lease_expiry["job_error"] != "LEASE_EXPIRED"
            or lease_expiry["attempt_status"] != "expired"
            or lease_expiry["lease_status"] != "expired"
            or lease_expiry["account_leases_after"] != lease_expiry["account_leases_before"]
        ):
            results["status"] = "failed"

    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0 if results["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
