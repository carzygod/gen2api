from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

import paramiko

from acceptance_audit import ApiClient, Audit


REMOTE_CONNECTOR = r'''
from __future__ import annotations

import base64
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAIAAAD8GO2jAAAAKUlEQVR4nGNkYPjPQC5gIlvnqOZRzaOaRzWPal7QMRg1g9EwYBgAq7cCP7wf1QQAAAAASUVORK5CYII="
TEMP_HITS = 0


class Handler(BaseHTTPRequestHandler):
    def json(self, payload: dict, status: int = 200) -> None:
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
        if prompt == "remote resilience timeout":
            self.json({"id": "task_remote_resilience_timeout", "status": "queued"})
            return
        if prompt == "remote resilience temp url":
            self.json({"status": "completed", "data": [{"image_url": f"http://127.0.0.1:{self.server.server_port}/media/temp-once.png"}]})
            return
        self.json({"status": "completed", "data": [{"b64_json": PNG_B64, "mime_type": "image/png"}]})

    def do_GET(self) -> None:
        global TEMP_HITS
        if self.path.startswith("/tasks/task_remote_resilience_timeout"):
            self.json({"id": "task_remote_resilience_timeout", "status": "queued"})
            return
        if self.path.startswith("/media/temp-once.png"):
            TEMP_HITS += 1
            if TEMP_HITS > 1:
                self.json({"error": "temporary url expired"}, status=410)
                return
            body = base64.b64decode(PNG_B64)
            self.send_response(200)
            self.send_header("content-type", "image/png")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.json({"status": "ok"})

    def log_message(self, format: str, *args) -> None:
        return


port = int(sys.argv[1])
HTTPServer(("127.0.0.1", port), Handler).serve_forever()
'''


def connect(host: str, user: str, password: str, port: int) -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(hostname=host, port=port, username=user, password=password, look_for_keys=False, allow_agent=False, timeout=20)
    return client


def run(client: paramiko.SSHClient, command: str, check: bool = True) -> str:
    stdin, stdout, stderr = client.exec_command(command)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    if check and code != 0:
        raise RuntimeError(f"remote command failed ({code}): {command}\nSTDOUT:\n{out}\nSTDERR:\n{err}")
    return out + err


def shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def upload_text(client: paramiko.SSHClient, remote_path: str, content: str) -> None:
    sftp = client.open_sftp()
    try:
        with sftp.open(remote_path, "w") as handle:
            handle.write(content)
    finally:
        sftp.close()


def wait_remote_health(client: paramiko.SSHClient, port: int) -> None:
    for _ in range(30):
        status = run(client, f"curl -s -o /dev/null -w '%{{http_code}}' http://127.0.0.1:{port}/health", check=False).strip()
        if status == "200":
            return
        time.sleep(0.2)
    raise RuntimeError("remote resilience connector did not become ready")


def upsert_provider(api: ApiClient, provider_id: str, port: int, extra_config: dict[str, Any] | None = None) -> None:
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
        "notes": "Remote resilience audit provider",
    }
    status, body = api.json_status("POST", "/v1/admin/providers", payload)
    if status == 409:
        api.json("PATCH", f"/v1/admin/providers/{provider_id}", payload)
    elif status >= 400:
        raise AssertionError(body)


def upsert_account(api: ApiClient, provider_id: str, account_id: str, provider_model: str) -> None:
    payload = {
        "id": account_id,
        "provider_id": provider_id,
        "label": account_id,
        "credential_ref": "plain://remote-resilience",
        "supported_operations": ["text_to_image"],
        "supported_provider_models": [provider_model],
        "quota_buckets": [{"type": "credits", "remaining_estimate": 1000, "confidence": 1}],
        "concurrency_limit": 1,
        "status": "active",
    }
    status, body = api.json_status("POST", "/v1/admin/accounts", payload)
    if status == 409:
        api.json(
            "PATCH",
            f"/v1/admin/accounts/{account_id}",
            {**{k: v for k, v in payload.items() if k not in {"id", "provider_id"}}, "health_score": 1.0, "failure_score": 0.0, "status": "active"},
        )
    elif status >= 400:
        raise AssertionError(body)
    breaker_id = f"cb_account_{account_id}"
    status, body = api.json_status("PATCH", f"/v1/admin/circuit-breakers/{breaker_id}", {"status": "closed", "clear_block_until": True})
    if status not in {200, 404}:
        raise AssertionError(body)


