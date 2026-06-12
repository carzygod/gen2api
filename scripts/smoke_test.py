from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta
import os
import shutil
import tarfile
import time
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse

from fastapi.testclient import TestClient
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "var" / "smoke_test.db"
ASSET_DIR = ROOT / "var" / "smoke-test-assets"
PROXY_KERNEL_DIR = ROOT / "var" / "smoke-test-proxy-kernels"
SOURCE_REPO_DIR = ROOT / "var" / "smoke-test-source-repo"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
if DB_PATH.exists():
    DB_PATH.unlink()
if PROXY_KERNEL_DIR.exists():
    shutil.rmtree(PROXY_KERNEL_DIR)
PROXY_KERNEL_DIR.mkdir(parents=True, exist_ok=True)
if SOURCE_REPO_DIR.exists():
    shutil.rmtree(SOURCE_REPO_DIR)
SOURCE_REPO_DIR.mkdir(parents=True, exist_ok=True)
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH.as_posix()}"
os.environ["ASSET_DIR"] = ASSET_DIR.as_posix()
os.environ["MEDIA2API_PROXY_KERNEL_DIR"] = PROXY_KERNEL_DIR.as_posix()
os.environ["MEDIA2API_SOURCE_REPO_DIR"] = SOURCE_REPO_DIR.as_posix()

sys.path.insert(0, str(ROOT))

from media2api import models as db_models
from media2api.config import settings
from media2api.database import SessionLocal
from media2api.main import app, build_proxy_kernel_release_checksums, proxy_kernel_asset_digest_sha256, proxy_kernel_best_release_candidate, proxy_kernel_runtime_acquisition_next_action, proxy_kernel_service, proxy_kernel_source_repo_sync_decision
from media2api.provider_templates import FINALIZED_PROVIDER_IDS, PROVIDER_TEMPLATES
from media2api.services_core import AccountScheduler, ModelRouter
from media2api.services_proxy_kernels import ProxyKernelRuntimeService
from media2api.utils import dumps
headers = {"Authorization": "Bearer dev-admin-key"}


def assert_ok(resp):
    if resp.status_code >= 400:
        raise AssertionError(f"{resp.status_code}: {resp.text}")
    return resp.json()


def tiny_png_bytes() -> bytes:
    image = Image.new("RGB", (24, 24), color=(84, 185, 129))
    buf = BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


class StaticAssetHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        data = tiny_png_bytes()
        self.send_response(200)
        self.send_header("content-type", "image/png")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args) -> None:
        return


