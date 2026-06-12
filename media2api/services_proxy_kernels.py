from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import tarfile
import time
from typing import Any
import urllib.error
import urllib.request
from urllib.parse import urlparse
import zipfile

from sqlalchemy.orm import Session

from . import models
from .config import settings
from .provider_templates import FINALIZED_PROVIDER_IDS
from .utils import dumps, loads


@dataclass(frozen=True)
class ProxyKernelSpec:
    selection_id: str
    provider_id: str
    repo: str
    runtime_kind: str
    operations: list[str]
    first_phase_role: str
    credential_boundary: str
    media_scope: str
    notes: str

    @property
    def repo_url(self) -> str:
        return f"https://github.com/{self.repo}"


KERNEL_SPECS: dict[str, ProxyKernelSpec] = {
    "openai_web_session": ProxyKernelSpec(
        "OAI-WEB-01",
        "openai_web_session",
        "basketikun/chatgpt2api",
        "web_session_runner",
        ["text_to_image", "image_to_image", "image_edit"],
        "ChatGPT Web session image execution reference.",
        "ChatGPT Web cookie/session only; never mix with Codex profile material.",
        "/v1/images/generations and /v1/images/edits",
        "Release/binary preferred when available; otherwise use as protocol reference for a platform-native adapter.",
    ),
    "openai_codex": ProxyKernelSpec(
        "OAI-CODEX-04",
        "openai_codex",
        "cnlimiter/codex-manager",
        "agent_profile_runner",
        ["text_to_image", "image_to_image", "image_edit"],
        "Codex account control plus GPT Image 2 validation reference.",
        "Codex OAuth/profile/account export only; never mix with ChatGPT Web cookies.",
        "/v1/images/generations and /v1/images/edits",
        "Account control can be integrated before media samples are production-ready.",
    ),
    "gemini_cli_oauth": ProxyKernelSpec(
        "GEM-CLI-02",
        "gemini_cli_oauth",
        "router-for-me/CLIProxyAPI",
        "agent_profile_runner",
        ["text_to_image", "image_to_image", "image_edit", "text_to_video", "image_to_video"],
        "Gemini CLI OAuth/profile bridge with media validation.",
        "Gemini CLI OAuth/profile material only; keep separate from Gemini Web session and Antigravity.",
        "/v1/images/* and /v1/videos/*",
        "Use fixed release/hash when a compatible binary exists.",
    ),
    "gemini_web_session": ProxyKernelSpec(
        "GEM-WEB-01",
        "gemini_web_session",
        "HanaokaYuzu/Gemini-API",
        "web_session_runner",
        ["text_to_image", "image_to_image", "image_edit", "text_to_video", "image_to_video"],
        "Gemini Web session image/video wrapper reference.",
        "Gemini Web cookie/session only; keep separate from CLI OAuth profiles.",
        "/v1/images/* and /v1/videos/*",
        "Prefer release/binary if provided; otherwise use as protocol reference.",
    ),
    "antigravity": ProxyKernelSpec(
        "AG-01",
        "antigravity",
        "ink1ing/anti-api",
        "agent_profile_runner",
        ["text_to_image", "image_to_image", "image_edit", "text_to_video", "image_to_video"],
        "Antigravity account/proxy/diagnostics reference.",
        "Antigravity profile/session material only; keep separate from Gemini.",
        "media capability is not a first strong promise until live validation passes",
        "First phase focuses on account/runtime health before media routing.",
    ),
    "grok": ProxyKernelSpec(
        "GROK-01",
        "grok",
        "chenyme/grok2api",
        "web_session_runner",
        ["text_to_image", "image_to_image", "text_to_video", "image_to_video"],
        "Grok Web/session image and video execution reference.",
        "Grok Web/session material plus matching User-Agent.",
        "/v1/images/* and /v1/videos/*",
        "Run only as controlled loopback runtime or rewrite adapter logic.",
    ),
    "jimeng_web_session": ProxyKernelSpec(
        "JM-01",
        "jimeng_web_session",
        "iptag/jimeng-api",
        "web_session_runner",
        ["text_to_image", "image_to_image", "image_edit"],
        "Jimeng/Dreamina image reverse-proxy reference.",
        "Jimeng/Dreamina Web session only; keep separate from Doubao.",
        "/v1/images/*",
        "Video remains outside this kernel's first commitment.",
    ),
    "doubao_web_session": ProxyKernelSpec(
        "DOUBAO-WEB-01",
        "doubao_web_session",
        "wangchuxiaoji-oss/doubao2api",
        "web_session_runner",
        ["text_to_image", "image_to_image", "image_edit", "text_to_video", "image_to_video"],
        "Doubao Web/session image and video reference.",
        "Doubao Web session only; quotas and accounts stay separate from Jimeng.",
        "/v1/images/* and /v1/videos/*",
        "Selected because Doubao daily quotas differ from Jimeng/Dreamina.",
    ),
    "kling_web_session": ProxyKernelSpec(
        "KLING-WEB-01",
        "kling_web_session",
        "yihong0618/klingCreator",
        "web_session_runner",
        ["text_to_video", "image_to_video", "video_extend"],
        "Kling Web/session video execution reference.",
        "Kling Web session/cookie material only.",
        "/v1/videos/*",
        "Image endpoints are not part of this first runtime scope.",
    ),
    "luma_web_session": ProxyKernelSpec(
        "LUMA-WEB-01",
        "luma_web_session",
        "yihong0618/LumaDreamCreator",
        "web_session_runner",
        ["text_to_video", "image_to_video", "video_extend"],
        "Luma Web cookie video execution reference.",
        "Luma Web cookie/session material only.",
        "/v1/videos/*",
        "Use only loopback runtime registration or adapter rewrite.",
    ),
    "midjourney_discord_session": ProxyKernelSpec(
        "MID-01",
        "midjourney_discord_session",
        "trueai-org/midjourney-proxy",
        "discord_session_runner",
        ["text_to_image", "image_to_image"],
        "Midjourney Discord/session task-channel proxy reference.",
        "Discord/Midjourney session plus guild/channel; do not expose upstream proxy publicly.",
        "imagine, upscale, variation, asset ingestion",
        "Requires guild_id and channel_id profile fields before runtime validation.",
    ),
    "qwen_ai_web_session": ProxyKernelSpec(
        "QWEN-AI-01",
        "qwen_ai_web_session",
        "Rfym21/Qwen2API",
        "web_session_runner",
        ["text_to_image", "image_to_image", "image_edit", "text_to_video", "image_to_video"],
        "qwen.ai/chat.qwen.ai/portal.qwen.ai Web session reference.",
        "qwen.ai family Web session only; never mix with qianwen.com.",
        "/v1/images/* and /v1/videos/* after live validation",
        "Keep separate from Qwen Code/CLI and qianwen.com.",
    ),
    "qianwen_web_session": ProxyKernelSpec(
        "QIANWEN-WEB-01",
        "qianwen_web_session",
        "kao0312/qianwen2api",
        "web_session_runner",
        ["text_to_image", "image_to_image", "image_edit", "text_to_video", "image_to_video"],
        "qianwen.com/Tongyi Qianwen Web reference.",
        "qianwen.com Web session only; never mix with qwen.ai.",
        "account/runtime first, media endpoints require separate validation",
        "Do not mark production media-ready before image/video samples pass.",
    ),
}


