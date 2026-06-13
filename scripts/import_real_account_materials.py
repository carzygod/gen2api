from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


SENSITIVE_KEYS = {
    "authorization",
    "cookie",
    "cookie_header",
    "session",
    "token",
    "access_token",
    "refresh_token",
    "id_token",
    "credential_value",
    "gemini_oauth_creds_file",
    "gemini_oauth_creds_base64",
    "chatgpt_cookie_or_session",
    "discord_session_or_user_token",
}


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if key.lower() in SENSITIVE_KEYS or any(marker in key.lower() for marker in ["token", "cookie", "secret", "credential"]):
                result[key] = "[provided]" if item else ""
            else:
                result[key] = redact(item)
        return result
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def read_json(path: str) -> dict[str, Any]:
    if path == "-":
        text = sys.stdin.read()
    else:
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("Input JSON must be an object.")
    return payload


def http_json(base_url: str, api_key: str, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Authorization": f"Bearer {api_key}"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = Request(base_url.rstrip("/") + path, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=900) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        try:
            detail = json.loads(body)
        except Exception:
            detail = {"status_code": exc.code, "body": body}
        raise RuntimeError(json.dumps({"status_code": exc.code, "detail": detail}, ensure_ascii=False)) from exc
    return json.loads(body)


def provider_query(provider_ids: list[str]) -> str:
    if not provider_ids:
        return ""
    return "?" + urlencode({"provider_ids": ",".join(provider_ids)})


def normalize_bulk_payload(raw: dict[str, Any], dry_run: bool, provider_ids: list[str]) -> dict[str, Any]:
    if isinstance(raw.get("items"), list):
        payload = dict(raw)
        payload["dry_run"] = dry_run
        payload.setdefault("continue_on_error", True)
        return payload

    if isinstance(raw.get("providers"), dict):
        items = []
        for provider_id, item in raw["providers"].items():
            if not isinstance(item, dict):
                raise ValueError(f"providers.{provider_id} must be an object.")
            items.append({"provider_id": provider_id, **item})
        return {"dry_run": dry_run, "continue_on_error": True, "items": items}

    if raw.get("provider_id") or raw.get("credential_value") or raw.get("credential_ref"):
        provider_id = str(raw.get("provider_id") or (provider_ids[0] if provider_ids else "")).strip()
        if not provider_id:
            raise ValueError("provider_id is required for single-account payloads.")
        item = dict(raw)
        item["provider_id"] = provider_id
        return {"dry_run": dry_run, "continue_on_error": True, "items": [item]}

    raise ValueError("Input JSON must contain items[], providers{}, or a single provider_id/credential_value payload.")


def summarize_bulk_response(payload: dict[str, Any]) -> dict[str, Any]:
    rows = []
    for row in payload.get("data") or []:
        package = row.get("package") or {}
        applied = package.get("applied") or {}
        account = applied.get("account") if isinstance(applied, dict) else {}
        runtime_sync = package.get("runtime_credential_sync") or {}
        rows.append(
            {
                "index": row.get("index"),
                "provider_id": row.get("provider_id"),
                "status": row.get("status"),
                "ok": row.get("ok"),
                "account_id": account.get("id") if isinstance(account, dict) else "",
                "runtime_credential_sync": {
                    "status": runtime_sync.get("status"),
                    "ok": runtime_sync.get("ok"),
                },
            }
        )
    return {
        "object": payload.get("object"),
        "dry_run": payload.get("dry_run"),
        "status": payload.get("status"),
        "ok": payload.get("ok"),
        "summary": payload.get("summary"),
        "data": rows,
        "errors": redact(payload.get("errors") or []),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Dry-run or import real reverse-proxy account material into media2api.")
    parser.add_argument("--base-url", default=os.getenv("MEDIA2API_BASE_URL", "http://127.0.0.1:18082"))
    parser.add_argument("--api-key", default=os.getenv("MEDIA2API_API_KEY", ""))
    parser.add_argument("--provider-ids", default="", help="Comma-separated provider ids. Empty uses production recommendation.")
    parser.add_argument("--payload-file", default="", help="JSON file to import. Use '-' for stdin. Omit to print the intake sheet.")
    parser.add_argument("--import", dest="do_import", action="store_true", help="Write accounts. Without this flag the script runs dry-run only.")
    parser.add_argument("--run-acceptance", action="store_true", help="Run /v1/admin/account-acceptance-suite after import or dry-run.")
    parser.add_argument("--require-production-ready", action="store_true", help="Require final production readiness in the acceptance suite.")
    parser.add_argument("--max-samples", type=int, default=1)
    args = parser.parse_args()

    if not args.api_key:
        raise SystemExit("MEDIA2API_API_KEY or --api-key is required.")

    provider_ids = [item.strip() for item in args.provider_ids.split(",") if item.strip()]
    intake = http_json(args.base_url, args.api_key, "GET", "/v1/admin/proxy-kernels/credential-intake-sheet" + provider_query(provider_ids))

    if not args.payload_file:
        print(json.dumps(redact(intake), ensure_ascii=False, indent=2))
        print("\nNo payload imported. Provide --payload-file and keep --import off for dry-run preflight first.", file=sys.stderr)
        return

    raw = read_json(args.payload_file)
    bulk_payload = normalize_bulk_payload(raw, dry_run=not args.do_import, provider_ids=provider_ids or list(intake.get("provider_ids") or []))
    bulk = http_json(args.base_url, args.api_key, "POST", "/v1/admin/proxy-kernels/account-materials-bulk", bulk_payload)
    print(json.dumps(summarize_bulk_response(bulk), ensure_ascii=False, indent=2))

    if args.run_acceptance:
        acceptance_payload = {
            "dry_run": False,
            "external_only": True,
            "active_only": True,
            "provider_ids": [item.get("provider_id") for item in bulk_payload.get("items", []) if item.get("provider_id")],
            "operations": intake.get("required_operations") or [],
            "run_samples": True,
            "max_samples": max(1, int(args.max_samples or 1)),
            "require_production_ready": bool(args.require_production_ready),
        }
        acceptance = http_json(args.base_url, args.api_key, "POST", "/v1/admin/account-acceptance-suite", acceptance_payload)
        print(json.dumps(redact({"account_acceptance_suite": acceptance}), ensure_ascii=False, indent=2))

    matrix = http_json(args.base_url, args.api_key, "GET", "/v1/admin/final-acceptance-matrix")
    print(json.dumps({"final_acceptance_summary": matrix.get("summary"), "blocked_rows": matrix.get("blocked_rows")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
