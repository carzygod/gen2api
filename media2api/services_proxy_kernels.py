from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
from typing import Any
import urllib.error
import urllib.request
from urllib.parse import urlparse

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
        return payload

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
        blockers: list[dict[str, Any]] = []
        if not provider:
            blockers.append({"code": "PROVIDER_NOT_INITIALIZED", "message": "Import a real account or register the provider template first."})
        if not active_accounts:
            blockers.append({"code": "NO_ACTIVE_ACCOUNT", "message": "Import an authorized Web session or Agent Provider profile for this provider."})
        if not runtime_registered:
            blockers.append({"code": "NO_LOOPBACK_RUNTIME", "message": "Register a verified loopback runtime or complete a native adapter rewrite."})
        if installed and not installed_verified:
            blockers.append({"code": "KERNEL_HASH_NOT_VERIFIED", "message": "Installed artifact hash does not match the expected SHA256."})
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
            "state": state,
            "usable": bool(provider and active_accounts and runtime_registered and (not installed or installed_verified)),
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
                "needs_account": sum(1 for item in data if any(blocker["code"] == "NO_ACTIVE_ACCOUNT" for blocker in item["blockers"])),
                "needs_runtime": sum(1 for item in data if any(blocker["code"] == "NO_LOOPBACK_RUNTIME" for blocker in item["blockers"])),
                "needs_hash": sum(1 for item in data if any(blocker["code"] == "KERNEL_HASH_NOT_VERIFIED" for blocker in item["blockers"])),
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
                return self.record_install(provider_id, release, asset, target, expected, current_sha, reused=True)
            raise ValueError("TARGET_EXISTS_WITH_DIFFERENT_HASH")
        request = urllib.request.Request(asset["browser_download_url"], headers=self.github_headers())
        with urllib.request.urlopen(request, timeout=120) as response:
            target.write_bytes(response.read())
        actual = self.file_sha256(target)
        if actual != expected:
            target.unlink(missing_ok=True)
            raise ValueError("SHA256_MISMATCH")
        return self.record_install(provider_id, release, asset, target, expected, actual, reused=False)

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
        entry.pop("runtime", None)
        self.save_state(state)
        return {"object": "media2api.proxy_kernel.runtime", "provider_id": provider_id, "runtime": {}}

    def record_install(
        self,
        provider_id: str,
        release: dict[str, Any],
        asset: dict[str, Any],
        target: Path,
        expected_sha256: str,
        actual_sha256: str,
        reused: bool,
    ) -> dict[str, Any]:
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