def upsert_mapping(api: ApiClient, provider_id: str, provider_model: str, priority: int, enabled: bool = True) -> None:
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
    status, body = api.json_status("POST", "/v1/admin/model-mappings", payload)
    if status == 409:
        api.json("PATCH", f"/v1/admin/model-mappings/{mapping_id}", {"enabled": enabled, "priority": priority, "reliability_score": 0.8})
    elif status >= 400:
        raise AssertionError(body)


def disable_mapping(api: ApiClient, provider_id: str) -> None:
    api.json_status("PATCH", f"/v1/admin/model-mappings/map_{provider_id}_t2i", {"enabled": False})


def disable_test_resources(api: ApiClient, provider_id: str) -> None:
    disable_mapping(api, provider_id)
    api.json_status("PATCH", f"/v1/admin/accounts/acct_{provider_id}", {"status": "disabled", "concurrency_limit": 0})
    api.json_status("PATCH", f"/v1/admin/providers/{provider_id}", {"status": "disabled"})


def create_media_client(api: ApiClient, base_url: str, suffix: str) -> tuple[ApiClient, dict[str, str]]:
    user_id = f"usr_remote_resilience_{suffix}"
    policy_id = f"limit_remote_resilience_{suffix}"
    api.json("POST", "/v1/admin/users", {"id": user_id, "email": f"{user_id}@media2api.local", "wallet_balance": 100000})
    api.json(
        "POST",
        "/v1/admin/user-limit-policies",
        {
            "id": policy_id,
            "name": "Remote resilience high limits",
            "user_id": user_id,
            "requests_per_minute": 1000,
            "daily_job_limit": 1000,
            "concurrent_job_limit": 100,
            "enabled": True,
        },
    )
    key = api.json("POST", "/v1/admin/api-keys", {"user_id": user_id, "name": "remote-resilience"})
    return ApiClient(base_url, key["api_key"]), {"user_id": user_id, "policy_id": policy_id, "key_id": key["id"]}


def cleanup_media_client(api: ApiClient, resources: dict[str, str]) -> None:
    if resources.get("key_id"):
        api.json_status("DELETE", f"/v1/admin/api-keys/{resources['key_id']}")
    if resources.get("policy_id"):
        api.json_status("PATCH", f"/v1/admin/user-limit-policies/{resources['policy_id']}", {"enabled": False})
    if resources.get("user_id"):
        api.json_status("PATCH", f"/v1/admin/users/{resources['user_id']}", {"status": "disabled"})