def main() -> None:
    for provider_id in FINALIZED_PROVIDER_IDS:
        template = PROVIDER_TEMPLATES[provider_id]
        endpoints = template.default_config.get("endpoints") or {}
        for operation in template.operations:
            if operation in {"text_to_image", "image_to_image", "image_edit", "text_to_video", "image_to_video", "video_extend"}:
                assert operation in endpoints, (provider_id, operation, endpoints)
                if operation in {"text_to_image", "image_to_image", "image_edit"}:
                    assert str(endpoints[operation]).startswith("/v1/images/"), (provider_id, operation, endpoints)
                else:
                    assert str(endpoints[operation]).startswith("/v1/videos/"), (provider_id, operation, endpoints)

    digest_value = "a" * 64
    assert proxy_kernel_asset_digest_sha256({"digest": f"sha256:{digest_value}"}) == digest_value
    assert proxy_kernel_asset_digest_sha256({"digest": digest_value.upper()}) == digest_value
    assert proxy_kernel_asset_digest_sha256({"digest": "sha512:" + digest_value}) == ""
    assert proxy_kernel_service.asset_candidate_score("codex-register-v2-linux-x64.zip") > 0
    assert proxy_kernel_service.asset_candidate_score("CLIProxyAPI_7.1.68_linux_amd64.tar.gz") > 0
    assert proxy_kernel_service.asset_candidate_score("anti-api-winget-x64.zip") == 0
    assert proxy_kernel_service.asset_candidate_score("tool-windows-x64.zip") == 0
    assert proxy_kernel_service.asset_candidate_score("tool-darwin-aarch64.tar.gz") == 0
    assert proxy_kernel_service.asset_candidate_score("tool-linux-arm64.tar.gz") == 0
    assert proxy_kernel_service.asset_candidate_score("tool-linux-x64-docker.tar.gz") == 0
    original_media2api_github_token = os.environ.pop("MEDIA2API_GITHUB_TOKEN", None)
    original_github_token = os.environ.pop("GITHUB_TOKEN", None)
    try:
        assert "Authorization" not in proxy_kernel_service.github_headers(), proxy_kernel_service.github_headers()
        os.environ["MEDIA2API_GITHUB_TOKEN"] = "ghp_test_token_for_header_shape"
        assert proxy_kernel_service.github_headers()["Authorization"] == "Bearer ghp_test_token_for_header_shape"
    finally:
        os.environ.pop("MEDIA2API_GITHUB_TOKEN", None)
        if original_media2api_github_token is not None:
            os.environ["MEDIA2API_GITHUB_TOKEN"] = original_media2api_github_token
        if original_github_token is not None:
            os.environ["GITHUB_TOKEN"] = original_github_token
    executable_probe_dir = PROXY_KERNEL_DIR / "executable-probe"
    executable_probe_dir.mkdir(parents=True, exist_ok=True)
    executable_probe = executable_probe_dir / "codex-register"
    executable_probe.write_bytes(b"#!/bin/sh\nexit 0\n")
    executable_probe.chmod(0o644)
    executable_payloads = proxy_kernel_service.executable_candidate_payloads([executable_probe], executable_probe_dir, "openai_codex")
    assert executable_payloads and executable_payloads[0]["relative_path"] == "codex-register", executable_payloads
    if os.name != "nt":
        assert executable_probe.stat().st_mode & 0o100 and executable_payloads[0]["made_executable"] is True, executable_payloads
    best_gemini_candidate = proxy_kernel_best_release_candidate(
        [
            {"asset_name": "CLIProxyAPI_7.1.68_darwin_aarch64.tar.gz", "candidate_score": 1, "preferred": True},
            {"asset_name": "CLIProxyAPI_7.1.68_windows_x64.zip", "candidate_score": 4, "preferred": True},
            {"asset_name": "CLIProxyAPI_7.1.68_linux_amd64_no-plugin.tar.gz", "candidate_score": 8, "preferred": True},
            {"asset_name": "CLIProxyAPI_7.1.68_linux_amd64.tar.gz", "candidate_score": 8, "preferred": True},
        ],
        require_preferred=True,
    )
    assert best_gemini_candidate["asset_name"] == "CLIProxyAPI_7.1.68_linux_amd64.tar.gz", best_gemini_candidate
    best_midjourney_candidate = proxy_kernel_best_release_candidate(
        [
            {"asset_name": "midjourney-proxy-linux-x64-docker-v11.9.7.tar.gz", "candidate_score": 8, "preferred": True},
            {"asset_name": "midjourney-proxy-linux-x64-v11.9.7.tar.gz", "candidate_score": 8, "preferred": True},
        ],
        require_preferred=True,
    )
    assert best_midjourney_candidate["asset_name"] == "midjourney-proxy-linux-x64-v11.9.7.tar.gz", best_midjourney_candidate
    preflight_failed_without_source = proxy_kernel_runtime_acquisition_next_action(
        kernel={
            "installed": {"path": "/tmp/runner"},
            "installed_verified": True,
            "runtime_preflight": {"ok": False, "status": "failed"},
        },
        release_state={"status": "ok", "install_ready_candidate_count": 1, "preferred_asset_count": 1},
        source_repo={"exists": False, "is_git_repo": False},
        resolve_release=True,
    )
    assert preflight_failed_without_source["id"] == "source_repo_reference", preflight_failed_without_source
    assert preflight_failed_without_source["primary_api"].endswith("/source-repo/sync"), preflight_failed_without_source
    assert preflight_failed_without_source["follow_up_api"].endswith("/source-runtime-plan"), preflight_failed_without_source
    preflight_failed_with_source = proxy_kernel_runtime_acquisition_next_action(
        kernel={
            "installed": {"path": "/tmp/runner"},
            "installed_verified": True,
            "runtime_preflight": {"ok": False, "status": "failed"},
        },
        release_state={"status": "ok", "install_ready_candidate_count": 1, "preferred_asset_count": 1},
        source_repo={"exists": True, "is_git_repo": True},
        resolve_release=True,
    )
    assert preflight_failed_with_source["id"] == "source_runtime_plan", preflight_failed_with_source
    source_sync_needed_after_preflight = proxy_kernel_source_repo_sync_decision(
        kernel={
            "installed": {"path": "/tmp/runner"},
            "installed_verified": True,
            "runtime_preflight": {"ok": False, "status": "failed"},
        },
        release_state={"status": "ok", "install_ready_candidate_count": 1, "preferred_asset_count": 1},
        source_repo={"exists": False, "is_git_repo": False},
        only_when_needed=True,
        resolve_release=True,
    )
    assert source_sync_needed_after_preflight["should_sync"] is True, source_sync_needed_after_preflight
    assert source_sync_needed_after_preflight["next_action"]["id"] == "source_repo_reference", source_sync_needed_after_preflight
    source_sync_skipped_for_release = proxy_kernel_source_repo_sync_decision(
        kernel={"installed": {}, "installed_verified": False},
        release_state={
            "status": "ok",
            "install_ready_candidate_count": 1,
            "preferred_asset_count": 1,
            "source_repo_fallback": False,
            "next_step": {"reason": "release path is still preferred"},
        },
        source_repo={"exists": False, "is_git_repo": False},
        only_when_needed=True,
        resolve_release=True,
    )
    assert source_sync_skipped_for_release["should_sync"] is False, source_sync_skipped_for_release

    source_repo = SOURCE_REPO_DIR / "basketikun__chatgpt2api"
    source_repo.mkdir(parents=True, exist_ok=True)
    (source_repo / ".git").mkdir(exist_ok=True)
    (source_repo / "package.json").write_text(
        json.dumps(
            {
                "name": "source-runtime-smoke",
                "scripts": {"start": "node server.js", "build": "node -e \"console.log('build')\""},
                "main": "server.js",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (source_repo / "server.js").write_text("console.log('source runtime smoke');\n", encoding="utf-8")
    (source_repo / "requirements.txt").write_text("", encoding="utf-8")
    (source_repo / "main.py").write_text("print('source runtime smoke')\n", encoding="utf-8")
    server = HTTPServer(("127.0.0.1", 0), StaticAssetHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
      with TestClient(app) as client:
        assert_ok(client.get("/health"))
        original_probe_release = proxy_kernel_service.probe_release
        digest_asset = {
            "name": "codex-register-v2-linux-x64.zip",
            "size": 1024,
            "browser_download_url": "https://example.invalid/codex-register-v2-linux-x64.zip",
            "candidate_score": 8,
            "candidate_reason": "possible linux/amd64 release asset",
            "digest": f"sha256:{digest_value}",
        }
        try:
            proxy_kernel_service.probe_release = lambda provider_id: {
                "object": "media2api.proxy_kernel.release_probe",
                "provider_id": provider_id,
                "status": "ok",
                "release": {"tag_name": "v.test"},
                "assets": [digest_asset],
                "preferred_assets": [digest_asset],
            }
            db = SessionLocal()
            try:
                digest_checksums = build_proxy_kernel_release_checksums(db, "openai_codex", dry_run=False)
            finally:
                db.close()
            assert digest_checksums["github_asset_digest_count"] == 1, digest_checksums
            assert digest_checksums["install_ready_candidate_count"] == 1, digest_checksums
            assert digest_checksums["resolved_sha256_candidates"][0]["expected_sha256"] == digest_value, digest_checksums
            assert digest_checksums["resolved_sha256_candidates"][0]["source_type"] == "github_release_asset_digest", digest_checksums
        finally:
            proxy_kernel_service.probe_release = original_probe_release
        assert_ok(client.patch("/v1/admin/users/usr_admin", headers=headers, json={"wallet_balance": 1000000, "status": "active"}))
        models = assert_ok(client.get("/v1/models", headers=headers))
        assert models["data"]
        providers = assert_ok(client.get("/v1/providers", headers=headers))
        assert len(providers["data"]) >= 1
        dashboard_suffix = int(time.time() * 1000)
        accounts = assert_ok(client.get("/v1/accounts", headers=headers))
        assert len(accounts["data"]) >= 1
        mappings = assert_ok(client.get("/v1/model-mappings", headers=headers))
        assert len(mappings["data"]) >= 1
        runtime = assert_ok(client.get("/v1/runtime", headers=headers))
        assert "job_counts" in runtime
        assert runtime["asset_store"] == "local"
        assert runtime["asset_backend"]["type"] == "local"
        assert runtime["worker_concurrency"] >= 1
        assert runtime["worker_stalled_job_seconds"] >= 1
        readiness = assert_ok(client.get("/v1/admin/readiness", headers=headers))
        assert readiness["object"] == "readiness" and readiness["core_ready"] is True, readiness
        assert {"database_query", "operation_coverage", "external_connector_accounts", "external_mixed_media_provider"}.issubset({check["name"] for check in readiness["checks"]}), readiness
        proxy_kernels = assert_ok(client.get("/v1/admin/proxy-kernels", headers=headers))
        assert proxy_kernels["object"] == "media2api.proxy_kernel.list" and proxy_kernels["summary"]["total"] >= 10, proxy_kernels
        assert {"ready_for_live_acceptance", "needs_live_acceptance", "needs_route", "needs_health", "needs_preflight", "usable"}.issubset(proxy_kernels["summary"]), proxy_kernels
        assert proxy_kernels["summary"]["needs_route"] == 0, proxy_kernels
        assert {"openai_web_session", "gemini_cli_oauth", "doubao_web_session", "qwen_ai_web_session"}.issubset({item["provider_id"] for item in proxy_kernels["data"]}), proxy_kernels
        assert all({"directly_usable", "route_ready", "route_evidence", "health_ok", "latest_health", "runtime_preflight", "runtime_preflight_ok", "ready_for_live_acceptance", "live_acceptance_ok", "live_acceptance"}.issubset(item) for item in proxy_kernels["data"]), proxy_kernels
        bulk_routing_plan = assert_ok(client.get("/v1/admin/proxy-kernels/routing-plan", headers=headers))
        assert bulk_routing_plan["object"] == "media2api.proxy_kernel.routing_plan.list" and bulk_routing_plan["summary"]["total"] >= 10, bulk_routing_plan
        bulk_routing_apply = assert_ok(
            client.post(
                "/v1/admin/proxy-kernels/apply-routing",
                headers=headers,
                json={"provider_ids": [], "status": "active", "enable_mappings": True, "priority_offset": 0, "update_provider_base_url": True},
            )
        )
        assert bulk_routing_apply["object"] == "media2api.proxy_kernel.routing_apply.list" and bulk_routing_apply["no_fake_account_created"] is True, bulk_routing_apply
        applied_mapping_count = bulk_routing_apply["summary"]["mappings"]["created"] + bulk_routing_apply["summary"]["mappings"]["updated"]
        assert bulk_routing_apply["summary"]["total"] >= 10 and applied_mapping_count >= 1, bulk_routing_apply
        assert all(item["routing_plan"]["route_config_ready"] and not item["routing_plan"]["missing_mappings"] for item in bulk_routing_apply["data"]), bulk_routing_apply
        bulk_go_live = assert_ok(client.get("/v1/admin/proxy-kernels/go-live-checklist", headers=headers))
        assert bulk_go_live["object"] == "media2api.proxy_kernel.go_live_checklist.list" and bulk_go_live["summary"]["total"] >= 10, bulk_go_live
        bulk_materials = assert_ok(client.get("/v1/admin/proxy-kernels/materials-request", headers=headers))
        assert bulk_materials["object"] == "media2api.proxy_kernel.materials_request.list" and bulk_materials["summary"]["total"] >= 10, bulk_materials
        assert bulk_materials["summary"]["needs_account_materials"] >= 1 and bulk_materials["summary"]["needs_runtime_materials"] >= 1, bulk_materials
        bulk_runtime_delivery = assert_ok(client.get("/v1/admin/proxy-kernels/runtime-delivery-plan", headers=headers))
        assert bulk_runtime_delivery["object"] == "media2api.proxy_kernel.runtime_delivery_plan.list" and bulk_runtime_delivery["summary"]["total"] >= 10, bulk_runtime_delivery
        assert bulk_runtime_delivery["policy"]["release_binary_first"] is True and bulk_runtime_delivery["summary"]["next_step_counts"], bulk_runtime_delivery
        activation_matrix = assert_ok(client.get("/v1/admin/proxy-kernels/activation-workflow", headers=headers))
        assert activation_matrix["object"] == "media2api.proxy_kernel.activation_workflow.list" and activation_matrix["summary"]["total"] >= 10, activation_matrix
        assert activation_matrix["summary"]["action_required"] >= 1 and activation_matrix["summary"]["needs_user_input"] >= 1, activation_matrix
        activation_dashboard = assert_ok(client.get("/v1/admin/proxy-kernels/production-activation-dashboard", headers=headers))
        assert activation_dashboard["object"] == "media2api.proxy_kernel.production_activation_dashboard", activation_dashboard
        assert activation_dashboard["summary"]["total"] >= 10 and activation_dashboard["policy"]["read_only"] is True, activation_dashboard
        assert activation_dashboard["policy"]["upstream_calls"] is False and activation_dashboard["policy"]["official_sdk_api"] == "forbidden", activation_dashboard
        openai_activation_dashboard = next((item for item in activation_dashboard["data"] if item["provider_id"] == "openai_web_session"), {})
        assert openai_activation_dashboard["next_action"]["id"] in {"route", "account", "runtime", "health", "live_acceptance", "user_api_key", "ready"}, openai_activation_dashboard
        assert openai_activation_dashboard["plain_status"] and "parallel_actions" in openai_activation_dashboard, openai_activation_dashboard
        production_gap_matrix = assert_ok(client.get("/v1/admin/proxy-kernels/production-gap-report", headers=headers))
        assert production_gap_matrix["object"] == "media2api.proxy_kernel.production_gap_report.list" and production_gap_matrix["summary"]["total"] >= 10, production_gap_matrix
        assert production_gap_matrix["summary"]["ready_to_use"] == 0 and production_gap_matrix["summary"]["action_required"] >= 10, production_gap_matrix
        assert {"account", "runtime", "health", "live_acceptance"}.issubset(set(production_gap_matrix["summary"]["gap_counts"])), production_gap_matrix
        go_live_packages = assert_ok(client.get("/v1/admin/proxy-kernels/go-live-package", headers=headers))
        assert go_live_packages["object"] == "media2api.proxy_kernel.go_live_package.list" and go_live_packages["summary"]["total"] >= 10, go_live_packages
        assert go_live_packages["summary"]["ready_to_call"] == 0 and go_live_packages["summary"]["missing_external_input_count"] >= 10, go_live_packages
        assert go_live_packages["policy"]["read_only"] is True and go_live_packages["policy"]["release_binary_first"] is True, go_live_packages
        live_workspace = assert_ok(
            client.post(
                "/v1/admin/proxy-kernels/live-workspace",
                headers=headers,
                json={
                    "dry_run": True,
                    "prepare_routing": True,
                    "include_release_candidates": True,
                    "resolve_release_candidates": False,
                    "install_release_candidates": False,
                    "sync_source_repos": True,
                    "sync_source_repos_only_when_needed": True,
                    "resolve_source_repo_release_state": False,
                    "run_loopback_contract": False,
                },
            )
        )
        assert live_workspace["object"] == "media2api.proxy_kernel.live_workspace" and live_workspace["dry_run"] is True, live_workspace
        assert live_workspace["summary"]["total"] >= 10 and live_workspace["policy"]["downloaded_binaries"] is False, live_workspace
        assert live_workspace["policy"]["official_sdk_api"] == "forbidden" and live_workspace["routing"]["dry_run"] is True, live_workspace
        assert live_workspace["source_repo_sync"]["object"] == "media2api.proxy_kernel.source_repo_sync_matrix", live_workspace
        assert live_workspace["source_repo_sync"]["summary"]["needs_release_resolution"] >= 10, live_workspace
        release_probe_matrix = assert_ok(client.get("/v1/admin/proxy-kernels/release-probe-matrix?dry_run=true", headers=headers))
        assert release_probe_matrix["object"] == "media2api.proxy_kernel.release_probe_matrix" and release_probe_matrix["dry_run"] is True, release_probe_matrix
        assert release_probe_matrix["summary"]["total"] >= 10 and release_probe_matrix["summary"]["planned"] >= 10, release_probe_matrix
        assert release_probe_matrix["policy"]["release_binary_first"] is True and release_probe_matrix["policy"]["downloaded"] is False, release_probe_matrix
        release_checksum_matrix = assert_ok(client.get("/v1/admin/proxy-kernels/release-checksum-matrix?dry_run=true", headers=headers))
        assert release_checksum_matrix["object"] == "media2api.proxy_kernel.release_checksum_matrix" and release_checksum_matrix["dry_run"] is True, release_checksum_matrix
        assert release_checksum_matrix["summary"]["total"] >= 10 and release_checksum_matrix["summary"]["planned"] >= 10, release_checksum_matrix
        assert release_checksum_matrix["policy"]["hash_required"] is True and release_checksum_matrix["policy"]["downloaded_binaries"] is False, release_checksum_matrix
        runtime_acquisition_matrix = assert_ok(client.get("/v1/admin/proxy-kernels/runtime-acquisition-plan?resolve_release=false", headers=headers))
        assert runtime_acquisition_matrix["object"] == "media2api.proxy_kernel.runtime_acquisition_plan.list", runtime_acquisition_matrix
        assert runtime_acquisition_matrix["summary"]["total"] >= 10 and runtime_acquisition_matrix["resolve_release"] is False, runtime_acquisition_matrix
        assert runtime_acquisition_matrix["policy"]["release_binary_first"] is True and runtime_acquisition_matrix["policy"]["synced_source_repo"] is False, runtime_acquisition_matrix
        assert runtime_acquisition_matrix["summary"]["next_action_counts"].get("resolve_release", 0) >= 10, runtime_acquisition_matrix
        release_candidate_install_matrix = assert_ok(client.post("/v1/admin/proxy-kernels/install-release-candidates", headers=headers, json={"dry_run": True, "resolve_release": False}))
        assert release_candidate_install_matrix["object"] == "media2api.proxy_kernel.release_candidate_install_matrix" and release_candidate_install_matrix["dry_run"] is True, release_candidate_install_matrix
        assert release_candidate_install_matrix["summary"]["total"] >= 10 and release_candidate_install_matrix["summary"]["planned"] >= 10, release_candidate_install_matrix
        assert release_candidate_install_matrix["policy"]["hash_required"] is True and release_candidate_install_matrix["policy"]["downloaded_binaries"] is False, release_candidate_install_matrix
        source_repo_sync_plan = assert_ok(client.post("/v1/admin/proxy-kernels/source-repo/sync", headers=headers, json={"dry_run": True, "only_when_needed": False, "resolve_release": False}))
        assert source_repo_sync_plan["object"] == "media2api.proxy_kernel.source_repo_sync_matrix" and source_repo_sync_plan["dry_run"] is True, source_repo_sync_plan
        assert source_repo_sync_plan["summary"]["total"] >= 10 and source_repo_sync_plan["summary"]["planned"] >= 10, source_repo_sync_plan
        assert source_repo_sync_plan["policy"]["release_binary_first"] is True and source_repo_sync_plan["policy"]["read_only"] is True, source_repo_sync_plan
        runtime_contract_matrix = assert_ok(client.get("/v1/admin/proxy-kernels/runtime-contract-matrix", headers=headers))
        assert runtime_contract_matrix["object"] == "media2api.proxy_kernel.runtime_contract_matrix" and runtime_contract_matrix["summary"]["total"] >= 10, runtime_contract_matrix
        assert runtime_contract_matrix["summary"]["contract_ready"] >= 10 and runtime_contract_matrix["summary"]["endpoint_complete"] >= 10, runtime_contract_matrix
        assert runtime_contract_matrix["policy"]["official_sdk_api"] == "forbidden" and "/v1/images/*" in runtime_contract_matrix["policy"]["public_api_priority"], runtime_contract_matrix
        production_readiness_matrix = assert_ok(client.get("/v1/admin/proxy-kernels/production-readiness-matrix", headers=headers))
        assert production_readiness_matrix["object"] == "media2api.proxy_kernel.production_readiness_matrix" and production_readiness_matrix["summary"]["total"] >= 10, production_readiness_matrix
        assert production_readiness_matrix["policy"]["requires_real_acceptance_samples"] is True and production_readiness_matrix["summary"]["production_ready"] == 0, production_readiness_matrix
        assert {"runtime", "account", "health", "live_acceptance"}.issubset(set(production_readiness_matrix["summary"]["phase_blockers"])), production_readiness_matrix
        loopback_contract = assert_ok(client.post("/v1/admin/proxy-kernels/loopback-contract-test", headers=headers, json={"operations": ["text_to_image", "image_edit", "text_to_video"]}))
        assert loopback_contract["object"] == "media2api.proxy_kernel.loopback_contract_test" and loopback_contract["ok"] is True, loopback_contract
        assert {"text_to_image", "image_edit", "text_to_video"}.issubset({item["operation"] for item in loopback_contract["jobs"]}), loopback_contract
        assert {"/v1/images/generations", "/v1/images/edits", "/v1/videos/generations"}.issubset({item["path"] for item in loopback_contract["runner_requests"]}), loopback_contract
        openai_web_kernel = assert_ok(client.get("/v1/admin/proxy-kernels/openai_web_session", headers=headers))
        assert openai_web_kernel["selection_id"] == "OAI-WEB-01" and openai_web_kernel["spec"]["install_policy"]["hash_required"] is True, openai_web_kernel
        openai_go_live = assert_ok(client.get("/v1/admin/proxy-kernels/openai_web_session/go-live-checklist", headers=headers))
        assert openai_go_live["object"] == "media2api.proxy_kernel.go_live_checklist" and "apply_routing" in openai_go_live["commands"], openai_go_live
        assert "live_acceptance" in openai_go_live["commands"], openai_go_live
        assert {"routing", "runtime", "account", "live_acceptance"}.issubset({step["id"] for step in openai_go_live["steps"]}), openai_go_live
        openai_materials = assert_ok(client.get("/v1/admin/proxy-kernels/openai_web_session/materials-request", headers=headers))
        assert openai_materials["object"] == "media2api.proxy_kernel.materials_request" and openai_materials["required_materials"], openai_materials
        assert {"account_materials", "runtime_materials", "routing_materials", "validation_materials", "message_to_user"}.issubset(set(openai_materials)), openai_materials
        assert "live_acceptance" in openai_materials["commands"], openai_materials
        assert openai_materials["policy"]["official_sdk_api"] == "forbidden" and openai_materials["policy"]["read_only"] is True, openai_materials
        account_materials_matrix = assert_ok(client.get("/v1/admin/proxy-kernels/account-materials-matrix", headers=headers))
        assert account_materials_matrix["object"] == "media2api.proxy_kernel.account_materials_matrix", account_materials_matrix
        assert account_materials_matrix["summary"]["total"] >= 10 and account_materials_matrix["summary"]["needs_account_material"] >= 1, account_materials_matrix
        assert account_materials_matrix["policy"]["release_binary_first"] is True and account_materials_matrix["policy"]["source_repo_only_when_needed"] is True, account_materials_matrix
        openai_matrix = next(item for item in account_materials_matrix["data"] if item["provider_id"] == "openai_web_session")
        assert openai_matrix["selection_id"] == "OAI-WEB-01" and openai_matrix["next_action"]["id"] == "import_account_material", openai_matrix
        assert openai_matrix["credential_value_json_template"].get("chatgpt_cookie_or_session"), openai_matrix
        assert any(section["id"] == "credential_value" and section["field_count"] >= 1 for section in openai_matrix["what_to_prepare"]), openai_matrix
        gemini_matrix = next(item for item in account_materials_matrix["data"] if item["provider_id"] == "gemini_cli_oauth")
        assert gemini_matrix["runtime_credential_sync"]["status"] != "unsupported" and gemini_matrix["credential_value_json_template"], gemini_matrix
        account_connection_package = assert_ok(client.get("/v1/admin/proxy-kernels/account-connection-package?provider_ids=openai_web_session,gemini_cli_oauth", headers=headers))
        assert account_connection_package["object"] == "media2api.proxy_kernel.account_connection_package", account_connection_package
        assert account_connection_package["summary"]["total"] == 2 and account_connection_package["summary"]["needs_account_material"] == 2, account_connection_package
        assert account_connection_package["policy"]["official_sdk_api"] == "forbidden" and account_connection_package["bulk_submission_json_template"]["dry_run"] is True, account_connection_package
        placeholder_bulk = assert_ok(client.post("/v1/admin/proxy-kernels/account-materials-bulk", headers=headers, json=account_connection_package["bulk_submission_json_template"]))
        assert placeholder_bulk["status"] == "needs_input" and placeholder_bulk["summary"]["processed"] == 2 and placeholder_bulk["summary"]["failed"] == 0, placeholder_bulk
        ready_bulk = assert_ok(
            client.post(
                "/v1/admin/proxy-kernels/account-materials-bulk",
                headers=headers,
                json={
                    "dry_run": True,
                    "items": [
                        {"provider_id": "openai_web_session", "credential_value": {"chatgpt_cookie_or_session": "fake-cookie-for-shape-check-only"}},
                        {"provider_id": "gemini_cli_oauth", "credential_value": {"gemini_oauth_creds_file": {"token": {"refresh_token": "fake-refresh-token"}, "email": "smoke@example.com"}}},
                    ],
                },
            )
        )
        assert ready_bulk["status"] == "ready_to_import" and ready_bulk["summary"]["ready"] == 2 and ready_bulk["summary"]["imported"] == 0, ready_bulk
        openai_account_materials = assert_ok(client.get("/v1/admin/proxy-kernels/openai_web_session/account-materials", headers=headers))
        assert openai_account_materials["object"] == "media2api.proxy_kernel.account_materials" and openai_account_materials["provider_id"] == "openai_web_session", openai_account_materials
        assert openai_account_materials["status"] == "needs_input" and openai_account_materials["credential_value_json_template"], openai_account_materials
        assert openai_account_materials["resource_profile_json_template"] == {}, openai_account_materials
        assert "credential_value" in openai_account_materials["fields_by_destination"], openai_account_materials
        openai_account_missing = assert_ok(client.post("/v1/admin/proxy-kernels/openai_web_session/account-materials", headers=headers, json={"dry_run": True}))
        assert openai_account_missing["preflight"]["ok"] is False and openai_account_missing["preflight"]["missing_input_fields"], openai_account_missing
        openai_account_placeholder = assert_ok(
            client.post(
                "/v1/admin/proxy-kernels/openai_web_session/account-materials",
                headers=headers,
                json={"dry_run": True, "credential_value": openai_account_materials["credential_value_json_template"]},
            )
        )
        assert openai_account_placeholder["preflight"]["ok"] is False and openai_account_placeholder["preflight"]["error"] == "CREDENTIAL_PLACEHOLDER_VALUE", openai_account_placeholder
        openai_account_ready = assert_ok(
            client.post(
                "/v1/admin/proxy-kernels/openai_web_session/account-materials",
                headers=headers,
                json={"dry_run": True, "credential_value": {"chatgpt_cookie_or_session": "fake-cookie-for-shape-check-only"}},
            )
        )
        assert openai_account_ready["preflight"]["ok"] is True and openai_account_ready["payload_preview"]["credential_value"] == "[provided]", openai_account_ready
        midjourney_account_materials = assert_ok(client.get("/v1/admin/proxy-kernels/midjourney_discord_session/account-materials", headers=headers))
        assert midjourney_account_materials["credential_value_json_template"].get("discord_session_or_user_token"), midjourney_account_materials
        assert "guild_id" not in midjourney_account_materials["credential_value_json_template"], midjourney_account_materials
        assert midjourney_account_materials["resource_profile_json_template"].get("guild_id") == "<required>", midjourney_account_materials
        assert midjourney_account_materials["resource_profile_json_template"].get("channel_id") == "<required>", midjourney_account_materials
        assert {item["section"] for item in midjourney_account_materials["field_instructions"]} >= {"credential_value", "resource_profile"}, midjourney_account_materials
        midjourney_account_ready = assert_ok(
            client.post(
                "/v1/admin/proxy-kernels/midjourney_discord_session/account-materials",
                headers=headers,
                json={
                    "dry_run": True,
                    "credential_value": {"discord_session_or_user_token": "fake-discord-session"},
                    "resource_profile": {"guild_id": "123456789012345678", "channel_id": "234567890123456789"},
                    "supported_operations": ["text_to_image", "image_to_image"],
                    "supported_provider_models": ["mj-v7"],
                    "concurrency_limit": 1,
                },
            )
        )
        assert midjourney_account_ready["preflight"]["ok"] is True and midjourney_account_ready["payload_preview"]["resource_profile"]["guild_id"] == "123456789012345678", midjourney_account_ready
        handoff_matrix = assert_ok(client.get("/v1/admin/proxy-kernels/operator-handoff", headers=headers))
        assert handoff_matrix["object"] == "media2api.proxy_kernel.operator_handoff.list" and handoff_matrix["summary"]["total"] >= 10, handoff_matrix
        openai_handoff = assert_ok(client.get("/v1/admin/proxy-kernels/openai_web_session/operator-handoff", headers=headers))
        assert openai_handoff["object"] == "media2api.proxy_kernel.operator_handoff" and openai_handoff["provider_id"] == "openai_web_session", openai_handoff
        assert {"account_onboarding_inline_secret", "install_release", "source_runtime_plan", "source_runtime_setup", "source_runtime_launcher", "start_runtime", "live_acceptance_dry_run"}.issubset(openai_handoff["submission_templates"]), openai_handoff
        assert "operator_handoff_run" in openai_handoff["submission_templates"], openai_handoff
        assert {"source_runtime_setup", "source_runtime_launcher"}.issubset({step["id"] for step in openai_handoff["steps"]}), openai_handoff
        assert "source_runtime_setup" in openai_handoff["submission_templates"]["operator_handoff_run"], openai_handoff
        assert openai_handoff["policy"]["read_only"] is True and openai_handoff["policy"]["release_binary_preferred"] is True, openai_handoff
        handoff_run = assert_ok(
            client.post(
                "/v1/admin/proxy-kernels/openai_web_session/operator-handoff/run",
                headers=headers,
                json={"dry_run": True},
            )
        )
        assert handoff_run["object"] == "media2api.proxy_kernel.operator_handoff_run" and handoff_run["dry_run"] is True, handoff_run
        assert all(item["status"] == "planned" for item in handoff_run["results"]), handoff_run
        assert {"source_runtime_setup", "source_runtime_launcher"}.issubset({item["step"] for item in handoff_run["results"]}), handoff_run
        openai_runtime_delivery = assert_ok(client.get("/v1/admin/proxy-kernels/openai_web_session/runtime-delivery-plan", headers=headers))
        assert openai_runtime_delivery["object"] == "media2api.proxy_kernel.runtime_delivery_plan" and openai_runtime_delivery["provider_id"] == "openai_web_session", openai_runtime_delivery
        assert {"install_payload_template", "start_payload_template", "preflight_payload_template", "start_command_candidates", "source_repo_payload_template"}.issubset(openai_runtime_delivery["runtime"]), openai_runtime_delivery
        assert openai_runtime_delivery["runtime"]["start_payload_template"]["run_health_check"] is True, openai_runtime_delivery
        assert openai_runtime_delivery["runtime"]["preflight_payload_template"]["timeout_seconds"] == 8, openai_runtime_delivery
        assert openai_runtime_delivery["runtime"]["start_command_candidates"], openai_runtime_delivery
        assert "runtime_health_check" in openai_runtime_delivery["commands"], openai_runtime_delivery
        assert "runtime_preflight" in openai_runtime_delivery["commands"], openai_runtime_delivery
        assert openai_runtime_delivery["policy"]["preferred_runtime_source"] == "release_binary" and openai_runtime_delivery["policy"]["read_only"] is True, openai_runtime_delivery
        gemini_runtime_delivery = assert_ok(client.get("/v1/admin/proxy-kernels/gemini_cli_oauth/runtime-delivery-plan", headers=headers))
        assert gemini_runtime_delivery["runtime"]["start_template_id"] == "cliproxyapi_config_standalone", gemini_runtime_delivery
        assert gemini_runtime_delivery["runtime"]["start_payload_template"]["config_files"], gemini_runtime_delivery
        assert "-config" in gemini_runtime_delivery["runtime"]["start_payload_template"]["command"], gemini_runtime_delivery
        openai_activation = assert_ok(client.get("/v1/admin/proxy-kernels/openai_web_session/activation-workflow", headers=headers))
        assert openai_activation["object"] == "media2api.proxy_kernel.activation_workflow" and openai_activation["provider_id"] == "openai_web_session", openai_activation
        assert {"route", "account", "runtime", "health", "live_acceptance", "user_api_key"}.issubset({stage["id"] for stage in openai_activation["stages"]}), openai_activation
        assert openai_activation["next_stage"]["id"] in {"route", "account", "runtime", "health", "live_acceptance", "user_api_key"}, openai_activation
        assert openai_activation["policy"]["official_sdk_api"] == "forbidden" and openai_activation["policy"]["release_binary_preferred"] is True, openai_activation
        assert "/v1/images/generations" in openai_activation["sample_requests"]["image_generation"]["url"], openai_activation
        openai_gap_report = assert_ok(client.get("/v1/admin/proxy-kernels/openai_web_session/production-gap-report", headers=headers))
        assert openai_gap_report["object"] == "media2api.proxy_kernel.production_gap_report" and openai_gap_report["provider_id"] == "openai_web_session", openai_gap_report
        assert openai_gap_report["ready_to_use"] is False and {"account", "runtime", "health", "live_acceptance"}.issubset(set(openai_gap_report["blocking_stages"])), openai_gap_report
        assert openai_gap_report["policy"]["ready_to_use_requires_user_api_key"] is True and openai_gap_report["policy"]["ready_to_use_requires_live_acceptance"] is True, openai_gap_report
        openai_go_live_package = assert_ok(client.get("/v1/admin/proxy-kernels/openai_web_session/go-live-package", headers=headers))
        assert openai_go_live_package["object"] == "media2api.proxy_kernel.go_live_package" and openai_go_live_package["provider_id"] == "openai_web_session", openai_go_live_package
        assert openai_go_live_package["ready_to_call"] is False and openai_go_live_package["missing_external_inputs"], openai_go_live_package
        assert {"routing", "account", "runtime", "health", "live_acceptance", "downstream_key", "call_downstream_api"}.issubset({step["id"] for step in openai_go_live_package["steps"]}), openai_go_live_package
        assert "credential_value_json_template" in openai_go_live_package["account_connection"] and "sample_requests" in openai_go_live_package["downstream_call"], openai_go_live_package
        assert openai_go_live_package["policy"]["admin_bootstrap_key_is_not_downstream_key"] is True, openai_go_live_package
        openai_activation_run = assert_ok(
            client.post(
                "/v1/admin/proxy-kernels/openai_web_session/activation-run",
                headers=headers,
                json={"dry_run": True, "steps": ["apply_routing", "submit_account_material", "runtime_health_check", "user_api_key"]},
            )
        )
        assert openai_activation_run["object"] == "media2api.proxy_kernel.activation_run" and openai_activation_run["dry_run"] is True, openai_activation_run
        assert openai_activation_run["status"] in {"planned", "failed"} and openai_activation_run["after_gap_report"]["object"] == "media2api.proxy_kernel.production_gap_report", openai_activation_run
        assert {"apply_routing", "submit_account_material", "runtime_health_check", "user_api_key"}.issubset(set(openai_activation_run["requested_steps"])), openai_activation_run
        downstream_packages = assert_ok(client.get("/v1/admin/proxy-kernels/downstream-call-package", headers=headers))
        assert downstream_packages["object"] == "media2api.proxy_kernel.downstream_call_package.list" and downstream_packages["summary"]["total"] >= 10, downstream_packages
        openai_downstream = assert_ok(client.get("/v1/admin/proxy-kernels/openai_web_session/downstream-call-package", headers=headers))
        assert openai_downstream["object"] == "media2api.proxy_kernel.downstream_call_package" and openai_downstream["provider_id"] == "openai_web_session", openai_downstream
        assert openai_downstream["ready_to_call"] is False and "user_api_key" in {item["stage"] for item in openai_downstream["blockers"]}, openai_downstream
        assert "/v1/images/generations" in openai_downstream["sample_requests"]["image_generation"]["url"], openai_downstream
        assert openai_downstream["policy"]["admin_bootstrap_key_is_not_downstream_key"] is True, openai_downstream
        openai_downstream_dry = assert_ok(
            client.post(
                "/v1/admin/proxy-kernels/openai_web_session/downstream-call-package",
                headers=headers,
                json={"dry_run": True, "create_user": True, "create_user_api_key": True, "user_id": "usr_openai_web_client", "user_email": "openai-web-client@example.com"},
            )
        )
        assert openai_downstream_dry["downstream_api_key"]["action"] == "planned_create" and openai_downstream_dry["downstream_api_key"]["plaintext_key_returned"] is False, openai_downstream_dry
        openai_release_checksums = assert_ok(client.get("/v1/admin/proxy-kernels/openai_web_session/release-checksums?dry_run=true", headers=headers))
        assert openai_release_checksums["object"] == "media2api.proxy_kernel.release_checksums" and openai_release_checksums["provider_id"] == "openai_web_session", openai_release_checksums
        assert openai_release_checksums["policy"]["hash_required"] is True and openai_release_checksums["policy"]["downloaded_binaries"] is False, openai_release_checksums
        openai_runtime_acquisition = assert_ok(client.get("/v1/admin/proxy-kernels/openai_web_session/runtime-acquisition-plan?resolve_release=false", headers=headers))
        assert openai_runtime_acquisition["object"] == "media2api.proxy_kernel.runtime_acquisition_plan", openai_runtime_acquisition
        assert openai_runtime_acquisition["provider_id"] == "openai_web_session" and openai_runtime_acquisition["resolve_release"] is False, openai_runtime_acquisition
        assert openai_runtime_acquisition["decision"]["preferred_path"] == "release_binary", openai_runtime_acquisition
        assert openai_runtime_acquisition["decision"]["synced_source_repo"] is False and openai_runtime_acquisition["policy"]["downloaded_binaries"] is False, openai_runtime_acquisition
        assert openai_runtime_acquisition["next_action"]["id"] == "resolve_release", openai_runtime_acquisition
        openai_install_candidate = assert_ok(client.post("/v1/admin/proxy-kernels/openai_web_session/install-release-candidate", headers=headers, json={"dry_run": True, "resolve_release": False}))
        assert openai_install_candidate["object"] == "media2api.proxy_kernel.release_candidate_install" and openai_install_candidate["status"] == "planned", openai_install_candidate
        assert openai_install_candidate["policy"]["hash_required"] is True and openai_install_candidate["policy"]["downloaded_binaries"] is False, openai_install_candidate
        openai_runtime_contract = assert_ok(client.get("/v1/admin/proxy-kernels/openai_web_session/runtime-contract", headers=headers))
        assert openai_runtime_contract["object"] == "media2api.proxy_kernel.runtime_contract" and openai_runtime_contract["provider_id"] == "openai_web_session", openai_runtime_contract
        assert openai_runtime_contract["adapter_contract"]["endpoints"]["text_to_image"] == "/v1/images/generations", openai_runtime_contract
        assert openai_runtime_contract["policy"]["official_sdk_api"] == "forbidden" and openai_runtime_contract["contract_ready"] is True, openai_runtime_contract
        openai_production_readiness = assert_ok(client.get("/v1/admin/proxy-kernels/openai_web_session/production-readiness", headers=headers))
        assert openai_production_readiness["object"] == "media2api.proxy_kernel.production_readiness" and openai_production_readiness["provider_id"] == "openai_web_session", openai_production_readiness
        assert openai_production_readiness["policy"]["requires_real_acceptance_samples"] is True and openai_production_readiness["production_ready"] is False, openai_production_readiness
        assert "live_acceptance" in openai_production_readiness["commands"], openai_production_readiness
        assert {"routing", "runtime_contract", "runtime", "account", "health", "live_acceptance"}.issubset({phase["id"] for phase in openai_production_readiness["phases"]}), openai_production_readiness
        openai_live_acceptance_dry_run = assert_ok(
            client.post(
                "/v1/admin/proxy-kernels/openai_web_session/live-acceptance",
                headers=headers,
                json={"dry_run": True, "operations": ["text_to_image"], "run_samples": True, "max_samples": 1},
            )
        )
        assert openai_live_acceptance_dry_run["object"] == "media2api.proxy_kernel.live_acceptance", openai_live_acceptance_dry_run
        assert openai_live_acceptance_dry_run["dry_run"] is True and openai_live_acceptance_dry_run["operations"] == ["text_to_image"], openai_live_acceptance_dry_run
        assert openai_live_acceptance_dry_run["policy"]["default_mode"] == "dry_run" and openai_live_acceptance_dry_run["runtime_health_check"]["status"] == "skipped_dry_run", openai_live_acceptance_dry_run
        source_repo = assert_ok(client.get("/v1/admin/proxy-kernels/openai_web_session/source-repo", headers=headers))
        assert source_repo["object"] == "media2api.proxy_kernel.source_repo" and source_repo["repo"] == "basketikun/chatgpt2api" and "source-repo" in source_repo["path"], source_repo
        connector_refresh = assert_ok(client.post("/v1/admin/connector-registry/refresh", headers=headers, json={}))
        assert connector_refresh["object"] == "connector_registry.refresh" and connector_refresh["status"] == "ok", connector_refresh
        assert Path(connector_refresh["path"]).resolve() == SOURCE_REPO_DIR.resolve(), connector_refresh
        source_runtime_plan = assert_ok(client.get("/v1/admin/proxy-kernels/openai_web_session/source-runtime-plan?base_url=http://127.0.0.1:19081", headers=headers))
        assert source_runtime_plan["object"] == "media2api.proxy_kernel.source_runtime_plan" and source_runtime_plan["source_available"] is True, source_runtime_plan
        assert {"node", "python"}.issubset(set(source_runtime_plan["detected_project_types"])) and source_runtime_plan["preferred_start_command"]["command"][:3] == ["npm", "run", "start"], source_runtime_plan
        assert any(item["id"] == "pip_install_requirements" for item in source_runtime_plan["dependency_commands"]), source_runtime_plan
        source_runtime_matrix = assert_ok(client.get("/v1/admin/proxy-kernels/source-runtime-plan", headers=headers))
        assert source_runtime_matrix["object"] == "media2api.proxy_kernel.source_runtime_plan_matrix", source_runtime_matrix
        assert source_runtime_matrix["summary"]["total"] >= 10 and source_runtime_matrix["policy"]["read_only"] is True, source_runtime_matrix
        openai_source_row = next((item for item in source_runtime_matrix["data"] if item["provider_id"] == "openai_web_session"), {})
        assert openai_source_row["source_available"] is True and openai_source_row["next_action"]["id"] == "source_runtime_setup", openai_source_row
        assert openai_source_row["candidate_summary"]["start_command_count"] >= 1, openai_source_row
        source_setup_dry_run = assert_ok(
            client.post(
                "/v1/admin/proxy-kernels/openai_web_session/source-runtime-setup",
                headers=headers,
                json={"dry_run": True, "command_id": "pip_install_requirements"},
            )
        )
        assert source_setup_dry_run["dry_run"] is True and source_setup_dry_run["status"] == "planned" and source_setup_dry_run["command_id"] == "pip_install_requirements", source_setup_dry_run
        source_setup = assert_ok(
            client.post(
                "/v1/admin/proxy-kernels/openai_web_session/source-runtime-setup",
                headers=headers,
                json={"dry_run": False, "command_id": "pip_install_requirements", "timeout_seconds": 60, "notes": "smoke source setup"},
            )
        )
        assert source_setup["status"] == "completed" and source_setup["exit_code"] == 0, source_setup
        assert Path(source_setup["stdout_log"]).exists() and Path(source_setup["stderr_log"]).exists(), source_setup
        source_launcher_dry_run = assert_ok(
            client.post(
                "/v1/admin/proxy-kernels/openai_web_session/source-runtime-launcher",
                headers=headers,
                json={"dry_run": True, "base_url": "http://127.0.0.1:19081"},
            )
        )
        assert source_launcher_dry_run["dry_run"] is True and source_launcher_dry_run["start_payload_template"]["command"], source_launcher_dry_run
        source_launcher = assert_ok(
            client.post(
                "/v1/admin/proxy-kernels/openai_web_session/source-runtime-launcher",
                headers=headers,
                json={"dry_run": False, "base_url": "http://127.0.0.1:19081", "notes": "smoke source launcher"},
            )
        )
        launcher_path = Path(source_launcher["launcher"]["path"])
        assert source_launcher["object"] == "media2api.proxy_kernel.source_runtime_launcher" and launcher_path.exists(), source_launcher
        assert launcher_path.is_absolute(), source_launcher
        assert str(launcher_path.resolve()).startswith(str(PROXY_KERNEL_DIR.resolve())) and hashlib.sha256(launcher_path.read_bytes()).hexdigest() == source_launcher["launcher"]["sha256"], source_launcher
        start_payload = source_launcher["start_payload_template"]
        assert start_payload["artifact_path"] == str(launcher_path) and Path(start_payload["artifact_path"]).is_absolute(), source_launcher
        assert start_payload["command"][1] == str(launcher_path) and Path(start_payload["cwd"]).is_absolute(), source_launcher
        extract_service = ProxyKernelRuntimeService(root=PROXY_KERNEL_DIR / "extract-smoke")
        extract_install_dir = extract_service.root / "openai_web_session" / "archive-smoke"
        extract_install_dir.mkdir(parents=True, exist_ok=True)
        archive_path = extract_install_dir / "runner.tar.gz"
        runner_bytes = b"#!/bin/sh\necho media2api archive runner\n"
        with tarfile.open(archive_path, "w:gz") as archive:
            root_dir = tarfile.TarInfo(".")
            root_dir.type = tarfile.DIRTYPE
            root_dir.mode = 0o755
            archive.addfile(root_dir)
            info = tarfile.TarInfo("bin/runner")
            info.size = len(runner_bytes)
            info.mode = 0o755
            archive.addfile(info, BytesIO(runner_bytes))
            cname_bytes = b"example.invalid\n"
            cname = tarfile.TarInfo("wwwroot/CNAME")
            cname.size = len(cname_bytes)
            cname.mode = 0o644
            archive.addfile(cname, BytesIO(cname_bytes))
        empty_extract_dir = extract_install_dir / f"{extract_service.safe_filename(archive_path.name)}.extracted-{hashlib.sha256(archive_path.read_bytes()).hexdigest()[:12]}"
        empty_extract_dir.mkdir(parents=True, exist_ok=True)
        extraction = extract_service.extract_release_asset("openai_web_session", archive_path, extract_install_dir)
        assert extraction["archive_extracted"] is True and extraction["archive_kind"] == "tar", extraction
        assert extraction["extracted_file_count"] >= 1, extraction
        assert extraction["executable_candidates"] and extraction["executable_candidates"][0]["relative_path"] == "bin/runner", extraction
        assert all(item["relative_path"] != "wwwroot/CNAME" for item in extraction["executable_candidates"]), extraction
        assert extraction["executable_candidates"][0]["sha256"] == hashlib.sha256(runner_bytes).hexdigest(), extraction
        unsafe_archive_path = extract_install_dir / "unsafe.tar.gz"
        with tarfile.open(unsafe_archive_path, "w:gz") as archive:
            info = tarfile.TarInfo("../escape")
            info.size = len(runner_bytes)
            info.mode = 0o755
            archive.addfile(info, BytesIO(runner_bytes))
        try:
            extract_service.extract_release_asset("openai_web_session", unsafe_archive_path, extract_install_dir)
            raise AssertionError("unsafe archive member was not rejected")
        except ValueError as exc:
            assert "ARCHIVE_MEMBER_OUTSIDE_EXTRACT_DIR" in str(exc), exc
        routing_plan = assert_ok(client.get("/v1/admin/proxy-kernels/openai_web_session/routing-plan", headers=headers))
        assert routing_plan["object"] == "media2api.proxy_kernel.routing_plan" and routing_plan["template_mapping_count"] >= 1, routing_plan
        routing_apply = assert_ok(
            client.post(
                "/v1/admin/proxy-kernels/openai_web_session/apply-routing",
                headers=headers,
                json={"status": "active", "enable_mappings": True, "priority_offset": 0, "update_provider_base_url": True},
            )
        )
        assert routing_apply["object"] == "media2api.proxy_kernel.routing_apply" and routing_apply["no_fake_account_created"] is True, routing_apply
        assert routing_apply["routing_plan"]["enabled_mapping_count"] >= 1, routing_apply
        class KernelHealthHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                if self.path == "/health":
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(b'{"status":"ok","object":"runtime.health.smoke"}')
                    return
                self.send_response(404)
                self.end_headers()

            def log_message(self, fmt: str, *args: object) -> None:
                return

        health_server = HTTPServer(("127.0.0.1", 0), KernelHealthHandler)
        health_thread = threading.Thread(target=health_server.serve_forever, daemon=True)
        health_thread.start()
        health_base_url = f"http://127.0.0.1:{health_server.server_address[1]}"
        try:
            registered_runtime = assert_ok(
                client.post(
                    "/v1/admin/proxy-kernels/openai_web_session/register-runtime",
                    headers=headers,
                    json={"base_url": health_base_url, "version": "health-smoke", "notes": "health smoke", "update_provider_base_url": True},
                )
            )
            assert registered_runtime["runtime"]["base_url"] == health_base_url, registered_runtime
            runtime_health = assert_ok(
                client.post(
                    "/v1/admin/proxy-kernels/openai_web_session/runtime-health-check",
                    headers=headers,
                    json={"sync_provider_base_url": True, "require_running_process": False, "fail_on_health_check": False},
                )
            )
            assert runtime_health["object"] == "media2api.proxy_kernel.runtime_health_check" and runtime_health["ok"] is True, runtime_health
            assert runtime_health["health_check"]["status"] == "ok" and runtime_health["runtime"]["base_url"] == health_base_url, runtime_health
        finally:
            health_server.shutdown()
            health_server.server_close()
            health_thread.join(timeout=2)
            assert_ok(client.post("/v1/admin/proxy-kernels/openai_web_session/clear-runtime", headers=headers))
        runtime_dir = settings.proxy_kernel_dir / "openai_web_session" / "smoke"
        runtime_dir.mkdir(parents=True, exist_ok=True)
        runtime_script = runtime_dir / "sleep_runtime.py"
        runtime_script.write_text("import time\nprint('media2api smoke runtime ready', flush=True)\ntime.sleep(60)\n", encoding="utf-8")
        runtime_config = runtime_dir / "runtime-config.txt"
        runtime_sha256 = hashlib.sha256(runtime_script.read_bytes()).hexdigest()
        try:
            runtime_start = assert_ok(
                client.post(
                    "/v1/admin/proxy-kernels/openai_web_session/start-runtime",
                    headers=headers,
                    json={
                        "command": [sys.executable, str(runtime_script)],
                        "base_url": "http://127.0.0.1:19081",
                        "artifact_path": str(runtime_script),
                        "expected_sha256": runtime_sha256,
                        "config_files": [{"path": str(runtime_config), "content": "smoke-runtime-config=true\n"}],
                        "version": "smoke",
                        "notes": "smoke controlled runtime",
                        "replace_existing": True,
                        "update_provider_base_url": False,
                        "run_health_check": False,
                        "fail_on_health_check": False,
                    },
                )
            )
            assert runtime_start["process"]["running"] is True and runtime_start["runtime"]["sha256"] == runtime_sha256, runtime_start
            assert runtime_config.exists() and runtime_config.read_text(encoding="utf-8") == "smoke-runtime-config=true\n", runtime_start
            assert runtime_start["process"]["config_files"][0]["path"] == str(runtime_config), runtime_start
            runtime_process = assert_ok(client.get("/v1/admin/proxy-kernels/openai_web_session/process", headers=headers))
            assert runtime_process["process"]["running"] is True, runtime_process
            runtime_logs = assert_ok(client.get("/v1/admin/proxy-kernels/openai_web_session/logs?stream=stdout", headers=headers))
            assert runtime_logs["object"] == "media2api.proxy_kernel.logs" and runtime_logs["path"], runtime_logs
        finally:
            runtime_stop = assert_ok(client.post("/v1/admin/proxy-kernels/openai_web_session/stop-runtime", headers=headers, json={"grace_seconds": 1}))
            assert runtime_stop["process"]["running"] is False, runtime_stop
        gemini_runtime_dir = settings.proxy_kernel_dir / "gemini_cli_oauth" / "smoke"
        gemini_runtime_dir.mkdir(parents=True, exist_ok=True)
        gemini_runtime_script = gemini_runtime_dir / "sleep_runtime.py"
        gemini_runtime_script.write_text("import time\nprint('gemini runtime smoke ready', flush=True)\ntime.sleep(60)\n", encoding="utf-8")
        gemini_runtime_config = gemini_runtime_dir / "config.yaml"
        gemini_auth_dir = gemini_runtime_dir / "auth"
        gemini_runtime_sha256 = hashlib.sha256(gemini_runtime_script.read_bytes()).hexdigest()
        try:
            gemini_runtime_start = assert_ok(
                client.post(
                    "/v1/admin/proxy-kernels/gemini_cli_oauth/start-runtime",
                    headers=headers,
                    json={
                        "command": [sys.executable, str(gemini_runtime_script)],
                        "base_url": "http://127.0.0.1:19083",
                        "artifact_path": str(gemini_runtime_script),
                        "expected_sha256": gemini_runtime_sha256,
                        "config_files": [{"path": str(gemini_runtime_config), "content": f'auth-dir: "{gemini_auth_dir.as_posix()}"\n'}],
                        "version": "smoke",
                        "notes": "gemini runtime credential sync smoke",
                        "replace_existing": True,
                        "update_provider_base_url": False,
                    },
                )
            )
            assert gemini_runtime_start["process"]["running"] is True, gemini_runtime_start
            gemini_credential_value = {
                "gemini_oauth_creds_file": {
                    "access_token": "fake-access-token",
                    "refresh_token": "fake-refresh-token",
                    "client_id": "smoke-oauth-client",
                    "client_secret": "smoke-oauth-secret",
                    "email": "smoke@example.com",
                    "project_id": "smoke-project",
                }
            }
            gemini_account = assert_ok(
                client.post(
                    "/v1/admin/proxy-kernels/gemini_cli_oauth/account-materials",
                    headers=headers,
                    json={
                        "dry_run": False,
                        "account_id": "acct_gemini_runtime_sync_smoke",
                        "label": "Gemini Runtime Sync Smoke",
                        "credential_value": gemini_credential_value,
                        "supported_operations": ["text_to_image", "text_to_video"],
                        "supported_provider_models": ["nano-banana-pro", "veo-3.1"],
                        "concurrency_limit": 1,
                        "upsert": True,
                        "auto_create_mappings": True,
                        "sync_capabilities": False,
                        "run_health_check": False,
                    },
                )
            )
            runtime_sync = gemini_account["runtime_credential_sync"]
            assert runtime_sync["ok"] is True and runtime_sync["status"] == "synced", runtime_sync
            auth_file = Path(runtime_sync["file"]["path"])
            assert auth_file.exists() and auth_file.parent == gemini_auth_dir, runtime_sync
            auth_json = json.loads(auth_file.read_text(encoding="utf-8"))
            assert auth_json["type"] == "gemini" and auth_json["email"] == "smoke@example.com" and auth_json["project_id"] == "smoke-project", auth_json
            assert auth_json["token"]["refresh_token"] == "fake-refresh-token" and auth_json["token"]["client_id"], auth_json
            manual_sync = assert_ok(
                client.post(
                    "/v1/admin/proxy-kernels/gemini_cli_oauth/runtime-credentials/sync",
                    headers=headers,
                    json={"dry_run": True, "account_id": "acct_gemini_runtime_sync_smoke"},
                )
            )
            assert manual_sync["ok"] is True and manual_sync["status"] == "planned" and manual_sync["file"]["name"].endswith(".json"), manual_sync
        finally:
            gemini_runtime_stop = assert_ok(client.post("/v1/admin/proxy-kernels/gemini_cli_oauth/stop-runtime", headers=headers, json={"grace_seconds": 1}))
            assert gemini_runtime_stop["process"]["running"] is False, gemini_runtime_stop
        dashboard = assert_ok(client.get("/v1/admin/dashboard", headers=headers))
        assert dashboard["object"] == "admin.dashboard" and "success_rate" in dashboard["jobs"] and "usage_today" in dashboard["billing"], dashboard
        assert "worker_concurrency" in dashboard["runtime"] and "active_leases" in dashboard["accounts"], dashboard
        admin_login = client.get("/admin")
        assert admin_login.status_code == 401 and "media2api 管理后台" in admin_login.text and "账号" in admin_login.text and "密码" in admin_login.text
        login_response = client.post("/admin/login", data={"username": "admin", "password": "dev-admin-key"}, follow_redirects=False)
        assert login_response.status_code in {302, 303} and "media2api_admin_key" in login_response.headers.get("set-cookie", "")
        admin_page = client.get("/admin")
        setup_page = client.get("/setup")
        assert setup_page.status_code == 200 and "MEDIA2API_PROXY_KERNEL_BOOTSTRAP_ROUTES=true" in setup_page.text and "MEDIA2API_SEED_DEFAULTS=false" in setup_page.text
        for setup_env_dom in ["MEDIA2API_PROXY_KERNEL_BOOTSTRAP_ROUTES=true", "MEDIA2API_SEED_DEFAULTS=false"]:
            assert setup_env_dom in admin_page.text, setup_env_dom
        assert admin_page.status_code == 200 and "总览" in admin_page.text and "今日任务" in admin_page.text and "操作" in admin_page.text
        for admin_control in ["平台输入要求", "反代内核", "反代内核清单", "上线包", "Provider 上线包", "读取上线包", "全量上线包", "启动受控执行器", "Runtime 预检", "安装 Release", "安装 Hash 候选", "批量安装候选计划", "上线工作台预检", "反代内核上线工作台", "启动 Runtime", "查看全部路由计划", "查看运行时交付计划", "运行时交付计划", "全量 Release 探测", "全量 Release 探测矩阵", "全量 Hash 候选", "全量 Release Hash 候选", "全量获取决策", "获取决策", "全量 Runtime 获取决策", "OpenAI Web Runtime 获取决策", "全量安装 Hash 候选计划", "全量源码运行计划", "Hash 候选", "OpenAI Web Hash 候选", "OpenAI Web 安装 Hash 候选", "运行合同矩阵", "全量运行合同矩阵", "运行合同", "OpenAI Web 运行合同", "生产就绪矩阵", "全量生产就绪矩阵", "生产就绪", "OpenAI Web 生产就绪", "补齐全部定型路由", "查看全部上线清单", "查看全部材料清单", "查看材料清单", "Loopback 合同自检", "查看上线清单", "查看路由计划", "补齐路由映射", "日志与停止", "源码参考", "source-repo 缺口计划", "同步需要源码参考", "源码运行计划", "生成启动器 dry-run", "同步到 source-repo", "探测 OpenAI Web Release", "探测 Gemini CLI Release", "全量材料清单", "OpenAI Web 材料清单", "OpenAI Web 运行时交付计划", "OpenAI Web 指南", "Codex 图像指南", "Gemini CLI 指南", "豆包指南", "Qwen.ai 指南", "Qianwen 指南", "账号验收套件", "任务诊断", "验收报告", "平台接入报告", "运维工作台报告", "生产上线计划", "连接器一致性", "外部连接器预检", "连接器清单模板", "系统要求报告", "最终验收矩阵", "交付包", "租约自检", "停滞任务恢复测试", "恢复停滞任务", "资产存储测试", "故障转移自检", "就绪检查", "添加平台账号", "批量导入账号", "真实平台合同套件", "配置快照", "导出配置", "试运行导入", "授权资源", "查看获取教程"]:
            assert admin_control in admin_page.text, admin_control
        for admin_dom in ["wizard-base-url", "wizard-provider-config", "wizard-submit", "wizard-provider-fields", "wizard-credential-label", "wizard-credential-hint", "cookie-provider-fields", "cookie-secret-label", "cookie-secret-hint", "agent-provider-fields", "agent-secret-label", "agent-secret-hint", "oauth-provider-guide", "oauth-guide-provider", "agent_provider_credential", "runtimeEndpointNamesByScope", "syncRuntimeEndpointField", "runtimeEndpointValue", "providerProfileRequirements", "providerCredentialRequirements", "syncCredentialInputHints", "collectProviderProfileFields", "field-hidden", "authorized-session-subnav", "authorized-session-start-pane", "authorized-session-complete-pane", "authorized-session-history-pane", "session-subnav-button", "kernel-provider", "kernel-package-provider", "kernel-go-live-package", "kernel-go-live-package-all", "kernel-go-live-package-all-status", "kernel-go-live-package-panel", "renderGoLivePackagePanel", "loadKernelGoLivePackage", "inspect-go-live-package", "kernel-go-live-all", "kernel-go-live", "kernel-materials-all", "kernel-materials", "kernel-runtime-delivery-all", "kernel-runtime-delivery", "kernel-live-workspace-plan", "kernel-release-probe-matrix", "kernel-release-checksum-matrix", "kernel-install-release-candidates-plan", "kernel-release-checksums", "kernel-install-release-candidate", "kernel-runtime-contract-matrix", "kernel-runtime-contract", "kernel-production-readiness-matrix", "kernel-production-readiness", "kernel-loopback-contract", "kernel-routing-plan-all", "kernel-apply-routing-all", "kernel-routing-plan", "kernel-apply-routing", "kernel-routing-status", "kernel-routing-enable", "kernel-release-tag", "kernel-release-asset", "kernel-release-sha256", "kernel-install-release", "kernel-artifact-path", "kernel-expected-sha256", "kernel-command", "kernel-runtime-preflight", "kernel-start-runtime", "kernel-load-logs", "kernel-provider-summary", "kernel-source-provider", "kernel-source-sync", "kernel-source-sync-needed-plan", "kernel-source-sync-needed", "kernel-source-runtime-plan-all", "kernel-source-runtime-plan", "kernel-source-runtime-setup", "kernel-source-runtime-launcher", "kernel-source-output", "kernel-source-plan-panel", "renderKernelSourceRuntimeMatrixPanel", "renderKernelSourcePlanPanel", "源码兜底操作面板", "/v1/admin/proxy-kernels/go-live-package", "/go-live-package", "/v1/admin/proxy-kernels/go-live-checklist", "/go-live-checklist", "/v1/admin/proxy-kernels/runtime-delivery-plan", "/runtime-delivery-plan", "/v1/admin/proxy-kernels/live-workspace", "/live-workspace", "/v1/admin/proxy-kernels/release-probe-matrix", "/release-probe-matrix", "/v1/admin/proxy-kernels/release-checksum-matrix", "/release-checksum-matrix", "/v1/admin/proxy-kernels/install-release-candidates", "/install-release-candidates", "/v1/admin/proxy-kernels/source-runtime-plan", "/v1/admin/proxy-kernels/source-repo/sync", "/source-runtime-plan", "/source-runtime-setup", "/source-runtime-launcher", "/v1/admin/proxy-kernels/openai_web_session/release-checksums", "/release-checksums", "/v1/admin/proxy-kernels/openai_web_session/install-release-candidate", "/install-release-candidate", "/runtime-preflight", "/v1/admin/proxy-kernels/runtime-contract-matrix", "/runtime-contract-matrix", "/v1/admin/proxy-kernels/production-readiness-matrix", "/production-readiness-matrix", "/v1/admin/proxy-kernels/openai_web_session/runtime-contract", "/runtime-contract", "/v1/admin/proxy-kernels/openai_web_session/production-readiness", "/production-readiness", "/v1/admin/proxy-kernels/materials-request", "/materials-request", "/v1/admin/proxy-kernels/loopback-contract-test", "/loopback-contract-test", "/v1/admin/proxy-kernels/routing-plan", "/v1/admin/proxy-kernels/apply-routing", "/routing-plan", "/apply-routing", "/source-repo/sync", "/v1/admin/account-onboarding", "/v1/admin/account-onboarding/bulk", "/v1/admin/authorized-resource-sessions", "/v1/admin/proxy-kernels"]:
            assert admin_dom in admin_page.text, admin_dom
        for runtime_acquisition_dom in ["kernel-runtime-acquisition-all", "kernel-runtime-acquisition", "loadKernelRuntimeAcquisitionPlan", "loadAllKernelRuntimeAcquisitionPlans", "runtime_acquisition_plan", "/v1/admin/proxy-kernels/runtime-acquisition-plan", "/runtime-acquisition-plan", "/v1/admin/proxy-kernels/openai_web_session/runtime-acquisition-plan"]:
            assert runtime_acquisition_dom in admin_page.text, runtime_acquisition_dom
        for account_material_dom in ["kernel-account-materials", "kernel-account-materials-matrix", "kernel-account-connection-package", "kernel-account-material-panel", "kernel-account-credential", "kernel-account-resource-profile", "kernel-account-preflight", "kernel-account-import", "kernel-account-runtime-sync", "kernel-account-runtime-sync-status", "submitKernelAccountMaterials", "syncKernelRuntimeCredentials", "renderKernelAccountMaterialsPanel", "loadKernelAccountMaterials", "renderKernelAccountMaterialsMatrix", "loadKernelAccountMaterialsMatrix", "renderKernelAccountConnectionPackage", "loadKernelAccountConnectionPackage", "resource_profile_json_template", "fields_by_destination", "/account-materials", "/account-materials-matrix", "/account-connection-package", "/account-materials-bulk", "/runtime-credentials/sync"]:
            assert account_material_dom in admin_page.text, account_material_dom
        for activation_dom in ["kernel-activation-workflow-all", "kernel-activation-workflow", "kernel-production-activation-dashboard", "kernel-production-gap-report-all", "kernel-production-gap-report", "kernel-activation-run", "kernel-activation-overview", "kernel-activation-panel", "activation-stage-grid", "activation-provider-grid", "data-activation-action", "runActivationAction", "runKernelActivationRun", "syncProviderEntryFields", "inspect-provider", "apply-routing", "open-account", "open-runtime", "open-users", "renderActivationWorkflowPanel", "renderActivationWorkflowOverview", "renderProductionActivationDashboard", "loadProductionActivationDashboard", "renderProductionGapReportOverview", "/v1/admin/proxy-kernels/activation-workflow", "/activation-workflow", "/v1/admin/proxy-kernels/production-activation-dashboard", "/production-activation-dashboard", "/v1/admin/proxy-kernels/production-gap-report", "/production-gap-report", "/activation-run"]:
            assert activation_dom in admin_page.text, activation_dom
        for kernel_health_control in ["Runtime 健康检查", "OpenAI Web Runtime 健康检查", "启动后健康检查", "健康失败时"]:
            assert kernel_health_control in admin_page.text, kernel_health_control
        for kernel_health_dom in ["kernel-runtime-health", "kernel-run-health", "kernel-fail-on-health", "/v1/admin/proxy-kernels/openai_web_session/runtime-health-check", "/runtime-health-check"]:
            assert kernel_health_dom in admin_page.text, kernel_health_dom
        for kernel_live_acceptance_text in ["Dry run", "Live"]:
            assert kernel_live_acceptance_text in admin_page.text, kernel_live_acceptance_text
        for kernel_live_acceptance_dom in ["kernel-live-acceptance", "kernel-run-live-acceptance", "kernel-live-acceptance-mode", "kernel-live-acceptance-max-samples", "kernel-live-acceptance-operations", "/v1/admin/proxy-kernels/openai_web_session/live-acceptance", "/live-acceptance"]:
            assert kernel_live_acceptance_dom in admin_page.text, kernel_live_acceptance_dom
        for kernel_handoff_dom in ["kernel-handoff-all", "kernel-handoff", "kernel-run-handoff", "/v1/admin/proxy-kernels/operator-handoff", "/operator-handoff", "/v1/admin/proxy-kernels/openai_web_session/operator-handoff", "/v1/admin/proxy-kernels/openai_web_session/operator-handoff/run", "/operator-handoff/run"]:
            assert kernel_handoff_dom in admin_page.text, kernel_handoff_dom
        for banned_oauth_copy in ["如果该平台没有官方 API Key 或公开 OAuth", "通用第三方连接器", "无公开获取入口", "Google OAuth 2.0 Playground", "https://developers.google.com/oauthplayground/", "https://bailian.console.aliyun.com/", "https://platform.openai.com/api-keys", "OpenAI API Keys", "refresh_token"]:
            assert banned_oauth_copy not in admin_page.text, banned_oauth_copy
        assert "connector.example" not in admin_page.text
        assert "Mock Stability Test" not in admin_page.text and "acct_mock_default" not in admin_page.text
        onboarding_account_id = f"acct_dashboard_onboarding_{dashboard_suffix}"
        onboarding_result = assert_ok(
            client.post(
                "/v1/admin/account-onboarding",
                headers=headers,
                json={
                    "provider_id": "gemini",
                    "account_id": onboarding_account_id,
                    "label": "dashboard onboarding smoke",
                    "provider_base_url": "http://127.0.0.1:18091",
                    "provider_config": {"source": "smoke"},
                    "resource_type": "agent_provider",
                    "auth_method": "agent_provider_credential",
                    "credential_ref": "agent://smoke/gemini/account",
                    "supported_operations": ["text_to_image"],
                    "supported_provider_models": ["nano-banana-pro"],
                    "sync_capabilities": False,
                    "run_health_check": False,
                },
            )
        )
        assert onboarding_result["object"] == "account.onboarding" and onboarding_result["account"]["id"] == onboarding_account_id, onboarding_result
        assert onboarding_result["account"]["provider_id"] == "gemini" and onboarding_result["provider"]["status"] == "active", onboarding_result
        official_api_onboarding = client.post(
            "/v1/admin/account-onboarding",
            headers=headers,
            json={
                "provider_id": "gemini",
                "account_id": f"acct_official_api_block_{dashboard_suffix}",
                "label": "blocked official api account",
                "auth_method": "api_key",
                "credential_value": "sk-official-api-not-allowed",
                "supported_operations": ["text_to_image"],
                "supported_provider_models": ["nano-banana-pro"],
                "sync_capabilities": False,
                "run_health_check": False,
            },
        )
        assert official_api_onboarding.status_code == 400 and "UPSTREAM_OFFICIAL_API_AUTH_NOT_ALLOWED" in official_api_onboarding.text
        operator_workbench = assert_ok(client.get("/v1/admin/operator-workbench-report", headers=headers))
        assert operator_workbench["object"] == "media2api.operator_workbench_report", operator_workbench
        assert operator_workbench["summary"]["required_missing_routes"] == 0, operator_workbench
        module_names = {item["module"] for item in operator_workbench["modules"]}
        assert {"Dashboard", "Users", "Models", "Providers", "Accounts", "Jobs", "Assets", "Billing", "Alerts", "Webhooks", "Audit"}.issubset(module_names), operator_workbench
        go_live_plan = assert_ok(client.get("/v1/admin/production-go-live-plan", headers=headers))
        assert go_live_plan["object"] == "media2api.production_go_live_plan", go_live_plan
        assert set(["text_to_image", "image_edit", "text_to_video", "image_to_video"]).issubset(set(go_live_plan["required_operations"])), go_live_plan
        assert go_live_plan["single_provider_candidates"], go_live_plan
        assert {"activate_dry_run", "external_acceptance_live", "scripted_acceptance"}.issubset(set(go_live_plan["single_provider_candidates"][0]["commands"])), go_live_plan
        connector_conformance = assert_ok(client.get("/v1/admin/connector-conformance-report", headers=headers))
        assert connector_conformance["object"] == "media2api.connector_conformance_report", connector_conformance
        assert set(["text_to_image", "image_edit", "text_to_video", "image_to_video"]).issubset(set(connector_conformance["required_operations"])), connector_conformance
        conformance_provider_ids = {item["provider_id"] for item in connector_conformance["providers"]}
        assert {"jimeng", "gemini", "qwen", "pollinations"}.issubset(conformance_provider_ids), connector_conformance
        assert all("operation_matrix" in item for item in connector_conformance["providers"]), connector_conformance
        external_preflight = assert_ok(client.get("/v1/admin/external-connector-preflight", headers=headers))
        assert external_preflight["object"] == "media2api.external_connector_preflight", external_preflight
        assert set(["text_to_image", "image_edit", "text_to_video", "image_to_video"]).issubset(set(external_preflight["required_operations"])), external_preflight
        assert external_preflight["providers"] and "activate_template" in external_preflight["providers"][0]["commands"], external_preflight
        manifest_template = assert_ok(client.get("/v1/admin/external-connector-manifest-template?provider_id=gemini", headers=headers))
        assert manifest_template["object"] == "media2api.external_connector_manifest_template", manifest_template
        assert manifest_template["provider_id"] == "gemini" and manifest_template["default_manifest"]["accounts"], manifest_template
        manifest_secret = "smoke-manifest-secret-token"
        manifest_credential_value = json.dumps({"GEMINI_CREDENTIALS": {"client_id": "smoke-client", "refresh_token": manifest_secret}})
        manifest_plan = assert_ok(
            client.post(
                "/v1/admin/external-connector-manifest",
                headers=headers,
                json={
                    "provider_id": "gemini",
                    "base_url": "https://gemini-agent-runtime.example",
                    "credential_value": manifest_credential_value,
                    "credential_kind": "agent_provider",
                    "dry_run": True,
                    "operations": ["text_to_image", "image_edit", "text_to_video", "image_to_video"],
                    "accounts": [
                        {"account_id": "acct_smoke_manifest_1", "account_label": "Smoke Manifest 1", "concurrency_limit": 1},
                        {"account_id": "acct_smoke_manifest_2", "account_label": "Smoke Manifest 2", "credential_ref": "agent://smoke/manifest/2", "concurrency_limit": 2},
                    ],
                },
            )
        )
        assert manifest_plan["object"] == "media2api.external_connector_manifest" and manifest_plan["dry_run"] is True, manifest_plan
        assert len(manifest_plan["accounts"]) == 2 and manifest_plan["accounts"][0]["credential_value_provided"] is True, manifest_plan
        assert manifest_secret not in json.dumps(manifest_plan, ensure_ascii=False), manifest_plan
        system_requirements = assert_ok(client.get("/v1/admin/system-requirements-report", headers=headers))
        assert system_requirements["object"] == "media2api.system_requirements_report", system_requirements
        assert system_requirements["summary"]["total_requirements"] >= 30, system_requirements
        system_requirement_ids = {item["id"] for item in system_requirements["requirements"]}
        assert {"C-001", "API-001", "API-OPENAI", "API-NATIVE", "MODEL-001", "ASSET-004", "PA-001", "ACC-001", "BILL-001", "ADMIN-001", "OBS-001", "SEC-001", "SDK-001", "CONNECTOR-SDK-001", "PREFLIGHT-001", "MANIFEST-001", "FINAL-ACCEPTANCE-001", "DELIVERY-001", "MVP-CORE", "MVP-REAL-PROVIDER"}.issubset(system_requirement_ids), system_requirements
        assert system_requirements["summary"]["core_ready"] is True, system_requirements
        final_acceptance = assert_ok(client.get("/v1/admin/final-acceptance-matrix", headers=headers))
        assert final_acceptance["object"] == "media2api.final_acceptance_matrix", final_acceptance
        final_ids = {item["id"] for item in final_acceptance["rows"]}
        assert {"AC-001", "AC-002", "AC-003", "AC-004", "AC-005", "AC-006", "AC-007", "AC-008", "AC-S-001", "AC-S-002", "AC-S-003", "AC-S-004", "AC-S-005", "N-001", "N-002", "N-003", "N-004", "N-005", "N-006", "N-007", "N-008", "AC-PROD-001"}.issubset(final_ids), final_acceptance
        assert final_acceptance["summary"]["system_requirements"]["core_ready"] is True, final_acceptance
        assert final_acceptance["status"] == "action_required", final_acceptance
        assert any(item["id"] == "AC-PROD-001" and item["blocked_by"] == "authorized_external_connector_accounts" for item in final_acceptance["blocked_rows"]), final_acceptance
        delivery_package = assert_ok(client.get("/v1/admin/delivery-package", headers=headers))
        assert delivery_package["object"] == "media2api.delivery_package", delivery_package
        assert delivery_package["readiness"]["core_ready"] is True, delivery_package
        assert "remote_acceptance" in delivery_package["acceptance_commands"], delivery_package
        assert "external_connector_preflight" in delivery_package, delivery_package
        assert "external_connector_manifest" in delivery_package and "external_connector_manifest_template" in delivery_package["acceptance_commands"], delivery_package
        assert "final_acceptance_matrix" in delivery_package and "final_acceptance_matrix" in delivery_package["acceptance_commands"], delivery_package
        assert "SDK-001" in system_requirement_ids and delivery_package["developer_assets"]["examples"], delivery_package
        assert any(item["path"] == "examples/media2api_sdk.py" and item["exists"] for item in delivery_package["developer_assets"]["examples"]), delivery_package
        redact_request_id = "req_smoke_admin_query_redact"
        admin_redact_page = client.get("/admin?admin_key=dev-admin-key&view=dashboard", headers={"x-request-id": redact_request_id})
        assert admin_redact_page.status_code == 200, admin_redact_page.text
        redacted_logs = assert_ok(client.get(f"/v1/admin/request-logs?request_id={redact_request_id}", headers=headers))
        assert redacted_logs["data"], redacted_logs
        redacted_query = redacted_logs["data"][0]["metadata"].get("query", "")
        assert "dev-admin-key" not in redacted_query and "admin_key" in redacted_query and "redacted" in redacted_query, redacted_query
        lease_self_test = assert_ok(client.post("/v1/admin/account-leases/self-test-expiry", headers=headers))
        assert lease_self_test["object"] == "lease_expiry_self_test" and lease_self_test["ok"] is True, lease_self_test
        assert lease_self_test["job"]["status"] == "expired" and lease_self_test["job"]["error"]["code"] == "LEASE_EXPIRED", lease_self_test
        assert lease_self_test["account"]["current_leases_after"] == lease_self_test["account"]["current_leases_before"], lease_self_test
        terminal_lease_job_id = f"job_terminal_lease_{int(time.time() * 1000)}"
        terminal_lease_id = f"lease_terminal_{int(time.time() * 1000)}"
        with SessionLocal() as db:
            account = db.get(db_models.AccountResource, "acct_mock_default")
            active_before = (
                db.query(db_models.AccountLease)
                .filter(db_models.AccountLease.account_id == "acct_mock_default", db_models.AccountLease.status == "active")
                .count()
            )
            account.current_leases = active_before + 1
            db.add(
                db_models.MediaJob(
                    id=terminal_lease_job_id,
                    user_id="usr_admin",
                    api_key_id="key_admin",
                    operation="text_to_image",
                    logical_model="t2i-fast",
                    normalized_params_json=dumps({"model": "t2i-fast", "prompt": "terminal lease reconcile", "n": 1}),
                    input_asset_ids_json=dumps([]),
                    output_asset_ids_json=dumps([]),
                    provider_id="mock",
                    provider_model="mock-image-fast",
                    account_id="acct_mock_default",
                    provider_task_id=f"terminal_{terminal_lease_job_id}",
                    status="completed",
                    cost_estimate=0,
                    final_cost=0,
                )
            )
            db.add(
                db_models.AccountLease(
                    id=terminal_lease_id,
                    job_id=terminal_lease_job_id,
                    account_id="acct_mock_default",
                    provider_id="mock",
                    provider_model="mock-image-fast",
                    expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=30),
                    status="active",
                )
            )
            db.commit()
        terminal_reconcile = assert_ok(client.post("/v1/admin/account-leases/reconcile?account_id=acct_mock_default", headers=headers))
        assert terminal_reconcile["released_terminal_leases"] >= 1, terminal_reconcile
        terminal_leases = assert_ok(client.get(f"/v1/admin/account-leases?job_id={terminal_lease_job_id}", headers=headers))
        assert terminal_leases["data"] and terminal_leases["data"][0]["status"] == "released", terminal_leases
        stalled_self_test = assert_ok(client.post("/v1/admin/media-jobs/self-test-stalled-recovery", headers=headers))
        assert stalled_self_test["object"] == "stalled_job_recovery_self_test" and stalled_self_test["ok"] is True, stalled_self_test
        assert stalled_self_test["recovery"]["recovered"] == 1, stalled_self_test
        assert stalled_self_test["recovered_job"]["status"] == "queued", stalled_self_test
        assert stalled_self_test["job"]["status"] == "cancelled", stalled_self_test
        assert any(event["event_type"] == "stalled_job_requeued" for event in stalled_self_test["events"]), stalled_self_test
        connector_cancel_self_test = assert_ok(client.post("/v1/admin/media-jobs/self-test-connector-cancel", headers=headers))
        assert connector_cancel_self_test["object"] == "connector_cancel_self_test" and connector_cancel_self_test["ok"] is True, connector_cancel_self_test
        assert connector_cancel_self_test["job"]["status"] == "cancelled", connector_cancel_self_test
        assert connector_cancel_self_test["provider_cancel"]["status"] == "cancelled", connector_cancel_self_test
        assert connector_cancel_self_test["upstream"]["cancel_hits"] == 1, connector_cancel_self_test
        assert connector_cancel_self_test["lease"]["status"] == "released", connector_cancel_self_test
        assert all(hold["status"] == "refunded" for hold in connector_cancel_self_test["billing"]["holds"]), connector_cancel_self_test
        assert connector_cancel_self_test["billing"]["wallet_after"] == connector_cancel_self_test["billing"]["wallet_before"], connector_cancel_self_test
        mock_stability = assert_ok(client.post("/v1/admin/stability/self-test-mock", headers=headers, json={"iterations": 3}))
        assert mock_stability["object"] == "mock_stability_self_test" and mock_stability["ok"] is True, mock_stability
        assert mock_stability["iterations_completed"] == 3 and not mock_stability["leases"]["active_lease_leaks"], mock_stability
        assert mock_stability["assets"]["output_asset_count"] >= 3 and mock_stability["billing"]["held_holds"] == 0, mock_stability
        asset_storage_self_test = assert_ok(client.post("/v1/admin/assets/self-test-storage", headers=headers, json={"cleanup": True}))
        assert asset_storage_self_test["object"] == "asset_storage_self_test" and asset_storage_self_test["ok"] is True, asset_storage_self_test
        assert asset_storage_self_test["read"]["ok"] is True, asset_storage_self_test
        assert asset_storage_self_test["signed_url"]["signature_ok"] is True, asset_storage_self_test
        assert asset_storage_self_test["cleanup"]["deleted"] is True, asset_storage_self_test
        temp_url_asset_self_test = assert_ok(client.post("/v1/admin/assets/self-test-temp-url", headers=headers))
        assert temp_url_asset_self_test["object"] == "temp_url_asset_self_test" and temp_url_asset_self_test["ok"] is True, temp_url_asset_self_test
        assert temp_url_asset_self_test["job"]["status"] == "completed", temp_url_asset_self_test
        assert temp_url_asset_self_test["source"]["second_fetch_status"] == 410, temp_url_asset_self_test
        assert temp_url_asset_self_test["platform_download"]["ok"] is True, temp_url_asset_self_test
        assert not [lease for lease in temp_url_asset_self_test["leases"] if lease["status"] == "active"], temp_url_asset_self_test
        assert "http://127.0.0.1" not in str(temp_url_asset_self_test["admin_asset"].get("provider_meta")), temp_url_asset_self_test
        temp_url_attempts_text = json.dumps(temp_url_asset_self_test.get("attempts") or [], sort_keys=True)
        assert "http://127.0.0.1" not in temp_url_attempts_text and "image_url_hash" in temp_url_attempts_text, temp_url_asset_self_test
        fallback_self_test = assert_ok(client.post("/v1/admin/fallback/self-test", headers=headers))
        assert fallback_self_test["object"] == "fallback_self_test" and fallback_self_test["ok"] is True, fallback_self_test
        assert fallback_self_test["job"]["status"] == "completed", fallback_self_test
        assert [attempt["status"] for attempt in fallback_self_test["attempts"]] == ["failed", "completed"], fallback_self_test
        assert fallback_self_test["fallback"]["fallback_event_count"] >= 1, fallback_self_test
        assert fallback_self_test["billing"]["usage_records"] == 1 and fallback_self_test["billing"]["held_holds"] == 0, fallback_self_test
        fallback_timeout_self_test = assert_ok(client.post("/v1/admin/fallback/self-test-timeout", headers=headers))
        assert fallback_timeout_self_test["object"] == "fallback_timeout_self_test" and fallback_timeout_self_test["ok"] is True, fallback_timeout_self_test
        assert fallback_timeout_self_test["job"]["status"] == "completed", fallback_timeout_self_test
        assert [attempt["status"] for attempt in fallback_timeout_self_test["attempts"]] == ["failed", "completed"], fallback_timeout_self_test
        assert fallback_timeout_self_test["attempts"][0]["error_code"] == "PROVIDER_TIMEOUT", fallback_timeout_self_test
        assert fallback_timeout_self_test["fallback"]["fallback_event_count"] >= 1, fallback_timeout_self_test
        assert fallback_timeout_self_test["billing"]["usage_records"] == 1 and fallback_timeout_self_test["billing"]["held_holds"] == 0, fallback_timeout_self_test
        account_cooldown_self_test = assert_ok(client.post("/v1/admin/accounts/self-test-cooldown", headers=headers))
        assert account_cooldown_self_test["object"] == "account_cooldown_self_test" and account_cooldown_self_test["ok"] is True, account_cooldown_self_test
        assert account_cooldown_self_test["account"]["status_before_cleanup"] == "cooldown", account_cooldown_self_test
        assert account_cooldown_self_test["account"]["failure_score_before_cleanup"] >= 0.75, account_cooldown_self_test
        assert account_cooldown_self_test["probe_job"]["status"] == "failed", account_cooldown_self_test
        assert account_cooldown_self_test["probe_job"]["error"]["code"] == "UNSUPPORTED_MODEL_OPERATION", account_cooldown_self_test
        assert not [lease for lease in account_cooldown_self_test["leases"] if lease["status"] == "active"], account_cooldown_self_test
        assert account_cooldown_self_test["billing"]["held_holds"] == 0 and account_cooldown_self_test["alerts"], account_cooldown_self_test
        onboarding = assert_ok(client.get("/v1/admin/provider-onboarding-report", headers=headers))
        assert onboarding["object"] == "media2api.provider_onboarding_report", onboarding
        assert onboarding["summary"]["providers"] >= 15 and "p0_action_required" in onboarding["summary"], onboarding
        provider_rows = {row["provider_id"]: row for row in onboarding["providers"]}
        assert {"openai_image", "gemini", "grok", "qwen", "jimeng"}.issubset(provider_rows), provider_rows.keys()
        assert provider_rows["gemini"]["operator_endpoints"]["external_acceptance"].endswith("/gemini/external-acceptance"), provider_rows["gemini"]
        assert "dev-admin-key" not in str(onboarding), onboarding
        for admin_section in ["用户", "模型", "模型映射", "资产", "回调"]:
            assert admin_section in admin_page.text, admin_section
        metrics = client.get("/metrics")
        assert metrics.status_code == 200 and "media2api_jobs_total" in metrics.text
        for metric_name in [
            "media2api_jobs_status_total",
            "media2api_media_job_duration_seconds",
            "media2api_provider_submit_errors_total",
            "media2api_provider_poll_timeout_total",
            "media2api_account_lease_active",
            "media2api_account_failure_score",
            "media2api_account_quota_remaining",
            "media2api_account_quota_available",
            "media2api_asset_ingest_failed_total",
            "media2api_fallback_attempts_total",
            "media2api_stalled_jobs_active",
            "media2api_stalled_jobs_recovered_total",
        ]:
            assert metric_name in metrics.text, metric_name
        for metric_name in [
            "media_jobs_total",
            "media_job_duration_seconds",
            "provider_submit_errors_total",
            "provider_poll_timeout_total",
            "account_lease_active",
            "account_failure_score",
            "asset_ingest_failed_total",
            "billing_holds_total",
            "fallback_attempts_total",
            "stalled_jobs_active",
            "stalled_jobs_recovered_total",
        ]:
            assert metric_name in metrics.text, metric_name
        users = assert_ok(client.get("/v1/admin/users", headers=headers))
        assert len(users["data"]) >= 1
        api_keys = assert_ok(client.get("/v1/admin/api-keys", headers=headers))
        assert len(api_keys["data"]) >= 1
        suffix = str(int(time.time() * 1000))
        key_user_id = f"usr_key_{suffix}"
        assert_ok(client.post("/v1/admin/users", headers=headers, json={"id": key_user_id, "email": f"{key_user_id}@media2api.local", "wallet_balance": 100000}))
        created_key = assert_ok(client.post("/v1/admin/api-keys", headers=headers, json={"user_id": key_user_id, "name": "key-smoke"}))
        smoke_key_headers = {"Authorization": f"Bearer {created_key['api_key']}"}
        assert_ok(client.get("/v1/models", headers=smoke_key_headers))
        non_admin_api = client.get("/v1/admin/users", headers=smoke_key_headers)
        assert non_admin_api.status_code == 403 and non_admin_api.json()["code"] == "ADMIN_REQUIRED", non_admin_api.text
        for internal_path in ["/v1/providers", "/v1/accounts", "/v1/model-mappings"]:
            internal_resp = client.get(internal_path, headers=smoke_key_headers)
            assert internal_resp.status_code == 403 and internal_resp.json()["code"] == "ADMIN_REQUIRED", internal_resp.text
        non_admin_assets = client.get("/v1/admin/assets", headers=smoke_key_headers)
        assert non_admin_assets.status_code == 403 and non_admin_assets.json()["code"] == "ADMIN_REQUIRED", non_admin_assets.text
        non_admin_preview = client.post("/v1/router/preview", headers=smoke_key_headers, json={"model": "t2i-fast", "operation": "text_to_image", "params": {"prompt": "x"}})
        assert non_admin_preview.status_code == 403 and non_admin_preview.json()["code"] == "ADMIN_REQUIRED", non_admin_preview.text
        credential_skip_provider_id = f"provider_credential_skip_{suffix}"
        credential_skip_model_id = f"model_credential_skip_{suffix}"
        credential_skip_provider_model = f"credential-skip-model-{suffix}"
        credential_skip_mapping_id = f"{credential_skip_model_id}:{credential_skip_provider_id}:{credential_skip_provider_model}"
        credential_skip_missing_account_id = f"acct_credential_skip_missing_{suffix}"
        credential_skip_public_account_id = f"acct_credential_skip_public_{suffix}"
        credential_skip_job_id = f"job_credential_skip_{suffix}"
        with SessionLocal() as db:
            db.add(
                db_models.Provider(
                    id=credential_skip_provider_id,
                    name="Credential Skip Smoke Provider",
                    adapter_type="http_adapter",
                    status="active",
                    base_config_json=dumps({}),
                    notes="smoke credential availability regression",
                )
            )
            db.add(
                db_models.LogicalModel(
                    id=credential_skip_model_id,
                    display_name="Credential Skip Smoke Model",
                    operations_json=dumps(["text_to_image"]),
                    constraints_json=dumps({}),
                    default_params_json=dumps({}),
                    billing_class="image_fast",
                    enabled=True,
                )
            )
            db.add(
                db_models.ProviderModelMapping(
                    id=credential_skip_mapping_id,
                    logical_model=credential_skip_model_id,
                    provider_id=credential_skip_provider_id,
                    provider_model=credential_skip_provider_model,
                    operations_json=dumps(["text_to_image"]),
                    priority=1,
                    weight=1,
                    cost_score=0.5,
                    speed_score=0.5,
                    quality_score=0.5,
                    reliability_score=0.5,
                    enabled=True,
                )
            )
            db.add(
                db_models.AccountResource(
                    id=credential_skip_missing_account_id,
                    provider_id=credential_skip_provider_id,
                    label="Missing Env Credential Smoke",
                    credential_ref=f"env://MEDIA2API_MISSING_CREDENTIAL_SKIP_{suffix}",
                    supported_operations_json=dumps(["text_to_image"]),
                    supported_provider_models_json=dumps([credential_skip_provider_model]),
                    quota_buckets_json=dumps([{"type": "credits", "remaining_estimate": 10, "confidence": 1}]),
                    concurrency_limit=1,
                    current_leases=0,
                    health_score=1.0,
                    failure_score=0.0,
                    status="active",
                )
            )
            db.add(
                db_models.AccountResource(
                    id=credential_skip_public_account_id,
                    provider_id=credential_skip_provider_id,
                    label="Public Credential Smoke",
                    credential_ref="public://credential-skip-smoke",
                    supported_operations_json=dumps(["text_to_image"]),
                    supported_provider_models_json=dumps([credential_skip_provider_model]),
                    quota_buckets_json=dumps([{"type": "credits", "remaining_estimate": 10, "confidence": 1}]),
                    concurrency_limit=1,
                    current_leases=0,
                    health_score=0.1,
                    failure_score=0.0,
                    status="active",
                )
            )
            db.add(
                db_models.MediaJob(
                    id=credential_skip_job_id,
                    user_id="usr_admin",
                    api_key_id=api_keys["data"][0]["id"],
                    operation="text_to_image",
                    logical_model=credential_skip_model_id,
                    normalized_params_json=dumps({"prompt": "credential skip smoke"}),
                    input_asset_ids_json=dumps([]),
                    output_asset_ids_json=dumps([]),
                    status="leasing_account",
                    cost_estimate=1,
                )
            )
            db.commit()
            mapping = db.get(db_models.ProviderModelMapping, credential_skip_mapping_id)
            router = ModelRouter()
            candidates = router.candidate_mappings(db, credential_skip_model_id, "text_to_image", {})
            assert [item.id for item in candidates] == [credential_skip_mapping_id], candidates
            assert router.explain_last(mapping)["available_accounts"] == 1, router.explain_last(mapping)
            scheduler = AccountScheduler()
            lease = scheduler.acquire(db, credential_skip_job_id, mapping, "text_to_image")
            assert lease.account_id == credential_skip_public_account_id, lease.account_id
            assert db.get(db_models.AccountResource, credential_skip_missing_account_id).current_leases == 0
            assert db.get(db_models.AccountResource, credential_skip_public_account_id).current_leases == 1
            scheduler.release(db, lease, success=False, neutral=True)
            db.commit()
        isolation_breaker = assert_ok(
            client.post(
                "/v1/admin/circuit-breakers",
                headers=headers,
                json={
                    "id": f"cb_public_alert_isolation_{suffix}",
                    "scope": "provider",
                    "target_id": f"provider_public_alert_isolation_{suffix}",
                    "status": "open",
                    "reason": "public alert isolation smoke",
                    "error_code": "SMOKE_ISOLATION",
                    "enabled": True,
                },
            )
        )
        public_alerts = assert_ok(client.get("/v1/alerts?status=open", headers=smoke_key_headers))
        assert all(item["user_id"] == key_user_id for item in public_alerts["data"]), public_alerts
        assert all(item["dimensions"].get("target_id") != isolation_breaker["target_id"] for item in public_alerts["data"]), public_alerts
        non_admin_page = client.get(f"/admin?admin_key={created_key['api_key']}")
        assert non_admin_page.status_code == 403 and "需要管理员权限" in non_admin_page.text, non_admin_page.text
        disabled_key = assert_ok(client.patch(f"/v1/admin/api-keys/{created_key['id']}", headers=headers, json={"status": "disabled", "name": "key-smoke-disabled"}))
        assert disabled_key["status"] == "disabled" and disabled_key["name"] == "key-smoke-disabled", disabled_key
        disabled_key_call = client.get("/v1/models", headers=smoke_key_headers)
        assert disabled_key_call.status_code == 401 and disabled_key_call.json()["code"] == "INVALID_API_KEY", disabled_key_call.text
        restored_key = assert_ok(client.patch(f"/v1/admin/api-keys/{created_key['id']}", headers=headers, json={"status": "active"}))
        assert restored_key["status"] == "active", restored_key
        assert_ok(client.get("/v1/models", headers=smoke_key_headers))
        revoked_key = assert_ok(client.delete(f"/v1/admin/api-keys/{created_key['id']}", headers=headers))
        assert revoked_key["revoked"] is True, revoked_key
        revoked_key_call = client.get("/v1/models", headers=smoke_key_headers)
        assert revoked_key_call.status_code == 401 and revoked_key_call.json()["code"] == "INVALID_API_KEY", revoked_key_call.text
        secret_id = f"secret_smoke_{suffix}"
        secret = assert_ok(
            client.post(
                "/v1/admin/credential-secrets",
                headers=headers,
                json={
                    "id": secret_id,
                    "name": "Smoke Credential",
                    "value": "sk-smoke-secret-value",
                    "kind": "api_key",
                    "provider_id": "mock",
                    "metadata": {"scope": "smoke"},
                },
            )
        )
        assert secret["ref"] == f"secret://{secret_id}" and secret["preview"] == "sk-s...alue" and "value" not in secret
        secret_list = assert_ok(client.get("/v1/admin/credential-secrets?provider_id=mock", headers=headers))
        assert any(item["id"] == secret_id for item in secret_list["data"]), secret_list
        secret_patch = assert_ok(client.patch(f"/v1/admin/credential-secrets/{secret_id}", headers=headers, json={"notes": "patched", "status": "disabled"}))
        assert secret_patch["status"] == "disabled" and secret_patch["notes"] == "patched", secret_patch
        secret_deleted = assert_ok(client.delete(f"/v1/admin/credential-secrets/{secret_id}", headers=headers))
        assert secret_deleted["deleted"] is True, secret_deleted
        bulk_account_id = f"acct_bulk_{suffix}"
        bulk_secret_id = f"secret_bulk_{suffix}"
        bulk = assert_ok(
            client.post(
                "/v1/admin/accounts/bulk-upsert",
                headers=headers,
                json={
                    "accounts": [
                        {
                            "id": bulk_account_id,
                            "provider_id": "mock",
                            "label": "Bulk Smoke Account",
                            "credential_value": "bulk-smoke-secret",
                            "credential_secret_id": bulk_secret_id,
                            "credential_kind": "api_key",
                            "supported_operations": ["text_to_image"],
                            "supported_provider_models": ["mock-image-fast"],
                            "quota_buckets": [{"type": "credits", "operation": "text_to_image", "remaining_estimate": 100, "confidence": 1}],
                            "concurrency_limit": 3,
                            "region": "smoke",
                            "plan": "bulk",
                        }
                    ]
                },
            )
        )
        assert bulk["created_accounts"] == 1 and not bulk["errors"], bulk
        assert bulk["data"][0]["account"]["credential_ref"] == f"secret://{bulk_secret_id}" and "value" not in bulk["data"][0]["secret"]
        assert bulk["data"][0]["account"]["resource_type"] == "agent_provider", bulk
        assert bulk["data"][0]["secret"]["kind"] == "agent_provider", bulk
        inline_account_id = f"acct_inline_{suffix}"
        inline_account = assert_ok(
            client.post(
                "/v1/admin/accounts",
                headers=headers,
                json={
                    "id": inline_account_id,
                    "provider_id": "mock",
                    "label": "Inline Credential Smoke",
                    "credential_ref": "bearer://inline-secret-should-not-leak",
                    "supported_operations": ["text_to_image"],
                    "supported_provider_models": ["mock-image-fast"],
                    "quota_buckets": [{"type": "credits", "remaining_estimate": 1, "confidence": 1}],
                    "concurrency_limit": 1,
                    "status": "disabled",
                },
            )
        )
        assert inline_account["credential_ref"] == f"secret://secret_{inline_account_id}" and inline_account["credential_ref_type"] == "secret", inline_account
        assert inline_account["secret"]["ref"] == f"secret://secret_{inline_account_id}" and "value" not in inline_account["secret"], inline_account
        account_list_after_inline = assert_ok(client.get("/v1/accounts", headers=headers))
        serialized_inline = [item for item in account_list_after_inline["data"] if item["id"] == inline_account_id][0]
        assert "inline-secret-should-not-leak" not in str(serialized_inline) and serialized_inline["credential_ref"] == f"secret://secret_{inline_account_id}", serialized_inline
        credential_migration = assert_ok(client.post("/v1/admin/accounts/migrate-inline-credentials", headers=headers))
        assert credential_migration["object"] == "account_credential_migration" and not credential_migration["errors"], credential_migration
        config_snapshot = assert_ok(client.get("/v1/admin/config-export", headers=headers))
        assert config_snapshot["object"] == "media2api.config_snapshot" and config_snapshot["counts"]["providers"] >= 1, config_snapshot
        assert "inline-secret-should-not-leak" not in str(config_snapshot) and "bulk-smoke-secret" not in str(config_snapshot), config_snapshot
        exported_pollinations = [item for item in config_snapshot["sections"]["providers"] if item["id"] == "pollinations"]
        if exported_pollinations:
            pollinations_ref = exported_pollinations[0]["base_config"].get("credential_ref") or exported_pollinations[0]["base_config"].get("api_key_ref")
            assert (
                pollinations_ref in {None, "public://pollinations", "agent://providers/pollinations/acct_01"}
                or str(pollinations_ref).startswith("secret://")
                or str(pollinations_ref).startswith("agent://")
            ) and pollinations_ref != "[redacted]", exported_pollinations[0]
        config_import_plan = assert_ok(client.post("/v1/admin/config-import", headers=headers, json={"snapshot": config_snapshot, "dry_run": True}))
        assert config_import_plan["object"] == "media2api.config_import" and config_import_plan["status"] == "planned", config_import_plan
        assert config_import_plan["summary"]["dry_run"] is True and not config_import_plan["summary"]["errors"], config_import_plan
        contract_suite = assert_ok(
            client.post(
                "/v1/admin/provider-contract-suite",
                headers=headers,
                json={"provider_ids": ["mock"], "operations": ["text_to_image"], "active_only": False, "run_submit": False},
            )
        )
        assert contract_suite["object"] == "media2api.provider_contract_suite" and contract_suite["status"] == "passed", contract_suite
        assert contract_suite["summary"]["passed"] >= 1 and contract_suite["summary"]["failed"] == 0 and contract_suite["summary"]["errors"] == 0, contract_suite
        acceptance_report = assert_ok(client.get("/v1/admin/acceptance-report", headers=headers))
        assert acceptance_report["object"] == "media2api.acceptance_report", acceptance_report
        pre_evidence_core_failures = {
            check["name"]
            for check in acceptance_report.get("failed_checks", [])
            if check.get("scope") == "core" and check.get("required") is True
        }
        assert pre_evidence_core_failures <= {"video_assets_have_thumbnails"}, acceptance_report
        assert any(check["name"] == "required_routes" and check["ok"] for check in acceptance_report["checks"]), acceptance_report
        assert any(check["name"] == "provider_contract_tests" and check["ok"] for check in acceptance_report["checks"]), acceptance_report
        import_provider_id = f"provider_config_import_{suffix}"
        import_model_id = f"model_config_import_{suffix}"
        import_mapping_id = f"mapping_config_import_{suffix}"
        import_account_id = f"acct_config_import_{suffix}"
        import_rule_id = f"price_config_import_{suffix}"
        import_inline_secret_value = f"config-import-inline-secret-{suffix}"
        minimal_snapshot = {
            "object": "media2api.config_snapshot",
            "schema_version": 1,
            "sections": {
                "logical_models": [
                    {
                        "id": import_model_id,
                        "display_name": "Config Import Smoke Model",
                        "operations": ["text_to_image"],
                        "constraints": {"max_prompt_length": 64},
                        "default_params": {"quality": "standard"},
                        "billing_class": "config_import",
                        "enabled": False,
                    }
                ],
                "providers": [
                    {
                        "id": import_provider_id,
                        "name": "Config Import Smoke Provider",
                        "adapter_type": "http_adapter",
                        "status": "disabled",
                        "base_config": {"base_url": "http://127.0.0.1:1", "credential_ref": "env://CONFIG_IMPORT_SMOKE_KEY"},
                        "notes": "created by smoke config import",
                    }
                ],
                "provider_model_mappings": [
                    {
                        "id": import_mapping_id,
                        "logical_model": import_model_id,
                        "provider_id": import_provider_id,
                        "provider_model": "config-import-model",
                        "operations": ["text_to_image"],
                        "priority": 999,
                        "weight": 1,
                        "cost_score": 0.5,
                        "speed_score": 0.5,
                        "quality_score": 0.5,
                        "reliability_score": 0.5,
                        "enabled": False,
                    }
                ],
                "accounts": [
                    {
                        "id": import_account_id,
                        "provider_id": import_provider_id,
                        "label": "Config Import Smoke Account",
                        "credential_ref": f"plain://{import_inline_secret_value}",
                        "supported_operations": ["text_to_image"],
                        "supported_provider_models": ["config-import-model"],
                        "quota_buckets": [{"type": "credits", "remaining_estimate": 5, "confidence": 1}],
                        "concurrency_limit": 1,
                        "region": "smoke",
                        "plan": "config-import",
                        "status": "disabled",
                    }
                ],
                "pricing_rules": [
                    {
                        "id": import_rule_id,
                        "name": "Config Import Smoke Price",
                        "logical_model": import_model_id,
                        "billing_class": "config_import",
                        "operation": "text_to_image",
                        "unit": "image",
                        "base_amount": 0,
                        "unit_amount": 1,
                        "input_asset_amount": 0,
                        "provider_cost_base": 0,
                        "provider_cost_unit": 1,
                        "provider_cost_input_asset": 0,
                        "quality_multipliers": {},
                        "currency": "credits",
                        "enabled": False,
                    }
                ],
            },
        }
        import_dry_run = assert_ok(client.post("/v1/admin/config-import", headers=headers, json={"snapshot": minimal_snapshot, "dry_run": True}))
        assert import_dry_run["status"] == "planned" and import_dry_run["summary"]["created"] >= 5 and not import_dry_run["summary"]["errors"], import_dry_run
        import_apply = assert_ok(client.post("/v1/admin/config-import", headers=headers, json={"snapshot": minimal_snapshot, "dry_run": False}))
        assert import_apply["status"] == "applied" and import_apply["summary"]["applied"] is True and not import_apply["summary"]["errors"], import_apply
        imported_models = assert_ok(client.get("/v1/admin/logical-models", headers=headers))
        assert any(item["id"] == import_model_id and item["enabled"] is False for item in imported_models["data"]), imported_models
        imported_providers = assert_ok(client.get("/v1/providers", headers=headers))
        assert any(item["id"] == import_provider_id and item["status"] == "disabled" for item in imported_providers["data"]), imported_providers
        with SessionLocal() as db:
            imported_account = db.get(db_models.AccountResource, import_account_id)
            imported_secret = db.get(db_models.CredentialSecret, f"secret_{import_account_id}")
            assert imported_account and imported_account.credential_ref == f"secret://secret_{import_account_id}", imported_account.credential_ref if imported_account else None
            assert imported_secret and imported_secret.account_id == import_account_id and imported_secret.provider_id == import_provider_id, imported_secret
        post_import_snapshot = assert_ok(client.get("/v1/admin/config-export", headers=headers))
        assert import_inline_secret_value not in str(post_import_snapshot), post_import_snapshot
        matrix = assert_ok(client.get("/v1/admin/compatibility-matrix?logical_model=t2i-fast&provider_id=mock&operation=text_to_image", headers=headers))
        matrix_accounts = [account for row in matrix["data"] for account in row["accounts"] if account["id"] == bulk_account_id]
        assert matrix_accounts and matrix_accounts[0]["credential"]["type"] == "secret" and matrix_accounts[0]["available"] is True, matrix
        assert matrix_accounts[0]["available_capacity"] == 3, matrix_accounts[0]
        assert all("constraints" in item and "default_params" in item for item in models["data"]), models
        disabled_model_id = f"model_disabled_{suffix}"
        disabled_model = assert_ok(
            client.post(
                "/v1/admin/logical-models",
                headers=headers,
                json={
                    "id": disabled_model_id,
                    "display_name": "Disabled Smoke Model",
                    "operations": ["text_to_image"],
                    "constraints": {"max_prompt_length": 16},
                    "default_params": {"quality": "standard"},
                    "billing_class": "image_fast",
                    "enabled": False,
                },
            )
        )
        assert disabled_model["id"] == disabled_model_id and disabled_model["enabled"] is False
        all_models = assert_ok(client.get("/v1/admin/logical-models", headers=headers))
        assert any(item["id"] == disabled_model_id for item in all_models["data"])
        public_models = assert_ok(client.get("/v1/models", headers=headers))
        assert all(item["id"] != disabled_model_id for item in public_models["data"])
        disabled_create = client.post(
            "/v1/images/generations",
            headers=headers,
            json={"model": disabled_model_id, "prompt": "disabled model should reject", "n": 1},
        )
        assert disabled_create.status_code == 403 and disabled_create.json()["code"] == "LOGICAL_MODEL_DISABLED", disabled_create.text

        constrained_model_id = f"model_constrained_{suffix}"
        constrained_model = assert_ok(
            client.post(
                "/v1/admin/logical-models",
                headers=headers,
                json={
                    "id": constrained_model_id,
                    "display_name": "Constrained Smoke Model",
                    "operations": ["text_to_image"],
                    "constraints": {"max_prompt_length": 4, "max_n": 1, "allowed_quality": ["standard"]},
                    "default_params": {"quality": "standard"},
                    "billing_class": "image_fast",
                    "enabled": True,
                },
            )
        )
        assert constrained_model["constraints"]["max_prompt_length"] == 4
        too_long_prompt = client.post(
            "/v1/images/generations",
            headers=headers,
            json={"model": constrained_model_id, "prompt": "12345", "n": 1},
        )
        assert too_long_prompt.status_code == 400 and too_long_prompt.json()["code"] == "INVALID_INPUT", too_long_prompt.text
        bad_operation_preview = client.post(
            "/v1/router/preview",
            headers=headers,
            json={"model": constrained_model_id, "operation": "image_to_video", "params": {"prompt": "ok"}},
        )
        assert bad_operation_preview.status_code == 400 and bad_operation_preview.json()["code"] == "OPERATION_NOT_SUPPORTED", bad_operation_preview.text
        patched_model = assert_ok(client.patch(f"/v1/admin/logical-models/{constrained_model_id}", headers=headers, json={"enabled": False}))
        assert patched_model["enabled"] is False
        governance_user = f"usr_governance_{suffix}"
        assert_ok(client.post("/v1/admin/users", headers=headers, json={"id": governance_user, "email": f"{governance_user}@media2api.local", "wallet_balance": 100000}))
        governance_key = assert_ok(client.post("/v1/admin/api-keys", headers=headers, json={"user_id": governance_user, "name": "governance-smoke"}))["api_key"]
        governance_headers = {"Authorization": f"Bearer {governance_key}"}
        limit_policy = assert_ok(
            client.post(
                "/v1/admin/user-limit-policies",
                headers=headers,
                json={
                    "id": f"limit_governance_{suffix}",
                    "name": "Governance Smoke Limit",
                    "user_id": governance_user,
                    "requests_per_minute": 60,
                    "daily_job_limit": 1,
                    "concurrent_job_limit": 1,
                    "allowed_models": ["t2i-fast"],
                    "high_cost_models": ["i2v-pro"],
                    "high_cost_allowed": False,
                },
            )
        )
        assert limit_policy["user_id"] == governance_user and limit_policy["daily_job_limit"] == 1
        own_limits = assert_ok(client.get("/v1/governance/limits", headers=governance_headers))
        assert own_limits["policy"]["policy_id"] == f"limit_governance_{suffix}", own_limits
        first_limited_job = assert_ok(
            client.post(
                "/v1/images/generations",
                headers=governance_headers,
                json={"model": "t2i-fast", "prompt": "first limited governance image", "n": 1},
            )
        )
        assert first_limited_job["job_id"]
        second_limited_job = client.post(
            "/v1/images/generations",
            headers=governance_headers,
            json={"model": "t2i-fast", "prompt": "second limited governance image", "n": 1},
        )
        assert second_limited_job.status_code == 429 and second_limited_job.json()["code"] == "DAILY_JOB_LIMIT_EXCEEDED", second_limited_job.text
        high_cost_user = f"usr_highcost_{suffix}"
        assert_ok(client.post("/v1/admin/users", headers=headers, json={"id": high_cost_user, "email": f"{high_cost_user}@media2api.local", "wallet_balance": 100000}))
        high_cost_key = assert_ok(client.post("/v1/admin/api-keys", headers=headers, json={"user_id": high_cost_user, "name": "highcost-smoke"}))["api_key"]
        assert_ok(
            client.post(
                "/v1/admin/user-limit-policies",
                headers=headers,
                json={
                    "id": f"limit_highcost_{suffix}",
                    "name": "High Cost Smoke Limit",
                    "user_id": high_cost_user,
                    "requests_per_minute": 60,
                    "daily_job_limit": 10,
                    "concurrent_job_limit": 10,
                    "high_cost_models": ["i2v-pro"],
                    "high_cost_allowed": False,
                },
            )
        )
        high_cost_block = client.post(
            "/v1/media-jobs",
            headers={"Authorization": f"Bearer {high_cost_key}"},
            json={"operation": "image_to_video", "model": "i2v-pro", "prompt": "should require whitelist", "wait": False},
        )
        assert high_cost_block.status_code == 403 and high_cost_block.json()["code"] == "MODEL_REQUIRES_WHITELIST", high_cost_block.text
        rate_user = f"usr_rate_{suffix}"
        assert_ok(client.post("/v1/admin/users", headers=headers, json={"id": rate_user, "email": f"{rate_user}@media2api.local", "wallet_balance": 100000}))
        rate_key = assert_ok(client.post("/v1/admin/api-keys", headers=headers, json={"user_id": rate_user, "name": "rate-smoke"}))["api_key"]
        assert_ok(
            client.post(
                "/v1/admin/user-limit-policies",
                headers=headers,
                json={
                    "id": f"limit_rate_{suffix}",
                    "name": "Rate Smoke Limit",
                    "user_id": rate_user,
                    "requests_per_minute": 1,
                    "daily_job_limit": 10,
                    "concurrent_job_limit": 10,
                },
            )
        )
        rate_headers = {"Authorization": f"Bearer {rate_key}"}
        assert_ok(client.get("/v1/models", headers=rate_headers))
        rate_limited = client.get("/v1/models", headers=rate_headers)
        assert rate_limited.status_code == 429 and rate_limited.json()["code"] == "RATE_LIMITED", rate_limited.text
        breaker = assert_ok(
            client.post(
                "/v1/admin/circuit-breakers",
                headers=headers,
                json={
                    "id": f"cb_model_t2i_pro_{suffix}",
                    "scope": "model",
                    "target_id": "t2i-pro",
                    "status": "open",
                    "reason": "smoke model circuit",
                    "error_code": "SMOKE_CIRCUIT",
                    "block_minutes": 5,
                },
            )
        )
        assert breaker["scope"] == "model" and breaker["status"] == "open"
        circuit_block = client.post(
            "/v1/images/generations",
            headers=headers,
            json={"model": "t2i-pro", "prompt": "blocked by smoke circuit", "n": 1},
        )
        circuit_body = circuit_block.json()
        assert circuit_block.status_code == 429 and circuit_body["code"] == "CIRCUIT_OPEN" and circuit_body["job_id"], circuit_block.text
        failed_events = assert_ok(client.get(f"/v1/media-jobs/{circuit_body['job_id']}/events", headers=headers))
        assert any(item["event_type"] == "governance_rejected" for item in failed_events["data"]), failed_events
        closed_breaker = assert_ok(client.patch(f"/v1/admin/circuit-breakers/{breaker['id']}", headers=headers, json={"status": "closed", "clear_block_until": True}))
        assert closed_breaker["status"] == "closed"
        retried_job = assert_ok(client.post(f"/v1/media-jobs/{circuit_body['job_id']}/retry", headers=headers, json={"wait": True}))
        assert retried_job["id"] == circuit_body["job_id"] and retried_job["status"] == "completed", retried_job
        retried_events = assert_ok(client.get(f"/v1/admin/media-jobs/{circuit_body['job_id']}/events", headers=headers))
        event_types = [item["event_type"] for item in retried_events["data"]]
        assert "retry_requested" in event_types and "completed" in event_types, retried_events
        admin_jobs = assert_ok(client.get(f"/v1/admin/jobs?status=completed&logical_model=t2i-pro", headers=headers))
        assert any(item["id"] == circuit_body["job_id"] for item in admin_jobs["data"]), admin_jobs
        job_event_metrics = client.get("/metrics")
        assert job_event_metrics.status_code == 200 and "media2api_job_events_total" in job_event_metrics.text
        breaker_list = assert_ok(client.get("/v1/admin/circuit-breakers", headers=headers))
        assert any(item["id"] == breaker["id"] for item in breaker_list["data"])

        expired_job_id = f"job_expired_lease_{suffix}"
        expired_attempt_id = f"attempt_expired_lease_{suffix}"
        expired_lease_id = f"lease_expired_{suffix}"
        with SessionLocal() as db:
            account = db.get(db_models.AccountResource, "acct_mock_default")
            assert account is not None
            account.current_leases += 1
            db.add(
                db_models.MediaJob(
                    id=expired_job_id,
                    user_id="usr_admin",
                    api_key_id=api_keys["data"][0]["id"],
                    operation="text_to_image",
                    logical_model="t2i-fast",
                    normalized_params_json=dumps({"model": "t2i-fast", "prompt": "stuck lease", "n": 1}),
                    input_asset_ids_json=dumps([]),
                    output_asset_ids_json=dumps([]),
                    provider_id="mock",
                    provider_model="mock-image-fast",
                    account_id=account.id,
                    provider_task_id="stuck_provider_task",
                    status="submitting",
                    cost_estimate=1,
                )
            )
            db.flush()
            db.add(
                db_models.MediaJobAttempt(
                    id=expired_attempt_id,
                    job_id=expired_job_id,
                    provider_id="mock",
                    account_id=account.id,
                    provider_model="mock-image-fast",
                    provider_task_id="stuck_provider_task",
                    status="submitting",
                )
            )
            db.add(
                db_models.AccountLease(
                    id=expired_lease_id,
                    job_id=expired_job_id,
                    account_id=account.id,
                    provider_id="mock",
                    provider_model="mock-image-fast",
                    expires_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=1),
                    status="active",
                )
            )
            db.commit()
        lease_sweep = assert_ok(client.post("/v1/admin/account-leases/release-expired", headers=headers))
        assert lease_sweep["expired_leases"] >= 1, lease_sweep
        expired_leases = assert_ok(client.get(f"/v1/admin/account-leases?job_id={expired_job_id}", headers=headers))
        assert expired_leases["data"] and expired_leases["data"][0]["status"] == "expired", expired_leases
        expired_job = assert_ok(client.get(f"/v1/media-jobs/{expired_job_id}", headers=headers))
        assert expired_job["status"] == "expired" and expired_job["error"]["code"] == "LEASE_EXPIRED", expired_job
        expired_attempts = assert_ok(client.get(f"/v1/media-jobs/{expired_job_id}/attempts", headers=headers))
        assert expired_attempts["data"][0]["status"] == "expired" and expired_attempts["data"][0]["error_code"] == "LEASE_EXPIRED", expired_attempts
        expired_accounts = assert_ok(client.get("/v1/accounts", headers=headers))
        expired_account = [item for item in expired_accounts["data"] if item["id"] == "acct_mock_default"][0]
        assert expired_account["last_error_code"] == "LEASE_EXPIRED" and expired_account["last_failed_at"], expired_account
        account_diagnostics = assert_ok(client.get("/v1/admin/accounts/acct_mock_default/diagnostics?limit=10", headers=headers))
        assert account_diagnostics["object"] == "media2api.account_diagnostics", account_diagnostics
        assert account_diagnostics["summary"]["last_error_code"] == "LEASE_EXPIRED", account_diagnostics
        assert account_diagnostics["recent_attempts"] and account_diagnostics["recent_leases"], account_diagnostics
        assert any(item["check"] == "last_account_error" for item in account_diagnostics["action_items"]), account_diagnostics
        expired_events = assert_ok(client.get(f"/v1/media-jobs/{expired_job_id}/events", headers=headers))
        assert any(item["event_type"] == "lease_expired" for item in expired_events["data"]), expired_events
        retried_expired = assert_ok(client.post(f"/v1/media-jobs/{expired_job_id}/retry", headers=headers, json={"wait": True}))
        assert retried_expired["id"] == expired_job_id and retried_expired["status"] == "completed", retried_expired
        lease_metrics = client.get("/metrics")
        assert lease_metrics.status_code == 200 and "media2api_account_leases_total" in lease_metrics.text and "expired" in lease_metrics.text

        cancel_job_id = f"job_cancel_active_{suffix}"
        cancel_attempt_id = f"attempt_cancel_active_{suffix}"
        cancel_lease_id = f"lease_cancel_active_{suffix}"
        with SessionLocal() as db:
            account = db.get(db_models.AccountResource, "acct_mock_default")
            assert account is not None
            account.current_leases += 1
            db.add(
                db_models.MediaJob(
                    id=cancel_job_id,
                    user_id="usr_admin",
                    api_key_id=api_keys["data"][0]["id"],
                    operation="text_to_image",
                    logical_model="t2i-fast",
                    normalized_params_json=dumps({"model": "t2i-fast", "prompt": "cancel active lease", "n": 1}),
                    input_asset_ids_json=dumps([]),
                    output_asset_ids_json=dumps([]),
                    provider_id="mock",
                    provider_model="mock-image-fast",
                    account_id=account.id,
                    provider_task_id="cancel_provider_task",
                    status="submitting",
                    cost_estimate=1,
                )
            )
            db.flush()
            db.add(
                db_models.MediaJobAttempt(
                    id=cancel_attempt_id,
                    job_id=cancel_job_id,
                    provider_id="mock",
                    account_id=account.id,
                    provider_model="mock-image-fast",
                    provider_task_id="cancel_provider_task",
                    status="submitting",
                )
            )
            db.add(
                db_models.AccountLease(
                    id=cancel_lease_id,
                    job_id=cancel_job_id,
                    account_id=account.id,
                    provider_id="mock",
                    provider_model="mock-image-fast",
                    expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=30),
                    status="active",
                )
            )
            db.commit()
        cancelled = assert_ok(client.post(f"/v1/admin/media-jobs/{cancel_job_id}/cancel", headers=headers))
        assert cancelled["status"] == "cancelled" and cancelled["error"]["code"] == "CANCELLED", cancelled
        cancel_leases = assert_ok(client.get(f"/v1/admin/account-leases?job_id={cancel_job_id}", headers=headers))
        assert cancel_leases["data"] and cancel_leases["data"][0]["status"] == "released", cancel_leases
        cancel_attempts = assert_ok(client.get(f"/v1/media-jobs/{cancel_job_id}/attempts", headers=headers))
        assert cancel_attempts["data"][0]["status"] == "cancelled" and cancel_attempts["data"][0]["error_code"] == "CANCELLED", cancel_attempts
        cancel_events = assert_ok(client.get(f"/v1/media-jobs/{cancel_job_id}/events", headers=headers))
        cancelled_event = [item for item in cancel_events["data"] if item["event_type"] == "cancelled"]
        assert cancelled_event and cancelled_event[0]["metadata"]["provider_cancel"]["status"] == "not_supported", cancel_events
        pricing = assert_ok(client.get("/v1/billing/pricing-rules", headers=headers))
        assert any(item["logical_model"] == "t2i-fast" for item in pricing["data"])
        pricing_payload = {
            "id": "price_smoke_disabled",
            "name": "Smoke Disabled Rule",
            "logical_model": "t2i-fast",
            "operation": "text_to_image",
            "unit": "image",
            "unit_amount": 99,
            "provider_cost_unit": 9,
            "enabled": False,
        }
        pricing_resp = client.post("/v1/admin/pricing-rules", headers=headers, json=pricing_payload)
        if pricing_resp.status_code == 409:
            created_pricing = assert_ok(client.patch("/v1/admin/pricing-rules/price_smoke_disabled", headers=headers, json={"enabled": False, "unit_amount": 99}))
        else:
            created_pricing = assert_ok(pricing_resp)
        assert created_pricing["id"] == "price_smoke_disabled" and created_pricing["enabled"] is False
        alert_rules = assert_ok(client.get("/v1/admin/alert-rules", headers=headers))
        assert any(item["id"] == "alert_account_rate_limited" for item in alert_rules["data"])
        custom_alert = {
            "id": "alert_smoke_disabled",
            "name": "Smoke Disabled Alert",
            "event_type": "job_failed",
            "severity": "warning",
            "condition": {"error_codes": ["SMOKE"]},
            "enabled": False,
        }
        alert_resp = client.post("/v1/admin/alert-rules", headers=headers, json=custom_alert)
        if alert_resp.status_code == 409:
            created_alert = assert_ok(client.patch("/v1/admin/alert-rules/alert_smoke_disabled", headers=headers, json={"enabled": False}))
        else:
            created_alert = assert_ok(alert_resp)
        assert created_alert["id"] == "alert_smoke_disabled" and created_alert["enabled"] is False
        assert any(item["id"] == "alert_usage_anomaly" for item in alert_rules["data"])
        fail_model_id = f"anomaly_fail_{suffix}"
        video_model_id = f"anomaly_video_{suffix}"
        with SessionLocal() as db:
            api_key_id = api_keys["data"][0]["id"]
            now = datetime.now(UTC).replace(tzinfo=None)
            db.add(
                db_models.LogicalModel(
                    id=fail_model_id,
                    display_name="Anomaly Failure Smoke",
                    operations_json=dumps(["text_to_image"]),
                    constraints_json=dumps({}),
                    default_params_json=dumps({}),
                    billing_class="image_fast",
                    enabled=True,
                )
            )
            db.add(
                db_models.LogicalModel(
                    id=video_model_id,
                    display_name="Anomaly Video Smoke",
                    operations_json=dumps(["image_to_video"]),
                    constraints_json=dumps({}),
                    default_params_json=dumps({}),
                    billing_class="video_fast",
                    enabled=True,
                )
            )
            for index in range(3):
                db.add(
                    db_models.MediaJob(
                        id=f"job_anomaly_fail_{suffix}_{index}",
                        user_id="usr_admin",
                        api_key_id=api_key_id,
                        operation="text_to_image",
                        logical_model=fail_model_id,
                        normalized_params_json=dumps({"prompt": "anomaly failure"}),
                        input_asset_ids_json=dumps([]),
                        output_asset_ids_json=dumps([]),
                        provider_id=f"anomaly_provider_{suffix}",
                        provider_model="anomaly-failure-model",
                        status="failed",
                        cost_estimate=1,
                        final_cost=0,
                        error_code="PROVIDER_FAILED",
                        error_message="Synthetic anomaly failure.",
                        created_at=now - timedelta(minutes=1),
                        updated_at=now - timedelta(minutes=1),
                    )
                )
            for index in range(2):
                db.add(
                    db_models.MediaJob(
                        id=f"job_anomaly_video_{suffix}_{index}",
                        user_id="usr_admin",
                        api_key_id=api_key_id,
                        operation="image_to_video",
                        logical_model=video_model_id,
                        normalized_params_json=dumps({"prompt": "anomaly video", "duration": 3}),
                        input_asset_ids_json=dumps([]),
                        output_asset_ids_json=dumps([]),
                        provider_id=f"anomaly_video_provider_{suffix}",
                        provider_model="anomaly-video-model",
                        account_id=f"acct_anomaly_video_{suffix}",
                        status="completed",
                        cost_estimate=250,
                        final_cost=250,
                        created_at=now - timedelta(minutes=1),
                        updated_at=now - timedelta(minutes=1),
                    )
                )
            db.commit()
        anomaly_scan = assert_ok(client.post("/v1/admin/anomaly-scan?lookback_minutes=120", headers=headers))
        anomaly_types = [item["dimensions"]["anomaly_type"] for item in anomaly_scan["data"]]
        assert "failure_spike" in anomaly_types and "high_cost_video_burst" in anomaly_types, anomaly_scan
        anomaly_alerts = assert_ok(client.get("/v1/admin/alerts?status=open", headers=headers))
        assert any(item["event_type"] == "usage_anomaly" and item["dimensions"].get("logical_model") == fail_model_id for item in anomaly_alerts["data"]), anomaly_alerts
        assert any(item["event_type"] == "usage_anomaly" and item["dimensions"].get("logical_model") == video_model_id for item in anomaly_alerts["data"]), anomaly_alerts
        safety_policies = assert_ok(client.get("/v1/admin/safety-policies", headers=headers))
        assert any(item["id"] == "safety_block_smoke_marker" for item in safety_policies["data"])
        custom_safety = {
            "id": "safety_smoke_audit_disabled",
            "name": "Smoke Disabled Safety Policy",
            "scope": "global",
            "action": "audit",
            "severity": "info",
            "terms": ["media2api_disabled_safety_marker"],
            "enabled": False,
        }
        safety_resp = client.post("/v1/admin/safety-policies", headers=headers, json=custom_safety)
        if safety_resp.status_code == 409:
            created_safety = assert_ok(client.patch("/v1/admin/safety-policies/safety_smoke_audit_disabled", headers=headers, json={"enabled": False}))
        else:
            created_safety = assert_ok(safety_resp)
        assert created_safety["id"] == "safety_smoke_audit_disabled" and created_safety["enabled"] is False
        platforms = assert_ok(client.get("/v1/target-platforms", headers=headers))
        required_platforms = {
            "openai_image",
            "gemini",
            "grok",
            "qwen",
            "jimeng",
            "kling",
            "luma",
            "runway",
            "midjourney",
            "pollinations",
            "openrouter_image",
            "fal_replicate",
            "seedream_proxy",
            "amux_qwen",
            "flux_stability",
        }
        assert required_platforms.issubset({item["provider_id"] for item in platforms["data"]}), platforms
        templates = assert_ok(client.get("/v1/provider-templates", headers=headers))
        assert required_platforms.issubset({item["id"] for item in templates["data"]}), templates
        pollinations_external_plan = assert_ok(
            client.post(
                "/v1/admin/provider-templates/pollinations/external-acceptance",
                headers=headers,
                json={"dry_run": True, "operations": ["text_to_image"], "run_samples": False},
            )
        )
        assert pollinations_external_plan["status"] == "planned", pollinations_external_plan
        assert pollinations_external_plan["activation"]["plan"]["credential_ref"] == "agent://providers/pollinations/acct_01", pollinations_external_plan
        missing_external = assert_ok(
            client.post(
                "/v1/admin/provider-templates/pollinations/external-acceptance",
                headers=headers,
                json={
                    "credential_ref": f"secret://missing_external_acceptance_{suffix}",
                    "operations": ["text_to_image"],
                    "run_samples": True,
                    "max_samples": 1,
                },
            )
        )
        assert missing_external["status"] == "action_required" and missing_external["error"] == "CREDENTIAL_UNAVAILABLE", missing_external
        mock_caps = assert_ok(client.get("/v1/admin/providers/mock/capabilities", headers=headers))
        assert "text_to_image" in mock_caps["operations"] and "mock-image-fast" in mock_caps["models"], mock_caps
        assert mock_caps["operation_capabilities"]["text_to_image"]["output_kind"] == "image", mock_caps
        assert mock_caps["accounts"]["available_capacity"] >= 1, mock_caps
        caps_list = assert_ok(client.get("/v1/admin/provider-capabilities?provider_id=mock", headers=headers))
        assert caps_list["data"] and caps_list["data"][0]["provider_id"] == "mock", caps_list
        installed = assert_ok(
            client.post(
                "/v1/admin/provider-templates/pollinations/install",
                headers=headers,
                json={
                    "base_url": "http://127.0.0.1:19999",
                    "status": "disabled",
                    "account_id": "acct_pollinations_template_smoke",
                    "enable_mappings": False,
                },
            )
        )
        assert installed["provider"]["id"] == "pollinations"
        assert installed["account"]["id"] == "acct_pollinations_template_smoke"
        assert installed["mappings"] and not installed["mappings"][0]["enabled"]
        connector_base_url = f"http://127.0.0.1:{server.server_port}"
        activated = assert_ok(
            client.post(
                "/v1/admin/provider-templates/openai_image/activate",
                headers=headers,
                json={
                    "base_url": connector_base_url,
                    "status": "active",
                    "account_id": "acct_template_activate_smoke",
                    "credential_value": "template-activate-secret",
                    "credential_secret_id": "secret_template_activate_smoke",
                    "contract_operations": ["text_to_image"],
                    "run_contract_tests": True,
                    "contract_run_submit": False,
                    "run_quota_sync": False,
                },
            )
        )
        assert activated["object"] == "provider_template.activation" and activated["ok"] is True and activated["status"] == "activated", activated
        assert activated["install"]["account"]["credential_ref"] == "secret://secret_template_activate_smoke", activated
        assert activated["install"]["account"]["resource_type"] == "agent_provider", activated
        assert activated["install"]["secret"]["kind"] == "agent_provider", activated
        assert "template-activate-secret" not in str(activated), activated
        assert activated["health_check"]["status"] == "ok", activated["health_check"]
        assert activated["contract_tests"] and activated["contract_tests"][0]["status"] == "passed", activated["contract_tests"]
        assert activated["compatibility"]["data"] and activated["capabilities"]["provider_id"] == "openai_image", activated
        for mapping in activated["install"]["mappings"]:
            assert_ok(client.patch(f"/v1/admin/model-mappings/{mapping['id']}", headers=headers, json={"enabled": False}))
        assert_ok(client.patch("/v1/admin/accounts/acct_template_activate_smoke", headers=headers, json={"status": "disabled", "concurrency_limit": 0}))
        assert_ok(client.patch("/v1/admin/providers/openai_image", headers=headers, json={"status": "disabled"}))
        bad_auth = client.get("/v1/models", headers={"Authorization": "Bearer wrong"})
        assert bad_auth.status_code == 401 and bad_auth.json()["code"] == "INVALID_API_KEY"
        low_user_resp = client.post(
            "/v1/admin/users",
            headers=headers,
            json={"id": "usr_low_balance_smoke", "email": "low-balance-smoke@media2api.local", "wallet_balance": 1},
        )
        if low_user_resp.status_code == 409:
            assert_ok(client.patch("/v1/admin/users/usr_low_balance_smoke", headers=headers, json={"wallet_balance": 1, "status": "active"}))
        else:
            assert_ok(low_user_resp)
        low_key = assert_ok(client.post("/v1/admin/api-keys", headers=headers, json={"user_id": "usr_low_balance_smoke", "name": "low-balance-smoke"}))["api_key"]
        low_balance = client.post(
            "/v1/images/generations",
            headers={"Authorization": f"Bearer {low_key}"},
            json={"model": "t2i-fast", "prompt": "should be rejected", "n": 1},
        )
        assert low_balance.status_code == 402 and low_balance.json()["code"] == "INSUFFICIENT_BALANCE"
        blocked = client.post(
            "/v1/images/generations",
            headers={**headers, "X-Request-ID": "req_smoke_safety_block"},
            json={"model": "t2i-fast", "prompt": "please trigger media2api_forbidden_test", "n": 1},
        )
        blocked_body = blocked.json()
        assert blocked.status_code == 400 and blocked_body["code"] == "SAFETY_REJECTED", blocked_body
        assert blocked_body["job_id"] and blocked_body["policy_id"] == "safety_block_smoke_marker", blocked_body
        blocked_job = assert_ok(client.get(f"/v1/media-jobs/{blocked_body['job_id']}", headers=headers))
        assert blocked_job["status"] == "failed" and blocked_job["final_cost"] == 0, blocked_job
        safety_events = assert_ok(client.get(f"/v1/admin/safety-events?job_id={blocked_body['job_id']}", headers=headers))
        assert safety_events["data"] and safety_events["data"][0]["matched_terms"] == ["media2api_forbidden_test"], safety_events
        own_safety_events = assert_ok(client.get(f"/v1/safety-events?job_id={blocked_body['job_id']}", headers=headers))
        assert own_safety_events["data"] and own_safety_events["data"][0]["status"] == "blocked"
        safety_request_log = assert_ok(client.get("/v1/admin/request-logs?request_id=req_smoke_safety_block", headers=headers))
        assert safety_request_log["data"] and safety_request_log["data"][0]["job_id"] == blocked_body["job_id"], safety_request_log
        assert safety_request_log["data"][0]["standard_error_code"] == "SAFETY_REJECTED" and safety_request_log["data"][0]["logical_model"] == "t2i-fast", safety_request_log
        safety_metrics = client.get("/metrics")
        assert safety_metrics.status_code == 200 and "media2api_safety_events_total" in safety_metrics.text

        uploaded = assert_ok(
            client.post(
                "/v1/assets",
                headers=headers,
                json={"b64_json": base64.b64encode(tiny_png_bytes()).decode("ascii"), "filename": "base64.png", "kind": "image", "purpose": "reference"},
            )
        )
        direct_content = client.get(f"/v1/assets/{uploaded['id']}/content")
        assert direct_content.status_code == 403
        parsed = urlparse(uploaded["url"])
        content = client.get(f"{parsed.path}?{parsed.query}")
        assert content.status_code == 200 and content.headers["content-type"].startswith("image/png")
        admin_uploaded_asset = assert_ok(client.get(f"/v1/admin/assets/{uploaded['id']}", headers=headers))
        assert admin_uploaded_asset["id"] == uploaded["id"] and admin_uploaded_asset["user_id"] == "usr_admin" and admin_uploaded_asset["provider_meta"] == {}, admin_uploaded_asset
        invalid_image = client.post(
            "/v1/assets",
            headers=headers,
            json={"b64_json": base64.b64encode(b"not-an-image").decode("ascii"), "filename": "broken.png", "kind": "image", "purpose": "reference", "mime_type": "image/png"},
        )
        assert invalid_image.status_code == 400 and invalid_image.json()["code"] == "ASSET_IMAGE_INVALID", invalid_image.text
        asset_failure_metrics = client.get("/metrics")
        assert asset_failure_metrics.status_code == 200 and 'asset_ingest_failed_total{' in asset_failure_metrics.text and "mime_type=" in asset_failure_metrics.text

        uploaded_alt = assert_ok(
            client.post(
                "/v1/assets",
                headers=headers,
                json={"b64_json": base64.b64encode(tiny_png_bytes()).decode("ascii"), "filename": "base64-alt.png", "kind": "image", "purpose": "reference"},
            )
        )
        native_complex_image = assert_ok(
            client.post(
                "/v1/media-jobs",
                headers=headers,
                json={
                    "operation": "image_edit",
                    "model": "image-edit",
                    "prompt": "native rich parameter image edit",
                    "image": uploaded["id"],
                    "images": [uploaded["id"], uploaded_alt["id"]],
                    "mask": uploaded["id"],
                    "seed": 12345,
                    "size": "1024x1024",
                    "quality": "high",
                    "negative_prompt": "low quality",
                    "route_policy": "best_quality",
                    "cost_policy": "max_cost:100000",
                    "provider_preference": ["mock"],
                    "providers": ["mock"],
                    "provider_models": ["mock-image-edit"],
                    "wait": True,
                },
            )
        )
        assert native_complex_image["status"] == "completed" and native_complex_image["operation"] == "image_edit", native_complex_image
        assert {uploaded["id"], uploaded_alt["id"]}.issubset(set(native_complex_image["input_asset_ids"])), native_complex_image
        native_image_params = native_complex_image["params"]
        assert native_image_params["images"] == [uploaded["id"], uploaded_alt["id"]], native_image_params
        assert native_image_params["mask"] == uploaded["id"] and native_image_params["seed"] == 12345, native_image_params
        assert native_image_params["quality"] == "high" and native_image_params["negative_prompt"] == "low quality", native_image_params
        assert native_image_params["route_policy"] == "best_quality" and native_image_params["cost_policy"] == "max_cost:100000", native_image_params
        assert native_complex_image["outputs"] and native_complex_image["outputs"][0]["kind"] == "image", native_complex_image
        native_complex_video = assert_ok(
            client.post(
                "/v1/media-jobs",
                headers=headers,
                json={
                    "operation": "image_to_video",
                    "model": "i2v-fast",
                    "prompt": "native rich parameter i2v",
                    "first_frame": uploaded["id"],
                    "last_frame": uploaded_alt["id"],
                    "duration": 3,
                    "aspect_ratio": "16:9",
                    "quality": "standard",
                    "seed": 54321,
                    "negative_prompt": "jitter",
                    "providers": ["mock"],
                    "provider_preference": ["mock"],
                    "provider_models": ["mock-video-fast"],
                    "max_cost": 100000,
                    "wait": True,
                },
            )
        )
        assert native_complex_video["status"] == "completed" and native_complex_video["operation"] == "image_to_video", native_complex_video
        assert {uploaded["id"], uploaded_alt["id"]}.issubset(set(native_complex_video["input_asset_ids"])), native_complex_video
        native_video_params = native_complex_video["params"]
        assert native_video_params["first_frame"] == uploaded["id"] and native_video_params["last_frame"] == uploaded_alt["id"], native_video_params
        assert native_video_params["aspect_ratio"] == "16:9" and native_video_params["seed"] == 54321, native_video_params
        assert native_complex_video["outputs"] and native_complex_video["outputs"][0]["kind"] == "video", native_complex_video
        frame_api_video = assert_ok(
            client.post(
                "/v1/videos/generations",
                headers=headers,
                json={
                    "model": "i2v-fast",
                    "prompt": "openai compatible first last frame i2v",
                    "first_frame": uploaded["id"],
                    "last_frame": uploaded_alt["id"],
                    "duration": 3,
                    "aspect_ratio": "16:9",
                    "provider_preference": ["mock"],
                    "providers": ["mock"],
                    "provider_models": ["mock-video-fast"],
                },
            )
        )
        frame_api_job = None
        for _ in range(20):
            frame_api_job = assert_ok(client.get(f"/v1/media-jobs/{frame_api_video['id']}", headers=headers))
            if frame_api_job["status"] in {"completed", "failed"}:
                break
            time.sleep(0.1)
        assert frame_api_job and frame_api_job["status"] == "completed", frame_api_job
        assert {uploaded["id"], uploaded_alt["id"]}.issubset(set(frame_api_job["input_asset_ids"])), frame_api_job
        assert frame_api_job["params"]["first_frame"] == uploaded["id"] and frame_api_job["params"]["last_frame"] == uploaded_alt["id"], frame_api_job

        asset_limited_model_id = f"model_asset_limited_{suffix}"
        limited_model = assert_ok(
            client.post(
                "/v1/admin/logical-models",
                headers=headers,
                json={
                    "id": asset_limited_model_id,
                    "display_name": "Asset Limited Smoke Model",
                    "operations": ["image_to_video"],
                    "constraints": {"max_input_image_width": 8},
                    "default_params": {"duration": 3, "quality": "standard"},
                    "billing_class": "video_fast",
                    "enabled": True,
                },
            )
        )
        assert limited_model["constraints"]["max_input_image_width"] == 8
        oversized_input = client.post(
            "/v1/media-jobs",
            headers=headers,
            json={"operation": "image_to_video", "model": asset_limited_model_id, "prompt": "reject large input image", "image": uploaded["id"], "wait": True},
        )
        assert oversized_input.status_code == 400 and oversized_input.json()["code"] == "ASSET_IMAGE_WIDTH_TOO_LARGE", oversized_input.text

        original_allowed_hosts = set(settings.asset_remote_url_allowed_hosts)
        original_allow_private = settings.asset_remote_url_allow_private
        settings.asset_remote_url_allowed_hosts = set()
        settings.asset_remote_url_allow_private = False
        try:
            bad_scheme_asset = client.post(
                "/v1/assets",
                headers=headers,
                json={"url": "file:///etc/passwd", "filename": "remote.png", "kind": "image", "purpose": "reference"},
            )
            assert bad_scheme_asset.status_code == 400 and bad_scheme_asset.json()["code"] == "REMOTE_URL_SCHEME_UNSUPPORTED", bad_scheme_asset.text
            private_remote_asset = client.post(
                "/v1/assets",
                headers=headers,
                json={"url": f"http://127.0.0.1:{server.server_port}/remote.png", "filename": "remote.png", "kind": "image", "purpose": "reference"},
            )
            assert private_remote_asset.status_code == 400 and private_remote_asset.json()["code"] == "REMOTE_URL_PRIVATE_ADDRESS_BLOCKED", private_remote_asset.text

            settings.asset_remote_url_allowed_hosts = {"127.0.0.1"}
            remote_asset = assert_ok(
                client.post(
                    "/v1/assets",
                    headers=headers,
                    json={"url": f"http://127.0.0.1:{server.server_port}/remote.png", "filename": "remote.png", "kind": "image", "purpose": "reference"},
                )
            )
            assert remote_asset["source"] == "remote_url" if "source" in remote_asset else remote_asset["id"]
            asset_list = assert_ok(client.get("/v1/assets?kind=image", headers=headers))
            assert any(item["id"] == remote_asset["id"] for item in asset_list["data"])
            deleted = assert_ok(client.delete(f"/v1/assets/{remote_asset['id']}", headers=headers))
            assert deleted["deleted"] is True
            assert client.get(f"/v1/assets/{remote_asset['id']}", headers=headers).status_code == 404
        finally:
            settings.asset_remote_url_allowed_hosts = original_allowed_hosts
            settings.asset_remote_url_allow_private = original_allow_private

        image = assert_ok(
            client.post(
                "/v1/images/generations",
                headers={**headers, "X-Request-ID": "req_smoke_image_generation"},
                json={"model": "t2i-fast", "prompt": "smoke test image", "n": 1},
            )
        )
        assert image["data"][0]["asset_id"]
        admin_assets = assert_ok(client.get(f"/v1/admin/assets?user_id=usr_admin&kind=image&limit=50", headers=headers))
        assert any(item["id"] == image["data"][0]["asset_id"] for item in admin_assets["data"]), admin_assets
        image_b64 = assert_ok(
            client.post(
                "/v1/images/generations",
                headers=headers,
                json={"model": "t2i-fast", "prompt": "smoke test image b64", "n": 1, "response_format": "b64_json"},
            )
        )
        assert image_b64["data"][0]["asset_id"] and image_b64["data"][0]["mime_type"] == "image/png"
        assert base64.b64decode(image_b64["data"][0]["b64_json"]).startswith(b"\x89PNG")
        bad_response_format = client.post(
            "/v1/images/generations",
            headers=headers,
            json={"model": "t2i-fast", "prompt": "bad format", "n": 1, "response_format": "file"},
        )
        assert bad_response_format.status_code == 400 and bad_response_format.json()["code"] == "INVALID_RESPONSE_FORMAT", bad_response_format.text
        image_job = assert_ok(client.get(f"/v1/media-jobs/{image['job_id']}", headers=headers))
        assert image_job["cost_estimate"] >= 1 and image_job["final_cost"] >= 1
        image_job_diagnostics = assert_ok(client.get(f"/v1/admin/media-jobs/{image['job_id']}/diagnostics?limit=100", headers=headers))
        assert image_job_diagnostics["object"] == "media2api.media_job_diagnostics", image_job_diagnostics
        assert image_job_diagnostics["job"]["id"] == image["job_id"], image_job_diagnostics
        assert image_job_diagnostics["summary"]["status"] == "completed", image_job_diagnostics
        assert image_job_diagnostics["summary"]["attempt_count"] >= 1 and image_job_diagnostics["summary"]["lease_count"] >= 1, image_job_diagnostics
        assert image_job_diagnostics["summary"]["output_asset_count"] >= 1 and image_job_diagnostics["summary"]["settled_usage_amount"] >= 1, image_job_diagnostics
        assert image_job_diagnostics["attempts"] and image_job_diagnostics["leases"] and image_job_diagnostics["output_assets"], image_job_diagnostics
        assert image_job_diagnostics["request_logs"], image_job_diagnostics
        assert image_job_diagnostics["billing"]["holds"] and image_job_diagnostics["billing"]["usage_records"], image_job_diagnostics
        assert any(item["kind"] == "event" and item.get("event_type") == "completed" for item in image_job_diagnostics["timeline"]), image_job_diagnostics
        request_logs = assert_ok(client.get("/v1/admin/request-logs?request_id=req_smoke_image_generation", headers=headers))
        assert request_logs["data"], request_logs
        request_log = request_logs["data"][0]
        assert request_log["job_id"] == image["job_id"], request_log
        assert request_log["user_id"] == "usr_admin" and request_log["api_key_id"], request_log
        assert request_log["provider_id"] == image_job["provider"] and request_log["account_id"] == image_job["account_id"], request_log
        assert request_log["logical_model"] == "t2i-fast" and request_log["provider_model"] == image_job["provider_model"], request_log
        assert request_log["provider_task_id"] and request_log["attempt_id"] and request_log["standard_error_code"] == "", request_log
        provider_logs = assert_ok(client.get(f"/v1/admin/request-logs?provider_id={image_job['provider']}&logical_model=t2i-fast", headers=headers))
        assert any(item["job_id"] == image["job_id"] for item in provider_logs["data"]), provider_logs
        own_logs = assert_ok(client.get("/v1/request-logs?request_id=req_smoke_image_generation", headers=headers))
        assert own_logs["data"] and own_logs["data"][0]["status_code"] == 200 and own_logs["data"][0]["provider_id"] == image_job["provider"]

        budget_rejected = client.post(
            "/v1/media-jobs",
            headers=headers,
            json={"operation": "text_to_video", "model": "t2v-general", "prompt": "budget rejected smoke", "duration": 3, "max_cost": 1, "wait": True},
        )
        assert budget_rejected.status_code == 402 and budget_rejected.json()["code"] == "COST_POLICY_REJECTED", budget_rejected.text
        rejected_job_id = budget_rejected.json()["job_id"]
        rejected_job = assert_ok(client.get(f"/v1/media-jobs/{rejected_job_id}", headers=headers))
        assert rejected_job["status"] == "failed" and rejected_job["final_cost"] == 0, rejected_job
        rejected_logs = assert_ok(client.get(f"/v1/admin/request-logs?job_id={rejected_job_id}&error_code=COST_POLICY_REJECTED", headers=headers))
        assert rejected_logs["data"] and rejected_logs["data"][0]["standard_error_code"] == "COST_POLICY_REJECTED", rejected_logs
        rejected_events = assert_ok(client.get(f"/v1/media-jobs/{rejected_job_id}/events", headers=headers))
        assert any(item["event_type"] == "cost_policy_rejected" for item in rejected_events["data"]), rejected_events
        budget_allowed = assert_ok(
            client.post(
                "/v1/media-jobs",
                headers=headers,
                json={"operation": "text_to_image", "model": "t2i-fast", "prompt": "budget allowed smoke", "max_cost": 100, "wait": True},
            )
        )
        assert budget_allowed["status"] == "completed" and budget_allowed["cost_estimate"] <= 100, budget_allowed
        targeted_account_job = assert_ok(
            client.post(
                "/v1/media-jobs",
                headers=headers,
                json={
                    "operation": "text_to_image",
                    "model": "t2i-fast",
                    "prompt": "target a specific account for acceptance smoke",
                    "preferred_account_id": bulk_account_id,
                    "wait": True,
                },
            )
        )
        assert targeted_account_job["status"] == "completed" and targeted_account_job["account_id"] == bulk_account_id, targeted_account_job
        assert targeted_account_job["params"]["preferred_account_id"] == bulk_account_id, targeted_account_job
        account_acceptance = assert_ok(
            client.post(
                f"/v1/admin/accounts/{bulk_account_id}/external-acceptance",
                headers=headers,
                json={
                    "operations": ["text_to_image"],
                    "run_health_check": True,
                    "run_contract_tests": True,
                    "run_quota_sync": True,
                    "run_samples": True,
                    "max_samples": 1,
                    "require_production_ready": False,
                },
            )
        )
        assert account_acceptance["status"] == "passed" and account_acceptance["ok"] is True, account_acceptance
        assert account_acceptance["samples"] and account_acceptance["samples"][0]["account_id"] == bulk_account_id, account_acceptance
        account_acceptance_suite = assert_ok(
            client.post(
                "/v1/admin/account-acceptance-suite",
                headers=headers,
                json={
                    "account_ids": [bulk_account_id],
                    "external_only": False,
                    "operations": ["text_to_image"],
                    "run_health_check": True,
                    "run_contract_tests": True,
                    "run_quota_sync": True,
                    "run_samples": True,
                    "max_samples": 1,
                    "max_accounts": 1,
                    "require_production_ready": False,
                    "dry_run": False,
                },
            )
        )
        assert account_acceptance_suite["status"] == "passed" and account_acceptance_suite["summary"]["passed"] == 1, account_acceptance_suite
        assert account_acceptance_suite["results"][0]["samples"][0]["account_id"] == bulk_account_id, account_acceptance_suite

        edit = assert_ok(
            client.post(
                "/v1/images/edits",
                headers=headers,
                json={"model": "image-edit", "prompt": "mock edit", "image": image["data"][0]["asset_id"]},
            )
        )
        assert edit["data"][0]["asset_id"]
        edit_b64 = assert_ok(
            client.post(
                "/v1/images/edits",
                headers=headers,
                json={"model": "image-edit", "prompt": "mock edit b64", "image": image["data"][0]["asset_id"], "response_format": "b64_json"},
            )
        )
        assert edit_b64["data"][0]["asset_id"] and base64.b64decode(edit_b64["data"][0]["b64_json"]).startswith(b"\x89PNG")

        native_edit = assert_ok(
            client.post(
                "/v1/media-jobs",
                headers=headers,
                json={
                    "operation": "image_edit",
                    "model": "image-edit",
                    "prompt": "native edit with mask and seed",
                    "image": image["data"][0]["asset_id"],
                    "mask": uploaded["id"],
                    "seed": 12345,
                    "negative_prompt": "low quality",
                    "size": "1024x1024",
                    "route_policy": "fastest",
                    "provider_preference": ["mock"],
                    "wait": True,
                },
            )
        )
        assert native_edit["status"] == "completed", native_edit
        assert image["data"][0]["asset_id"] in native_edit["input_asset_ids"] and uploaded["id"] in native_edit["input_asset_ids"], native_edit
        assert native_edit["params"]["seed"] == 12345 and native_edit["params"]["negative_prompt"] == "low quality", native_edit
        assert native_edit["params"]["route_policy"] == "fastest" and native_edit["params"]["provider_preference"] == ["mock"], native_edit
        native_i2i = assert_ok(
            client.post(
                "/v1/media-jobs",
                headers=headers,
                json={
                    "operation": "image_to_image",
                    "model": "image-variation",
                    "prompt": "native image variation",
                    "image": image["data"][0]["asset_id"],
                    "seed": 23456,
                    "quality": "standard",
                    "wait": True,
                },
            )
        )
        assert native_i2i["status"] == "completed" and native_i2i["operation"] == "image_to_image", native_i2i
        assert image["data"][0]["asset_id"] in native_i2i["input_asset_ids"], native_i2i
        assert native_i2i["outputs"] and native_i2i["outputs"][0]["kind"] == "image", native_i2i

        bad_native_asset = client.post(
            "/v1/media-jobs",
            headers=headers,
            json={"operation": "image_edit", "model": "image-edit", "prompt": "bad asset", "image": "asset_missing_native", "wait": True},
        )
        assert bad_native_asset.status_code == 404 and bad_native_asset.json()["code"] == "ASSET_NOT_FOUND", bad_native_asset.text

        native_i2v = assert_ok(
            client.post(
                "/v1/media-jobs",
                headers=headers,
                json={
                    "operation": "image_to_video",
                    "model": "i2v-fast",
                    "prompt": "native i2v first and last frame",
                    "first_frame": image["data"][0]["asset_id"],
                    "last_frame": uploaded["id"],
                    "duration": 3,
                    "aspect_ratio": "16:9",
                    "quality": "standard",
                    "cost_policy": "balanced",
                    "wait": True,
                },
            )
        )
        assert native_i2v["status"] == "completed", native_i2v
        assert image["data"][0]["asset_id"] in native_i2v["input_asset_ids"] and uploaded["id"] in native_i2v["input_asset_ids"], native_i2v
        assert native_i2v["params"]["first_frame"] == image["data"][0]["asset_id"] and native_i2v["params"]["last_frame"] == uploaded["id"], native_i2v

        video = assert_ok(
            client.post(
                "/v1/videos/generations",
                headers=headers,
                json={"model": "i2v-fast", "prompt": "mock video", "image": image["data"][0]["asset_id"], "duration": 3},
            )
        )
        job_id = video["id"]
        final = None
        for _ in range(20):
            final = assert_ok(client.get(f"/v1/media-jobs/{job_id}", headers=headers))
            if final["status"] in {"completed", "failed"}:
                break
            time.sleep(0.1)
        assert final and final["status"] == "completed", final
        assert final["outputs"][0]["asset_id"] if "asset_id" in final["outputs"][0] else final["outputs"][0]["id"]
        video_output = final["outputs"][0]
        assert video_output["kind"] == "video" and video_output["thumbnail_asset_id"], video_output
        extended_video = assert_ok(
            client.post(
                "/v1/media-jobs",
                headers=headers,
                json={
                    "operation": "video_extend",
                    "model": "video-extend",
                    "prompt": "native video extend",
                    "video": video_output["id"],
                    "duration": 2,
                    "quality": "standard",
                    "wait": True,
                },
            )
        )
        assert extended_video["status"] == "completed" and extended_video["operation"] == "video_extend", extended_video
        assert video_output["id"] in extended_video["input_asset_ids"], extended_video
        assert extended_video["outputs"] and extended_video["outputs"][0]["kind"] == "video", extended_video
        thumb = assert_ok(client.get(f"/v1/assets/{video_output['thumbnail_asset_id']}", headers=headers))
        assert thumb["kind"] == "thumbnail" and thumb["parent_asset_id"] == video_output["id"], thumb
        thumb_url = urlparse(video_output["thumbnail_url"])
        thumb_content = client.get(f"{thumb_url.path}?{thumb_url.query}")
        assert thumb_content.status_code == 200 and thumb_content.headers["content-type"].startswith("image/png")
        attempts = assert_ok(client.get(f"/v1/media-jobs/{job_id}/attempts", headers=headers))
        assert attempts["data"] and attempts["data"][0]["status"] == "completed"
        assert attempts["data"][0]["started_at"] and attempts["data"][0]["finished_at"], attempts
        health = assert_ok(client.post("/v1/admin/providers/mock/health-check", headers=headers))
        assert health["status"] == "ok"
        health_list = assert_ok(client.get("/v1/admin/provider-health", headers=headers))
        assert any(item["provider_id"] == "mock" for item in health_list["data"])
        jobs = assert_ok(client.get("/v1/jobs", headers=headers))
        assert any(job["id"] == job_id for job in jobs["data"])
        usage = assert_ok(client.get("/v1/billing/usage", headers=headers))
        assert len(usage["data"]) >= 1
        summary = assert_ok(client.get("/v1/billing/summary", headers=headers))
        assert summary["settled_usage_amount"] >= 1 and summary["provider_cost_amount"] >= 1
        invoice = assert_ok(client.get("/v1/billing/invoice", headers=headers))
        assert invoice["object"] == "billing.invoice" and invoice["user_id"] == "usr_admin", invoice
        assert invoice["totals"]["settled_usage_amount"] >= 1 and invoice["totals"]["provider_cost_amount"] >= 1, invoice
        assert any(item["type"] == "usage" and item["logical_model"] == "t2i-fast" for item in invoice["line_items"]), invoice
        invoice_csv = client.get("/v1/billing/invoice?format=csv", headers=headers)
        assert invoice_csv.status_code == 200 and invoice_csv.headers["content-type"].startswith("text/csv") and "invoice_id" in invoice_csv.text, invoice_csv.text
        provider_costs = assert_ok(client.get("/v1/admin/provider-costs", headers=headers))
        assert provider_costs["data"]
        admin_invoice = assert_ok(client.get("/v1/admin/billing-invoices", headers=headers))
        assert admin_invoice["object"] == "billing.invoice" and admin_invoice["user_id"] is None, admin_invoice
        assert admin_invoice["totals"]["settled_usage_amount"] >= invoice["totals"]["settled_usage_amount"], admin_invoice
        scoped_admin_invoice = assert_ok(client.get("/v1/admin/billing-invoices?user_id=usr_admin", headers=headers))
        assert scoped_admin_invoice["user_id"] == "usr_admin" and scoped_admin_invoice["totals"]["settled_usage_amount"] == invoice["totals"]["settled_usage_amount"], scoped_admin_invoice
        admin_invoice_csv = client.get("/v1/admin/billing-invoices?format=csv&user_id=usr_admin", headers=headers)
        assert admin_invoice_csv.status_code == 200 and "provider_cost" in admin_invoice_csv.text, admin_invoice_csv.text
        analytics = assert_ok(client.get("/v1/admin/analytics?group_by=provider_id,logical_model", headers=headers))
        assert analytics["object"] == "admin.analytics" and analytics["totals"]["jobs"] >= 1, analytics
        assert any(row["dimensions"].get("provider_id") == image_job["provider"] and row["dimensions"].get("logical_model") == "t2i-fast" for row in analytics["data"]), analytics
        account_analytics = assert_ok(client.get(f"/v1/admin/analytics?group_by=account_id&account_id={image_job['account_id']}", headers=headers))
        assert account_analytics["data"] and account_analytics["data"][0]["dimensions"]["account_id"] == image_job["account_id"], account_analytics
        assert account_analytics["data"][0]["revenue_amount"] >= 1 and account_analytics["data"][0]["provider_cost_amount"] >= 1, account_analytics
        failure_analytics = assert_ok(client.get("/v1/admin/analytics?group_by=status&status=failed", headers=headers))
        assert any(row["error_codes"] for row in failure_analytics["data"]), failure_analytics
        invalid_analytics = client.get("/v1/admin/analytics?group_by=provider_id,bad_dimension", headers=headers)
        assert invalid_analytics.status_code == 400 and invalid_analytics.json()["code"] == "INVALID_ANALYTICS_DIMENSION", invalid_analytics.text
        holds = assert_ok(client.get("/v1/admin/billing-holds", headers=headers))
        assert holds["data"]
        print("smoke ok")
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