def finalized_kernel_provider_ids() -> list[str]:
    return [provider_id for provider_id in FINALIZED_PROVIDER_IDS if provider_id in KERNEL_SPECS]


class ProxyKernelRuntimeService:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or settings.proxy_kernel_dir
        self.source_root = settings.source_repo_dir

    def state_path(self) -> Path:
        return self.root / "state.json"

    def load_state(self) -> dict[str, Any]:
        path = self.state_path()
        if not path.exists():
            return {"version": 1, "kernels": {}}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {"version": 1, "kernels": {}}
        if not isinstance(data, dict):
            return {"version": 1, "kernels": {}}
        data.setdefault("version", 1)
        data.setdefault("kernels", {})
        return data

    def save_state(self, state: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_path().write_text(dumps(state), encoding="utf-8")

    def spec_payload(self, spec: ProxyKernelSpec) -> dict[str, Any]:
        payload = asdict(spec)
        payload["repo_url"] = spec.repo_url
        payload["release_api_url"] = f"https://api.github.com/repos/{spec.repo}/releases"
        payload["install_policy"] = {
            "preferred_source": "github_release_binary",
            "full_source_checkout": "source-repo only when release binary is missing or protocol inspection is required",
            "hash_required": True,
            "listener": "loopback_only",
            "public_exposure": "forbidden",
        }
        payload["source_repo_policy"] = {
            "root": str(self.source_root),
            "allowed_repo": spec.repo,
            "checkout": "source-repo only when release binary is missing, protocol inspection is required, or adapter rewrite is needed",
        }
        return payload

    def live_acceptance_evidence(self, db: Session, provider_id: str, operations: list[str]) -> dict[str, Any]:
        operation_evidence: dict[str, dict[str, Any]] = {}
        for operation in operations:
            job = (
                db.query(models.MediaJob)
                .filter(
                    models.MediaJob.provider_id == provider_id,
                    models.MediaJob.operation == operation,
                    models.MediaJob.status == "completed",
                    models.MediaJob.output_asset_ids_json != "[]",
                )
                .order_by(models.MediaJob.updated_at.desc(), models.MediaJob.created_at.desc())
                .first()
            )
            if not job:
                operation_evidence[operation] = {"operation": operation, "ok": False, "status": "missing"}
                continue
            asset_ids = [str(item) for item in loads(job.output_asset_ids_json, []) if str(item)]
            operation_evidence[operation] = {
                "operation": operation,
                "ok": bool(asset_ids),
                "status": "passed" if asset_ids else "asset_missing",
                "job_id": job.id,
                "logical_model": job.logical_model,
                "provider_model": job.provider_model,
                "account_id": job.account_id,
                "provider_task_id": job.provider_task_id,
                "asset_ids": asset_ids,
                "completed_at": job.updated_at.isoformat() + "Z",
            }
        missing = [operation for operation, item in operation_evidence.items() if not item.get("ok")]
        return {
            "required_operations": operations,
            "passed_operations": [operation for operation, item in operation_evidence.items() if item.get("ok")],
            "missing_operations": missing,
            "operation_evidence": operation_evidence,
            "ok": bool(operations) and not missing,
        }

    def route_evidence(self, db: Session, provider_id: str, operations: list[str]) -> dict[str, Any]:
        mappings = (
            db.query(models.ProviderModelMapping)
            .filter(models.ProviderModelMapping.provider_id == provider_id, models.ProviderModelMapping.enabled.is_(True))
            .all()
        )
        covered: set[str] = set()
        for mapping in mappings:
            for operation in loads(mapping.operations_json, []):
                if operation:
                    covered.add(str(operation))
        missing = [operation for operation in operations if operation not in covered]
        return {
            "enabled_mapping_count": len(mappings),
            "covered_operations": sorted(covered),
            "missing_operations": missing,
            "ok": bool(operations) and not missing,
        }

    def latest_health_evidence(self, db: Session, provider_id: str) -> dict[str, Any]:
        check = (
            db.query(models.ProviderHealthCheck)
            .filter(models.ProviderHealthCheck.provider_id == provider_id)
            .order_by(models.ProviderHealthCheck.created_at.desc())
            .first()
        )
        if not check:
            return {"status": "missing", "ok": False}
        return {
            "status": check.status,
            "ok": check.status == "ok",
            "latency_ms": check.latency_ms,
            "message": check.message,
            "checked_at": check.created_at.isoformat() + "Z",
            "detail": loads(check.detail_json, {}),
        }

    def kernel_summary(self, db: Session, provider_id: str) -> dict[str, Any]:
        spec = KERNEL_SPECS.get(provider_id)
        if not spec:
            raise KeyError(provider_id)
        state = self.load_state().get("kernels", {}).get(provider_id, {})
        provider = db.get(models.Provider, provider_id)
        accounts = db.query(models.AccountResource).filter(models.AccountResource.provider_id == provider_id).all()
        active_accounts = [item for item in accounts if item.status == "active"]
        config = loads(provider.base_config_json, {}) if provider else {}
        base_url = str(config.get("base_url") or state.get("runtime", {}).get("base_url") or "").strip()
        runtime_registered = bool(base_url)
        installed = state.get("install", {})
        installed_verified = bool(installed.get("sha256") and installed.get("expected_sha256") == installed.get("sha256"))
        process = self.process_status(provider_id)
        managed_process_configured = bool(process.get("pid"))
        runtime_ready = bool(runtime_registered and self.is_loopback_url(base_url) and (not managed_process_configured or process.get("running")))
        hash_ready = bool(not installed or installed_verified)
        route_evidence = self.route_evidence(db, provider_id, spec.operations)
        route_ready = bool(route_evidence.get("ok"))
        health_evidence = self.latest_health_evidence(db, provider_id)
        health_ok = bool(health_evidence.get("ok"))
        ready_for_live_acceptance = bool(provider and active_accounts and route_ready and runtime_ready and hash_ready and health_ok)
        live_acceptance = self.live_acceptance_evidence(db, provider_id, spec.operations)
        live_acceptance_ok = bool(live_acceptance.get("ok"))
        blockers: list[dict[str, Any]] = []
        if not provider:
            blockers.append({"code": "PROVIDER_NOT_INITIALIZED", "message": "Import a real account or register the provider template first."})
        if not route_ready:
            blockers.append({"code": "NO_ROUTE_MAPPING", "message": "Apply provider/model mappings for every declared media operation.", "missing_operations": route_evidence.get("missing_operations", [])})
        if not active_accounts:
            blockers.append({"code": "NO_ACTIVE_ACCOUNT", "message": "Import an authorized Web session or Agent Provider profile for this provider."})
        if not runtime_registered:
            blockers.append({"code": "NO_LOOPBACK_RUNTIME", "message": "Register a verified loopback runtime or complete a native adapter rewrite."})
        if installed and not installed_verified:
            blockers.append({"code": "KERNEL_HASH_NOT_VERIFIED", "message": "Installed artifact hash does not match the expected SHA256."})
        if managed_process_configured and not process.get("running"):
            blockers.append({"code": "KERNEL_PROCESS_STOPPED", "message": "Managed kernel process is not running."})
        if provider and active_accounts and route_ready and runtime_ready and hash_ready and not health_ok:
            blockers.append({"code": "RUNTIME_HEALTH_REQUIRED", "message": "Run a successful provider health check against the loopback runtime before live acceptance.", "latest_health": health_evidence})
        if ready_for_live_acceptance and not live_acceptance_ok:
            blockers.append({"code": "LIVE_ACCEPTANCE_REQUIRED", "message": "Run live image/video acceptance samples for every declared operation before marking this kernel directly usable.", "missing_operations": live_acceptance.get("missing_operations", [])})
        return {
            "object": "media2api.proxy_kernel",
            "provider_id": provider_id,
            "selection_id": spec.selection_id,
            "spec": self.spec_payload(spec),
            "provider_status": provider.status if provider else "missing",
            "account_count": len(accounts),
            "active_account_count": len(active_accounts),
            "runtime_registered": runtime_registered,
            "runtime_base_url": base_url,
            "runtime_loopback_only": self.is_loopback_url(base_url) if base_url else False,
            "installed": installed,
            "installed_verified": installed_verified,
            "process": process,
            "route_ready": route_ready,
            "route_evidence": route_evidence,
            "runtime_ready": runtime_ready,
            "latest_health": health_evidence,
            "health_ok": health_ok,
            "ready_for_live_acceptance": ready_for_live_acceptance,
            "live_acceptance": live_acceptance,
            "live_acceptance_ok": live_acceptance_ok,
            "state": state,
            "usable": bool(ready_for_live_acceptance and live_acceptance_ok),
            "directly_usable": bool(ready_for_live_acceptance and live_acceptance_ok),
            "blockers": blockers,
        }

    def list_kernels(self, db: Session) -> dict[str, Any]:
        data = [self.kernel_summary(db, provider_id) for provider_id in finalized_kernel_provider_ids()]
        return {
            "object": "media2api.proxy_kernel.list",
            "data": data,
            "summary": {
                "total": len(data),
                "usable": sum(1 for item in data if item["usable"]),
                "ready_for_live_acceptance": sum(1 for item in data if item.get("ready_for_live_acceptance")),
                "needs_live_acceptance": sum(1 for item in data if any(blocker["code"] == "LIVE_ACCEPTANCE_REQUIRED" for blocker in item["blockers"])),
                "needs_route": sum(1 for item in data if any(blocker["code"] == "NO_ROUTE_MAPPING" for blocker in item["blockers"])),
                "needs_account": sum(1 for item in data if any(blocker["code"] == "NO_ACTIVE_ACCOUNT" for blocker in item["blockers"])),
                "needs_runtime": sum(1 for item in data if any(blocker["code"] == "NO_LOOPBACK_RUNTIME" for blocker in item["blockers"])),
                "needs_hash": sum(1 for item in data if any(blocker["code"] == "KERNEL_HASH_NOT_VERIFIED" for blocker in item["blockers"])),
                "needs_health": sum(1 for item in data if any(blocker["code"] == "RUNTIME_HEALTH_REQUIRED" for blocker in item["blockers"])),
            },
            "policy": [
                "Use release binaries first when available.",
                "Every managed artifact must be fixed-version and fixed-SHA256.",
                "Managed runtimes must listen only on loopback/local socket.",
                "The platform remains the public API, account pool, audit, billing, and asset owner.",
            ],
        }

    def probe_release(self, provider_id: str) -> dict[str, Any]:
        spec = self.require_spec(provider_id)
        releases = self.github_json(f"https://api.github.com/repos/{spec.repo}/releases")
        if isinstance(releases, dict) and releases.get("error"):
            return {"object": "media2api.proxy_kernel.release_probe", "provider_id": provider_id, "status": "failed", **releases}
        if not isinstance(releases, list):
            return {
                "object": "media2api.proxy_kernel.release_probe",
                "provider_id": provider_id,
                "status": "no_release",
                "message": "GitHub releases response was empty or not a list.",
                "repo_url": spec.repo_url,
            }
        public_releases = [item for item in releases if isinstance(item, dict) and not item.get("draft")]
        if not public_releases:
            return {
                "object": "media2api.proxy_kernel.release_probe",
                "provider_id": provider_id,
                "status": "no_release",
                "message": "No public release was found. Use source-repo only for protocol inspection or adapter rewrite.",
                "repo_url": spec.repo_url,
            }
        release = public_releases[0]
        assets = [self.asset_payload(asset) for asset in release.get("assets") or [] if isinstance(asset, dict)]
        return {
            "object": "media2api.proxy_kernel.release_probe",
            "provider_id": provider_id,
            "status": "ok" if assets else "release_without_assets",
            "selection_id": spec.selection_id,
            "repo_url": spec.repo_url,
            "release": {
                "tag_name": release.get("tag_name"),
                "name": release.get("name"),
                "html_url": release.get("html_url"),
                "published_at": release.get("published_at"),
                "prerelease": bool(release.get("prerelease")),
            },
            "assets": assets,
            "preferred_assets": [asset for asset in assets if asset["candidate_score"] > 0],
            "hash_required": True,
            "next_step": "Select an asset and provide its expected_sha256 to /install-release before using it as a managed runtime.",
        }

    def install_release(
        self,
        provider_id: str,
        expected_sha256: str,
        asset_name: str | None = None,
        tag_name: str | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        spec = self.require_spec(provider_id)
        expected = self.normalize_sha256(expected_sha256)
        if not expected:
            raise ValueError("EXPECTED_SHA256_REQUIRED")
        probe = self.probe_release(provider_id)
        if probe.get("status") not in {"ok", "release_without_assets"}:
            raise ValueError("RELEASE_NOT_AVAILABLE")
        release = probe.get("release") or {}
        if tag_name and release.get("tag_name") != tag_name:
            releases = self.github_json(f"https://api.github.com/repos/{spec.repo}/releases/tags/{tag_name}")
            if isinstance(releases, dict) and releases.get("error"):
                raise ValueError("RELEASE_TAG_NOT_FOUND")
            assets = [self.asset_payload(asset) for asset in releases.get("assets") or [] if isinstance(asset, dict)]
            release = {
                "tag_name": releases.get("tag_name"),
                "name": releases.get("name"),
                "html_url": releases.get("html_url"),
                "published_at": releases.get("published_at"),
                "prerelease": bool(releases.get("prerelease")),
            }
        else:
            assets = probe.get("assets") or []
        asset = self.pick_asset(assets, asset_name)
        if not asset:
            raise ValueError("RELEASE_ASSET_NOT_FOUND")
        install_dir = self.root / provider_id / str(release.get("tag_name") or "latest")
        install_dir.mkdir(parents=True, exist_ok=True)
        target = install_dir / self.safe_filename(asset["name"])
        if target.exists() and not force:
            current_sha = self.file_sha256(target)
            if current_sha == expected:
                extraction = self.extract_release_asset(provider_id, target, install_dir)
                return self.record_install(provider_id, release, asset, target, expected, current_sha, reused=True, extraction=extraction)
            raise ValueError("TARGET_EXISTS_WITH_DIFFERENT_HASH")
        request = urllib.request.Request(asset["browser_download_url"], headers=self.github_headers())
        with urllib.request.urlopen(request, timeout=120) as response:
            target.write_bytes(response.read())
        actual = self.file_sha256(target)
        if actual != expected:
            target.unlink(missing_ok=True)
            raise ValueError("SHA256_MISMATCH")
        extraction = self.extract_release_asset(provider_id, target, install_dir)
        return self.record_install(provider_id, release, asset, target, expected, actual, reused=False, extraction=extraction)

    def register_runtime(
        self,
        provider_id: str,
        base_url: str,
        version: str = "",
        binary_path: str = "",
        sha256: str = "",
        notes: str = "",
    ) -> dict[str, Any]:
        self.require_spec(provider_id)
        url = (base_url or "").strip().rstrip("/")
        if not self.is_loopback_url(url):
            raise ValueError("LOOPBACK_RUNTIME_REQUIRED")
        state = self.load_state()
        kernels = state.setdefault("kernels", {})
        entry = kernels.setdefault(provider_id, {})
        entry["runtime"] = {
            "base_url": url,
            "version": version,
            "binary_path": binary_path,
            "sha256": self.normalize_sha256(sha256),
            "notes": notes,
            "registered_at": self.utcnow(),
            "loopback_only": True,
        }
        self.save_state(state)
        return {"object": "media2api.proxy_kernel.runtime", "provider_id": provider_id, "runtime": entry["runtime"]}

    def clear_runtime(self, provider_id: str) -> dict[str, Any]:
        self.require_spec(provider_id)
        state = self.load_state()
        entry = state.setdefault("kernels", {}).setdefault(provider_id, {})
        process = entry.get("process") if isinstance(entry.get("process"), dict) else {}
        pid = int(process.get("pid") or 0)
        if pid and self.pid_running(pid):
            self.stop_runtime(provider_id, grace_seconds=5)
            state = self.load_state()
            entry = state.setdefault("kernels", {}).setdefault(provider_id, {})
        entry.pop("runtime", None)
        entry.pop("process", None)
        self.save_state(state)
        return {"object": "media2api.proxy_kernel.runtime", "provider_id": provider_id, "runtime": {}}

    def source_repo_status(self, provider_id: str) -> dict[str, Any]:
        spec = self.require_spec(provider_id)
        state = self.load_state()
        entry = state.get("kernels", {}).get(provider_id, {})
        source = entry.get("source_repo") if isinstance(entry.get("source_repo"), dict) else {}
        path = self.source_repo_path(spec)
        git_dir = path / ".git"
        exists = path.exists()
        is_git_repo = git_dir.exists() and git_dir.is_dir()
        remote_url = self.git_output(path, ["remote", "get-url", "origin"]) if is_git_repo else ""
        current_ref = self.git_output(path, ["rev-parse", "--abbrev-ref", "HEAD"]) if is_git_repo else ""
        head = self.git_output(path, ["rev-parse", "HEAD"]) if is_git_repo else ""
        dirty = bool(self.git_output(path, ["status", "--porcelain"])) if is_git_repo else False
        return {
            "object": "media2api.proxy_kernel.source_repo",
            "provider_id": provider_id,
            "selection_id": spec.selection_id,
            "repo": spec.repo,
            "repo_url": spec.repo_url,
            "path": str(path),
            "exists": exists,
            "is_git_repo": is_git_repo,
            "remote_url": remote_url,
            "current_ref": current_ref,
            "head": head,
            "dirty": dirty,
            "state": source,
            "policy": {
                "allowlist_only": True,
                "root": str(self.source_root),
                "purpose": "protocol inspection, local build input, or adapter rewrite reference when release binary is insufficient",
            },
        }

    def sync_source_repo(self, provider_id: str, ref: str = "", force: bool = False) -> dict[str, Any]:
        spec = self.require_spec(provider_id)
        ref = (ref or "").strip()
        if ref and not re.fullmatch(r"[A-Za-z0-9._/\-]+", ref):
            raise ValueError("INVALID_GIT_REF")
        path = self.source_repo_path(spec)
        root = self.source_root.resolve()
        if not self.path_within(path.resolve(), root):
            raise ValueError("SOURCE_REPO_OUTSIDE_ROOT")
        root.mkdir(parents=True, exist_ok=True)
        if path.exists() and not (path / ".git").exists():
            if any(path.iterdir()):
                raise ValueError("SOURCE_PATH_NOT_EMPTY")
        if (path / ".git").exists():
            remote_url = self.git_output(path, ["remote", "get-url", "origin"])
            if remote_url and not self.same_repo_url(remote_url, spec.repo_url):
                raise ValueError("SOURCE_REMOTE_MISMATCH")
            self.run_git(path, ["fetch", "origin", "--tags", "--prune"], timeout=120)
            if ref:
                self.run_git(path, ["checkout", ref], timeout=60)
            elif force:
                self.run_git(path, ["pull", "--ff-only"], timeout=120)
        else:
            command = ["clone", "--depth", "1"]
            if ref:
                command.extend(["--branch", ref])
            command.extend([spec.repo_url, str(path)])
            self.run_git(root, command, timeout=180)
        status = self.source_repo_status(provider_id)
        state = self.load_state()
        entry = state.setdefault("kernels", {}).setdefault(provider_id, {})
        entry["source_repo"] = {
            "repo": spec.repo,
            "repo_url": spec.repo_url,
            "path": status["path"],
            "ref": status["current_ref"] or ref,
            "head": status["head"],
            "synced_at": self.utcnow(),
            "dirty": status["dirty"],
        }
        self.save_state(state)
        status["state"] = entry["source_repo"]
        return status

    def start_runtime(
        self,
        provider_id: str,
        command: list[str],
        base_url: str,
        artifact_path: str = "",
        expected_sha256: str = "",
        cwd: str = "",
        env: dict[str, str] | None = None,
        version: str = "",
        notes: str = "",
        replace_existing: bool = False,
    ) -> dict[str, Any]:
        self.require_spec(provider_id)
        if not command or not all(isinstance(item, str) and item.strip() for item in command):
            raise ValueError("COMMAND_REQUIRED")
        url = (base_url or "").strip().rstrip("/")
        if not self.is_loopback_url(url):
            raise ValueError("LOOPBACK_RUNTIME_REQUIRED")
        current = self.process_status(provider_id)
        if current.get("running") and not replace_existing:
            raise ValueError("KERNEL_PROCESS_ALREADY_RUNNING")
        if current.get("running"):
            self.stop_runtime(provider_id, grace_seconds=5)

        artifact = self.resolve_start_artifact(provider_id, artifact_path, expected_sha256, command)
        workdir = self.resolve_cwd(provider_id, cwd, artifact)
        log_dir = self.root / provider_id / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        stdout_path = log_dir / f"{stamp}-stdout.log"
        stderr_path = log_dir / f"{stamp}-stderr.log"
        child_env = dict(os.environ)
        for key, value in (env or {}).items():
            if isinstance(key, str) and key:
                child_env[key] = str(value)
        with stdout_path.open("ab") as stdout_file, stderr_path.open("ab") as stderr_file:
            popen_kwargs: dict[str, Any] = {}
            if os.name == "nt":
                popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
            process = subprocess.Popen(
                command,
                cwd=str(workdir),
                env=child_env,
                stdout=stdout_file,
                stderr=stderr_file,
                stdin=subprocess.DEVNULL,
                shell=False,
                **popen_kwargs,
            )
        time.sleep(0.2)
        running = self.pid_running(process.pid)
        state = self.load_state()
        entry = state.setdefault("kernels", {}).setdefault(provider_id, {})
        entry["runtime"] = {
            "base_url": url,
            "version": version,
            "binary_path": str(artifact["path"]),
            "sha256": artifact["sha256"],
            "notes": notes,
            "registered_at": self.utcnow(),
            "loopback_only": True,
        }
        entry["process"] = {
            "pid": process.pid,
            "command": command,
            "cwd": str(workdir),
            "artifact_path": str(artifact["path"]),
            "artifact_sha256": artifact["sha256"],
            "expected_sha256": artifact["expected_sha256"],
            "stdout_log": str(stdout_path),
            "stderr_log": str(stderr_path),
            "env_keys": sorted((env or {}).keys()),
            "started_at": self.utcnow(),
            "running": running,
        }
        self.save_state(state)
        return {
            "object": "media2api.proxy_kernel.process",
            "provider_id": provider_id,
            "process": self.process_status(provider_id),
            "runtime": entry["runtime"],
        }

    def stop_runtime(self, provider_id: str, grace_seconds: float = 5) -> dict[str, Any]:
        self.require_spec(provider_id)
        state = self.load_state()
        entry = state.setdefault("kernels", {}).setdefault(provider_id, {})
        process = entry.get("process") if isinstance(entry.get("process"), dict) else {}
        pid = int(process.get("pid") or 0)
        stopped = False
        if pid and self.pid_running(pid):
            self.terminate_pid(pid, force=False)
            deadline = time.time() + max(float(grace_seconds), 0)
            while time.time() < deadline and self.pid_running(pid):
                time.sleep(0.1)
            if self.pid_running(pid):
                self.terminate_pid(pid, force=True)
            stopped = not self.pid_running(pid)
        if process:
            process["running"] = self.pid_running(pid) if pid else False
            process["stopped_at"] = self.utcnow()
            entry["process"] = process
        self.save_state(state)
        return {"object": "media2api.proxy_kernel.process", "provider_id": provider_id, "stopped": stopped, "process": self.process_status(provider_id)}

    def process_status(self, provider_id: str) -> dict[str, Any]:
        state = self.load_state()
        process = state.get("kernels", {}).get(provider_id, {}).get("process", {})
        if not isinstance(process, dict) or not process:
            return {"pid": None, "running": False}
        pid = int(process.get("pid") or 0)
        result = dict(process)
        result["running"] = self.pid_running(pid) if pid else False
        return result

    def tail_logs(self, provider_id: str, stream: str = "stderr", max_bytes: int = 12000) -> dict[str, Any]:
        self.require_spec(provider_id)
        process = self.process_status(provider_id)
        key = "stdout_log" if stream == "stdout" else "stderr_log"
        path_text = str(process.get(key) or "")
        content = ""
        path = Path(path_text) if path_text else None
        if path and path.exists() and path.is_file():
            size = path.stat().st_size
            with path.open("rb") as fh:
                fh.seek(max(size - max_bytes, 0))
                content = fh.read(max_bytes).decode("utf-8", errors="replace")
        return {"object": "media2api.proxy_kernel.logs", "provider_id": provider_id, "stream": stream, "path": str(path) if path else "", "content": content}

    def resolve_start_artifact(self, provider_id: str, artifact_path: str, expected_sha256: str, command: list[str]) -> dict[str, Any]:
        state = self.load_state()
        installed = state.get("kernels", {}).get(provider_id, {}).get("install", {})
        path_text = artifact_path or str(installed.get("path") or "")
        if not path_text:
            raise ValueError("ARTIFACT_PATH_REQUIRED")
        path = Path(path_text).expanduser().resolve()
        root = self.root.resolve()
        if not self.path_within(path, root):
            raise ValueError("ARTIFACT_OUTSIDE_PROXY_KERNEL_DIR")
        if not path.exists() or not path.is_file():
            raise ValueError("ARTIFACT_NOT_FOUND")
        expected = self.normalize_sha256(expected_sha256) or self.normalize_sha256(str(installed.get("expected_sha256") or ""))
        if not expected:
            raise ValueError("EXPECTED_SHA256_REQUIRED")
        actual = self.file_sha256(path)
        if actual != expected:
            raise ValueError("SHA256_MISMATCH")
        if not self.command_references_path(command, path):
            raise ValueError("ARTIFACT_PATH_NOT_IN_COMMAND")
        return {"path": path, "expected_sha256": expected, "sha256": actual}

    def resolve_cwd(self, provider_id: str, cwd: str, artifact: dict[str, Any]) -> Path:
        if not cwd:
            return Path(artifact["path"]).parent
        path = Path(cwd).expanduser().resolve()
        if not self.path_within(path, self.root.resolve() / provider_id):
            raise ValueError("CWD_OUTSIDE_PROVIDER_KERNEL_DIR")
        if not path.exists() or not path.is_dir():
            raise ValueError("CWD_NOT_FOUND")
        return path

    def command_references_path(self, command: list[str], path: Path) -> bool:
        target = path.resolve()
        for item in command:
            try:
                candidate = Path(item).expanduser().resolve()
            except Exception:
                continue
            if candidate == target:
                return True
        return False

    def path_within(self, path: Path, root: Path) -> bool:
        try:
            path.resolve().relative_to(root.resolve())
            return True
        except ValueError:
            return False

    def pid_running(self, pid: int) -> bool:
        if not pid:
            return False
        if os.name == "nt":
            try:
                result = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    check=False,
                )
                return f'"{pid}"' in result.stdout or f",{pid}," in result.stdout
            except Exception:
                return False
        try:
            os.kill(pid, 0)
            if os.name == "posix":
                stat_path = Path(f"/proc/{pid}/stat")
                if stat_path.exists():
                    text = stat_path.read_text(encoding="utf-8", errors="ignore")
                    state = text.rsplit(")", 1)[1].strip().split()[0] if ")" in text else ""
                    if state == "Z":
                        return False
            return True
        except OSError:
            return False

    def terminate_pid(self, pid: int, force: bool = False) -> None:
        if not pid:
            return
        try:
            if os.name == "nt":
                command = ["taskkill", "/PID", str(pid), "/F"]
                subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
                return
            os.kill(pid, signal.SIGKILL if force and hasattr(signal, "SIGKILL") else signal.SIGTERM)
        except Exception:
            return

    def source_repo_path(self, spec: ProxyKernelSpec) -> Path:
        owner, repo = spec.repo.split("/", 1)
        slug = re.sub(r"[^A-Za-z0-9._-]+", "-", f"{owner}__{repo}").strip("-")
        return (self.source_root / slug).resolve()

    def run_git(self, cwd: Path, args: list[str], timeout: int = 120) -> str:
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=str(cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                shell=False,
                timeout=timeout,
                check=False,
            )
        except FileNotFoundError as exc:
            raise ValueError("GIT_NOT_AVAILABLE") from exc
        except subprocess.TimeoutExpired as exc:
            raise ValueError("GIT_COMMAND_TIMEOUT") from exc
        if result.returncode != 0:
            message = (result.stderr or result.stdout or "").strip()[:800]
            raise ValueError(f"GIT_COMMAND_FAILED: {message}")
        return result.stdout.strip()

    def git_output(self, cwd: Path, args: list[str]) -> str:
        try:
            return self.run_git(cwd, args, timeout=30).strip()
        except ValueError:
            return ""

    def same_repo_url(self, actual: str, expected: str) -> bool:
        def normalize(value: str) -> str:
            text = value.strip()
            if text.startswith("git@github.com:"):
                text = "https://github.com/" + text.split(":", 1)[1]
            text = text.removesuffix(".git").rstrip("/")
            return text.lower()

        return normalize(actual) == normalize(expected)

    def release_archive_kind(self, path: Path) -> str:
        lower = path.name.lower()
        if lower.endswith((".tar.gz", ".tgz", ".tar", ".tar.xz", ".txz", ".tar.bz2", ".tbz2")):
            return "tar"
        if lower.endswith(".zip"):
            return "zip"
        return ""

    def extract_release_asset(self, provider_id: str, archive_path: Path, install_dir: Path) -> dict[str, Any]:
        kind = self.release_archive_kind(archive_path)
        if not kind:
            return {
                "archive_extracted": False,
                "archive_kind": "",
                "extracted_dir": "",
                "extracted_file_count": 0,
                "executable_candidates": self.executable_candidate_payloads([archive_path], archive_path.parent, provider_id),
            }
        digest = self.file_sha256(archive_path)[:12]
        extract_dir = install_dir / f"{self.safe_filename(archive_path.name)}.extracted-{digest}"
        root = self.root.resolve()
        resolved_extract_dir = extract_dir.resolve()
        if not self.path_within(resolved_extract_dir, root):
            raise ValueError("EXTRACT_DIR_OUTSIDE_PROXY_KERNEL_DIR")
        max_files = 2000
        max_bytes = 512 * 1024 * 1024
        extracted_files: list[Path] = []
        if resolved_extract_dir.exists():
            extracted_files = [item for item in resolved_extract_dir.rglob("*") if item.is_file()]
        else:
            resolved_extract_dir.mkdir(parents=True, exist_ok=True)
            if kind == "zip":
                extracted_files = self.extract_zip_release(archive_path, resolved_extract_dir, max_files=max_files, max_bytes=max_bytes)
            else:
                extracted_files = self.extract_tar_release(archive_path, resolved_extract_dir, max_files=max_files, max_bytes=max_bytes)
        candidates = self.executable_candidate_payloads(extracted_files, resolved_extract_dir, provider_id)
        return {
            "archive_extracted": True,
            "archive_kind": kind,
            "extracted_dir": str(resolved_extract_dir),
            "extracted_file_count": len(extracted_files),
            "extracted_files_sample": [
                str(path.relative_to(resolved_extract_dir)).replace("\\", "/")
                for path in extracted_files[:50]
                if self.path_within(path.resolve(), resolved_extract_dir)
            ],
            "executable_candidates": candidates,
            "limits": {"max_files": max_files, "max_bytes": max_bytes},
        }

    def extract_zip_release(self, archive_path: Path, extract_dir: Path, *, max_files: int, max_bytes: int) -> list[Path]:
        extracted: list[Path] = []
        total_bytes = 0
        with zipfile.ZipFile(archive_path) as archive:
            for info in archive.infolist():
                target = self.safe_extract_member_path(extract_dir, info.filename)
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                total_bytes += int(info.file_size or 0)
                if len(extracted) >= max_files or total_bytes > max_bytes:
                    raise ValueError("ARCHIVE_EXTRACTION_LIMIT_EXCEEDED")
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info, "r") as source, target.open("wb") as output:
                    self.copy_limited(source, output, max_bytes=max_bytes)
                mode = (info.external_attr >> 16) & 0o777
                if mode:
                    try:
                        target.chmod(mode)
                    except OSError:
                        pass
                extracted.append(target)
        return extracted

    def extract_tar_release(self, archive_path: Path, extract_dir: Path, *, max_files: int, max_bytes: int) -> list[Path]:
        extracted: list[Path] = []
        total_bytes = 0
        with tarfile.open(archive_path, "r:*") as archive:
            for member in archive.getmembers():
                target = self.safe_extract_member_path(extract_dir, member.name)
                if member.issym() or member.islnk():
                    raise ValueError("ARCHIVE_LINK_MEMBER_FORBIDDEN")
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                if not member.isfile():
                    continue
                total_bytes += int(member.size or 0)
                if len(extracted) >= max_files or total_bytes > max_bytes:
                    raise ValueError("ARCHIVE_EXTRACTION_LIMIT_EXCEEDED")
                source = archive.extractfile(member)
                if source is None:
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with source, target.open("wb") as output:
                    self.copy_limited(source, output, max_bytes=max_bytes)
                try:
                    target.chmod(member.mode & 0o777)
                except OSError:
                    pass
                extracted.append(target)
        return extracted

    def safe_extract_member_path(self, extract_dir: Path, member_name: str) -> Path:
        name = str(member_name or "").replace("\\", "/").lstrip("/")
        if not name or name in {".", ".."} or "\x00" in name:
            raise ValueError("INVALID_ARCHIVE_MEMBER")
        target = (extract_dir / name).resolve()
        if not self.path_within(target, extract_dir.resolve()):
            raise ValueError("ARCHIVE_MEMBER_OUTSIDE_EXTRACT_DIR")
        return target

    def copy_limited(self, source: Any, output: Any, *, max_bytes: int) -> None:
        written = 0
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            written += len(chunk)
            if written > max_bytes:
                raise ValueError("ARCHIVE_MEMBER_TOO_LARGE")
            output.write(chunk)

    def executable_candidate_payloads(self, files: list[Path], root: Path, provider_id: str = "") -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        for path in files:
            if not path.exists() or not path.is_file():
                continue
            lower = path.name.lower()
            if any(token in lower for token in ("sha256", "checksum", "license", "readme", "notice", "changelog")):
                continue
            if lower.endswith((".txt", ".md", ".json", ".yaml", ".yml", ".toml", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".html", ".css")):
                continue
            try:
                mode = path.stat().st_mode
                size = path.stat().st_size
            except OSError:
                continue
            executable_bit = bool(mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))
            executable_ext = lower.endswith((".exe", ".bin", ".sh", ".cmd", ".bat"))
            extensionless = "." not in path.name
            if not (executable_bit or executable_ext or extensionless):
                continue
            relative = str(path.relative_to(root)).replace("\\", "/") if self.path_within(path.resolve(), root.resolve()) else path.name
            score = 0
            if executable_bit:
                score += 5
            if executable_ext:
                score += 3
            if extensionless:
                score += 2
            if any(token in lower for token in ("server", "proxy", "api", "runner", "main", provider_id.replace("_", "-"), provider_id.replace("_", ""))):
                score += 2
            candidates.append({
                "path": str(path.resolve()),
                "relative_path": relative,
                "size_bytes": size,
                "sha256": self.file_sha256(path),
                "mode": oct(mode & 0o777),
                "candidate_score": score,
            })
        candidates.sort(key=lambda item: int(item.get("candidate_score") or 0), reverse=True)
        return candidates[:20]

    def record_install(
        self,
        provider_id: str,
        release: dict[str, Any],
        asset: dict[str, Any],
        target: Path,
        expected_sha256: str,
        actual_sha256: str,
        reused: bool,
        extraction: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        extraction = extraction or {}
        state = self.load_state()
        entry = state.setdefault("kernels", {}).setdefault(provider_id, {})
        entry["install"] = {
            "selection_id": KERNEL_SPECS[provider_id].selection_id,
            "repo": KERNEL_SPECS[provider_id].repo,
            "tag_name": release.get("tag_name"),
            "asset_name": asset.get("name"),
            "asset_url": asset.get("browser_download_url"),
            "path": str(target),
            "expected_sha256": expected_sha256,
            "sha256": actual_sha256,
            "size_bytes": target.stat().st_size if target.exists() else None,
            "installed_at": self.utcnow(),
            "reused_existing_file": reused,
            "archive_extracted": bool(extraction.get("archive_extracted")),
            "extracted_dir": extraction.get("extracted_dir") or "",
            "extracted_file_count": int(extraction.get("extracted_file_count") or 0),
            "executable_candidates": extraction.get("executable_candidates") or [],
            "extraction": extraction,
        }
        self.save_state(state)
        return {"object": "media2api.proxy_kernel.install", "provider_id": provider_id, "install": entry["install"]}

    def require_spec(self, provider_id: str) -> ProxyKernelSpec:
        spec = KERNEL_SPECS.get(provider_id)
        if not spec:
            raise KeyError(provider_id)
        return spec

    def github_json(self, url: str) -> Any:
        request = urllib.request.Request(url, headers=self.github_headers())
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return {"error": "GITHUB_HTTP_ERROR", "status_code": exc.code, "message": exc.read().decode("utf-8", errors="replace")[:500]}
        except Exception as exc:
            return {"error": "GITHUB_REQUEST_FAILED", "message": str(exc)}

    def github_headers(self) -> dict[str, str]:
        return {"Accept": "application/vnd.github+json", "User-Agent": "media2api-proxy-kernel-runtime"}

    def asset_payload(self, asset: dict[str, Any]) -> dict[str, Any]:
        name = str(asset.get("name") or "")
        score = self.asset_candidate_score(name)
        return {
            "name": name,
            "size": asset.get("size"),
            "content_type": asset.get("content_type"),
            "browser_download_url": asset.get("browser_download_url"),
            "created_at": asset.get("created_at"),
            "updated_at": asset.get("updated_at"),
            "candidate_score": score,
            "candidate_reason": self.asset_candidate_reason(name, score),
        }

    def asset_candidate_score(self, name: str) -> int:
        lower = name.lower()
        score = 0
        if any(token in lower for token in ["linux", "ubuntu", "debian"]):
            score += 4
        if any(token in lower for token in ["amd64", "x86_64", "x64"]):
            score += 3
        if any(lower.endswith(ext) for ext in [".tar.gz", ".tgz", ".zip", ".gz", ".bin", ".exe"]):
            score += 1
        if any(token in lower for token in ["sha256", "checksum", "checksums"]):
            score -= 5
        return score

    def asset_candidate_reason(self, name: str, score: int) -> str:
        if score <= 0:
            return "not a preferred linux/amd64 runtime asset"
        return "possible linux/amd64 release asset; verify manually and provide expected SHA256"

    def pick_asset(self, assets: list[dict[str, Any]], asset_name: str | None) -> dict[str, Any] | None:
        if asset_name:
            for asset in assets:
                if asset.get("name") == asset_name:
                    return asset
            return None
        candidates = sorted(assets, key=lambda item: int(item.get("candidate_score") or 0), reverse=True)
        return candidates[0] if candidates and int(candidates[0].get("candidate_score") or 0) > 0 else None

    def safe_filename(self, value: str) -> str:
        name = re.sub(r"[^A-Za-z0-9._+-]+", "_", value).strip("._")
        return name or "release-asset"

    def file_sha256(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def normalize_sha256(self, value: str | None) -> str:
        raw = (value or "").strip().lower()
        return raw if re.fullmatch(r"[0-9a-f]{64}", raw) else ""

    def is_loopback_url(self, value: str) -> bool:
        if not value:
            return False
        parsed = urlparse(value)
        host = (parsed.hostname or "").lower()
        return parsed.scheme in {"http", "https"} and host in {"127.0.0.1", "localhost", "::1"}

    def utcnow(self) -> str:
        return datetime.utcnow().isoformat() + "Z"
