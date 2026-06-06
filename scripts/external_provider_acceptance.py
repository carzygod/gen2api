from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any


TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)

DEFAULT_PROVIDER_ENV = {
    "pollinations": "POLLINATIONS_KEY",
    "jimeng": "MEDIA2API_JIMENG_KEY",
    "grok": "MEDIA2API_GROK_KEY",
    "qwen": "MEDIA2API_QWEN_KEY",
    "gemini": "MEDIA2API_GEMINI_KEY",
    "kling": "MEDIA2API_KLING_KEY",
    "luma": "MEDIA2API_LUMA_KEY",
    "runway": "MEDIA2API_RUNWAY_KEY",
    "openai_image": "MEDIA2API_OPENAI_IMAGE_KEY",
}

SENSITIVE_KEYS = {"credential_value", "api_key", "authorization", "token", "password", "value"}


class ApiClient:
    def __init__(self, base_url: str, api_key: str, timeout: int = 900) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def json(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        status, body = self.json_status(method, path, payload)
        if status >= 400:
            raise RuntimeError(f"{method} {path} failed with HTTP {status}: {body}")
        return body

    def json_status(self, method: str, path: str, payload: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.base_url + path,
            data=data,
            method=method,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8")
            try:
                parsed = json.loads(body)
            except json.JSONDecodeError:
                parsed = {"body": body}
            return exc.code, parsed

    def bytes_url(self, url: str) -> tuple[int, bytes]:
        try:
            with urllib.request.urlopen(url, timeout=self.timeout) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            key_lower = str(key).lower()
            if key_lower in SENSITIVE_KEYS or any(marker in key_lower for marker in ["token", "password"]):
                result[key] = "[redacted]"
            elif "secret" in key_lower or "credential" in key_lower:
                if key_lower.endswith("_ref") or key_lower.endswith("_id") or key_lower == "credential_ref":
                    result[key] = item
                else:
                    result[key] = "[redacted]"
            else:
                result[key] = redact(item)
        return result
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def parse_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def choose_credential(args: argparse.Namespace) -> tuple[str | None, str | None, str | None]:
    if args.credential_value:
        return None, args.credential_value, "argument"
    if args.credential_env:
        env_value = os.getenv(args.credential_env)
        if env_value:
            return None, env_value, f"local_env:{args.credential_env}"
        return f"env://{args.credential_env}", None, f"remote_env:{args.credential_env}"
    if args.credential_ref:
        return args.credential_ref, None, "argument_ref"
    default_env = DEFAULT_PROVIDER_ENV.get(args.template_id, "MEDIA2API_CONNECTOR_KEY")
    env_value = os.getenv(default_env)
    if env_value:
        return None, env_value, f"local_env:{default_env}"
    return f"env://{default_env}", None, f"remote_env:{default_env}"


def upload_reference_image(client: ApiClient) -> str:
    asset = client.json(
        "POST",
        "/v1/assets",
        {
            "b64_json": TINY_PNG_B64,
            "filename": "external-provider-reference.png",
            "kind": "image",
            "purpose": "reference",
            "mime_type": "image/png",
        },
    )
    return str(asset["id"])


def wait_for_job(client: ApiClient, job_id: str, timeout_seconds: int) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    latest: dict[str, Any] = {}
    while time.time() < deadline:
        latest = client.json("GET", f"/v1/media-jobs/{job_id}")
        if latest.get("status") in {"completed", "failed", "cancelled", "expired"}:
            return latest
        time.sleep(2)
    raise RuntimeError(f"job {job_id} did not finish within {timeout_seconds}s; latest={latest}")


def mapping_by_operation(mappings: list[dict[str, Any]], operations: list[str]) -> dict[str, dict[str, Any]]:
    selected: dict[str, dict[str, Any]] = {}
    for operation in operations:
        for mapping in mappings:
            if operation in (mapping.get("operations") or []):
                selected[operation] = mapping
                break
    return selected


def create_sample_job(
    client: ApiClient,
    provider_id: str,
    operation: str,
    model: str,
    image_asset_id: str,
    source_video_asset_id: str | None,
    timeout_seconds: int,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "operation": operation,
        "model": model,
        "prompt": f"external provider acceptance {operation}",
        "provider_preference": [provider_id],
        "providers": [provider_id],
        "quality": "standard",
        "wait": True,
    }
    if operation in {"image_to_image", "image_edit", "image_to_video"}:
        payload["image"] = image_asset_id
    if operation in {"text_to_video", "image_to_video", "video_extend"}:
        payload["duration"] = 2
        payload["aspect_ratio"] = "16:9"
    if operation == "video_extend":
        if not source_video_asset_id:
            return {
                "operation": operation,
                "status": "skipped",
                "reason": "video_extend requires a source video asset from a previous sample",
            }
        payload["video"] = source_video_asset_id

    created = client.json("POST", "/v1/media-jobs", payload)
    job = created if created.get("status") in {"completed", "failed", "cancelled", "expired"} else wait_for_job(client, str(created["id"]), timeout_seconds)
    output_assets = []
    for asset_id in job.get("output_asset_ids") or []:
        asset = client.json("GET", f"/v1/assets/{asset_id}")
        status, content = client.bytes_url(str(asset.get("url") or ""))
        output_assets.append(
            {
                "asset_id": asset_id,
                "kind": asset.get("kind"),
                "download_status": status,
                "bytes": len(content),
                "download_ok": status == 200 and bool(content),
            }
        )
    return {
        "operation": operation,
        "job_id": job.get("id"),
        "status": job.get("status"),
        "provider": job.get("provider"),
        "model": job.get("model"),
        "provider_model": job.get("provider_model"),
        "error": job.get("error"),
        "output_assets": output_assets,
        "ok": job.get("status") == "completed" and bool(output_assets) and all(item["download_ok"] for item in output_assets),
    }


def run_samples(client: ApiClient, provider_id: str, mappings: list[dict[str, Any]], operations: list[str], max_samples: int, timeout_seconds: int) -> list[dict[str, Any]]:
    selected = mapping_by_operation(mappings, operations)
    image_asset_id = upload_reference_image(client)
    results: list[dict[str, Any]] = []
    source_video_asset_id: str | None = None
    sample_order = ["text_to_image", "image_to_image", "image_edit", "text_to_video", "image_to_video", "video_extend"]
    for operation in sample_order:
        if operation not in selected or len(results) >= max_samples:
            continue
        mapping = selected[operation]
        result = create_sample_job(
            client,
            provider_id,
            operation,
            str(mapping["logical_model"]),
            image_asset_id,
            source_video_asset_id,
            timeout_seconds,
        )
        results.append(result)
        if result.get("ok") and operation in {"text_to_video", "image_to_video"}:
            assets = result.get("output_assets") or []
            video_assets = [item for item in assets if item.get("kind") == "video"]
            if video_assets:
                source_video_asset_id = str(video_assets[0]["asset_id"])
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Activate and verify one real external media provider.")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--template-id", default="pollinations")
    parser.add_argument("--provider-base-url", default="")
    parser.add_argument("--credential-ref", default="")
    parser.add_argument("--credential-value", default="")
    parser.add_argument("--credential-env", default="")
    parser.add_argument("--credential-kind", default="api_key")
    parser.add_argument("--account-id", default="")
    parser.add_argument("--account-label", default="")
    parser.add_argument("--concurrency-limit", type=int, default=1)
    parser.add_argument("--operations", default="")
    parser.add_argument("--run-samples", action="store_true")
    parser.add_argument("--max-samples", type=int, default=4)
    parser.add_argument("--sample-timeout", type=int, default=900)
    parser.add_argument("--contract-run-submit", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-action-required", action="store_true")
    args = parser.parse_args()

    credential_ref, credential_value, credential_source = choose_credential(args)
    if not args.dry_run and not credential_value and credential_ref and credential_ref.startswith("env://"):
        print(
            json.dumps(
                {
                    "status": "action_required",
                    "error": "remote_env_credential_unverified",
                    "message": f"{credential_ref} must exist in the deployed service environment, or pass --credential-value/--credential-env with a local value.",
                    "credential_ref": credential_ref,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2

    client = ApiClient(args.base_url, args.api_key, timeout=max(60, args.sample_timeout))
    operations = parse_csv(args.operations)
    activate_payload: dict[str, Any] = {
        "dry_run": args.dry_run,
        "status": "active",
        "account_status": "active",
        "credential_kind": args.credential_kind,
        "concurrency_limit": max(1, args.concurrency_limit),
        "enable_mappings": True,
        "overwrite_config": True,
        "run_health_check": not args.dry_run,
        "run_contract_tests": not args.dry_run,
        "run_quota_sync": not args.dry_run,
        "contract_run_submit": bool(args.contract_run_submit),
    }
    if credential_ref:
        activate_payload["credential_ref"] = credential_ref
    if credential_value:
        activate_payload["credential_value"] = credential_value
    if args.provider_base_url:
        activate_payload["base_url"] = args.provider_base_url
    if args.account_id:
        activate_payload["account_id"] = args.account_id
    if args.account_label:
        activate_payload["account_label"] = args.account_label
    if operations:
        activate_payload["contract_operations"] = operations

    activation = client.json("POST", f"/v1/admin/provider-templates/{args.template_id}/activate", activate_payload)
    mappings = ((activation.get("install") or {}).get("mappings") or []) if isinstance(activation.get("install"), dict) else []
    if not operations:
        operations = sorted({operation for mapping in mappings for operation in mapping.get("operations", [])})

    samples: list[dict[str, Any]] = []
    if args.run_samples and not args.dry_run:
        samples = run_samples(
            client,
            args.template_id,
            mappings,
            operations,
            max(1, args.max_samples),
            max(60, args.sample_timeout),
        )

    readiness = client.json("GET", "/v1/admin/readiness") if not args.dry_run else {}
    acceptance = client.json("GET", "/v1/admin/acceptance-report") if not args.dry_run else {}
    failed_samples = [item for item in samples if not item.get("ok") and item.get("status") != "skipped"]
    result_status = (
        "planned"
        if args.dry_run
        else "passed"
        if activation.get("ok") and not failed_samples and (not acceptance or acceptance.get("production_ready") is True)
        else "action_required"
    )
    result = {
        "object": "media2api.external_provider_acceptance",
        "template_id": args.template_id,
        "status": result_status,
        "credential_source": credential_source,
        "activation": redact(activation),
        "samples": redact(samples),
        "readiness": {
            "status": readiness.get("status"),
            "core_ready": readiness.get("core_ready"),
            "production_ready": readiness.get("production_ready"),
            "action_items": readiness.get("action_items", []),
        }
        if readiness
        else {},
        "acceptance": {
            "status": acceptance.get("status"),
            "core_ready": acceptance.get("core_ready"),
            "production_ready": acceptance.get("production_ready"),
            "summary": acceptance.get("summary"),
        }
        if acceptance
        else {},
        "failed_samples": failed_samples,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["status"] in {"passed", "planned"} or args.allow_action_required:
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