def download_asset(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=30) as resp:
        return resp.read()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deployed media2api resilience checks using a temporary remote connector.")
    parser.add_argument("--host", default=os.getenv("DEPLOY_HOST", "192.168.31.26"))
    parser.add_argument("--ssh-port", type=int, default=int(os.getenv("DEPLOY_SSH_PORT", "22")))
    parser.add_argument("--user", default=os.getenv("DEPLOY_USER", "root"))
    parser.add_argument("--password", default=os.getenv("DEPLOY_PASSWORD", ""))
    parser.add_argument("--base-url", default=os.getenv("MEDIA2API_REMOTE_BASE_URL", "http://192.168.31.26:18082"))
    parser.add_argument("--api-key", default=os.getenv("MEDIA2API_BOOTSTRAP_KEY", "dev-admin-key"))
    parser.add_argument("--connector-port", type=int, default=18111)
    args = parser.parse_args()
    if not args.password:
        parser.error("--password or DEPLOY_PASSWORD is required")

    suffix = str(int(time.time()))
    timeout_provider = f"remote_resilience_timeout_{suffix}"
    temp_provider = f"remote_resilience_temp_{suffix}"
    remote_path = f"/tmp/media2api_resilience_connector_{suffix}.py"
    remote_log = f"/tmp/media2api_resilience_connector_{suffix}.log"
    api = ApiClient(args.base_url, args.api_key)
    media_api: ApiClient | None = None
    media_resources: dict[str, str] = {}
    audit = Audit()
    ssh = connect(args.host, args.user, args.password, args.ssh_port)
    pid = ""
    try:
        upload_text(ssh, remote_path, REMOTE_CONNECTOR)
        pid = run(
            ssh,
            f"nohup python3 {shell_quote(remote_path)} {int(args.connector_port)} > {shell_quote(remote_log)} 2>&1 & echo $!",
        ).strip().splitlines()[-1]
        wait_remote_health(ssh, args.connector_port)
        media_api, media_resources = create_media_client(api, args.base_url, suffix)

        upsert_provider(api, timeout_provider, args.connector_port, {"poll_timeout_seconds": 0.18})
        upsert_account(api, timeout_provider, f"acct_{timeout_provider}", "remote-resilience-timeout-image")
        upsert_mapping(api, timeout_provider, "remote-resilience-timeout-image", priority=0)
        timeout_result = media_api.json(
            "POST",
            "/v1/images/generations",
            {
                "model": "t2i-fast",
                "prompt": "remote resilience timeout",
                "n": 1,
                "providers": [timeout_provider, "mock"],
                "provider_preference": [timeout_provider],
            },
        )
        timeout_job = media_api.json("GET", f"/v1/media-jobs/{timeout_result['job_id']}")
        timeout_attempts = media_api.json("GET", f"/v1/media-jobs/{timeout_job['id']}/attempts")
        timeout_events = media_api.json("GET", f"/v1/media-jobs/{timeout_job['id']}/events")
        audit.check("remote_timeout_fallback", timeout_job.get("status") == "completed" and timeout_job.get("provider") == "mock", timeout_job)
        audit.check(
            "remote_timeout_attempt",
            any(item.get("provider_id") == timeout_provider and item.get("status") == "failed" and item.get("error_code") == "PROVIDER_TIMEOUT" for item in timeout_attempts.get("data", [])),
            timeout_attempts,
        )
        audit.check(
            "remote_timeout_event",
            any(item.get("event_type") == "fallback_queued" and item.get("metadata", {}).get("error_code") == "PROVIDER_TIMEOUT" for item in timeout_events.get("data", [])),
            timeout_events,
        )
        metrics_status, metrics = api.text("/metrics")
        audit.check("remote_timeout_metric", metrics_status == 200 and f'provider="{timeout_provider}"' in metrics and "media2api_provider_poll_timeout_total" in metrics)

        upsert_provider(api, temp_provider, args.connector_port)
        upsert_account(api, temp_provider, f"acct_{temp_provider}", "remote-resilience-temp-image")
        upsert_mapping(api, temp_provider, "remote-resilience-temp-image", priority=0)
        temp_result = media_api.json(
            "POST",
            "/v1/images/generations",
            {
                "model": "t2i-fast",
                "prompt": "remote resilience temp url",
                "n": 1,
                "providers": [temp_provider],
                "provider_preference": [temp_provider],
            },
        )
        temp_asset_id = temp_result.get("data", [{}])[0].get("asset_id")
        temp_asset = api.json("GET", f"/v1/admin/assets/{temp_asset_id}")
        source_status = run(ssh, f"curl -s -o /dev/null -w '%{{http_code}}' http://127.0.0.1:{int(args.connector_port)}/media/temp-once.png", check=False).strip()
        asset_bytes = download_asset(temp_asset["url"])
        audit.check("remote_temp_source_expired", source_status == "410", {"status": source_status})
        audit.check("remote_temp_asset_download", asset_bytes.startswith(b"\x89PNG"), {"asset_id": temp_asset_id, "bytes": len(asset_bytes)})
    finally:
        try:
            disable_test_resources(api, timeout_provider)
            disable_test_resources(api, temp_provider)
            cleanup_media_client(api, media_resources)
        except Exception:
            pass
        if pid:
            run(ssh, f"kill {shell_quote(pid)} >/dev/null 2>&1 || true", check=False)
        run(ssh, f"rm -f {shell_quote(remote_path)} {shell_quote(remote_log)}", check=False)
        ssh.close()

    result = audit.result()
    result["base_url"] = args.base_url
    result["checked_at_unix"] = int(time.time())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
