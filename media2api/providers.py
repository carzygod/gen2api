from __future__ import annotations

import subprocess
import tempfile
import base64
import hashlib
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote

import httpx
from PIL import Image, ImageDraw, ImageFont
from sqlalchemy.orm import Session

from . import models
from .services_secrets import SecretService
from .services_assets import AssetService
from .utils import dumps, loads, new_id, redact_sensitive


TINY_MP4_BASE64 = (
    "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"
)
ASSET_PAYLOAD_FIELDS = ["image", "images", "assets", "first_frame", "last_frame", "mask", "video", "videos"]
DEFAULT_TASK_ID_PATHS = ["id", "job_id", "task_id", "task.id", "task.uid", "result.id", "result.task_id"]
DEFAULT_STATUS_PATHS = ["status", "state", "task_status", "task.status", "task.state", "result.status", "result.state", "output.status", "output.state"]
DEFAULT_OUTPUT_PATHS = [
    "data",
    "outputs",
    "assets",
    "images",
    "videos",
    "result.data",
    "result.outputs",
    "result.assets",
    "result.images",
    "result.videos",
    "result.urls",
    "result.url",
    "result.media_url",
    "result.image_url",
    "result.video_url",
    "output.data",
    "output.outputs",
    "output.assets",
    "output.images",
    "output.videos",
    "output.urls",
    "output.url",
    "output.media_url",
    "output.image_url",
    "output.video_url",
    "url",
    "download_url",
    "content_url",
    "media_url",
    "image_url",
    "video_url",
    "b64_json",
    "base64",
    "image_base64",
    "video_base64",
]
MEDIA_ITEM_KEYS = {
    "b64_json",
    "base64",
    "image_base64",
    "video_base64",
    "url",
    "download_url",
    "content_url",
    "media_url",
    "image_url",
    "video_url",
    "asset_id",
}


@dataclass
class ProviderContext:
    provider_id: str
    provider_model: str
    account: models.AccountResource
    user_id: str


@dataclass
class ProviderSubmitResult:
    provider_task_id: str
    status: str
    assets: list[models.MediaAsset]
    raw_status: str = "completed"
    raw_response: dict[str, Any] | None = None


class MediaProviderAdapter(Protocol):
    provider_id: str

    def capabilities(self) -> dict[str, Any]:
        ...

    def submit(self, db: Session, ctx: ProviderContext, job: models.MediaJob) -> ProviderSubmitResult:
        ...

    def health_check(self, db: Session, provider_id: str) -> dict[str, Any]:
        ...

    def cancel(self, db: Session, ctx: ProviderContext, provider_task_id: str) -> dict[str, Any]:
        ...

    def query_account_quota(self, db: Session, ctx: ProviderContext) -> dict[str, Any]:
        ...

    def classify_error(self, error: Exception) -> dict[str, Any]:
        ...


class MockProvider:
    provider_id = "mock"

    def capabilities(self) -> dict[str, Any]:
        return {
            "operations": ["text_to_image", "image_to_image", "image_edit", "text_to_video", "image_to_video", "video_extend"],
            "models": [
                "mock-image-fast",
                "mock-image-pro",
                "mock-image-edit",
                "mock-image-variation",
                "mock-video-fast",
                "mock-video-pro",
                "mock-video-general",
                "mock-video-extend",
            ],
        }

    def submit(self, db: Session, ctx: ProviderContext, job: models.MediaJob) -> ProviderSubmitResult:
        params = loads(job.normalized_params_json, {})
        fail_models = params.get("_mock_fail_provider_models") or params.get("mock_fail_provider_models") or []
        if isinstance(fail_models, str):
            fail_models = [item.strip() for item in fail_models.split(",") if item.strip()]
        if ctx.provider_model in set(fail_models):
            raise RuntimeError(f"MOCK_FORCED_FAILURE:{ctx.provider_model}")
        timeout_models = params.get("_mock_timeout_provider_models") or params.get("mock_timeout_provider_models") or []
        if isinstance(timeout_models, str):
            timeout_models = [item.strip() for item in timeout_models.split(",") if item.strip()]
        if ctx.provider_model in set(timeout_models):
            raise TimeoutError(f"MOCK_FORCED_TIMEOUT:{ctx.provider_model}")
        asset_service = AssetService()
        if job.operation in {"text_to_image", "image_to_image", "image_edit"}:
            asset = self._make_image(db, asset_service, ctx, job)
        else:
            asset = self._make_video(db, asset_service, ctx, job)
        return ProviderSubmitResult(
            provider_task_id=f"mocktask_{job.id}",
            status="completed",
            assets=[asset],
            raw_response={"status": "completed", "provider": ctx.provider_id, "provider_model": ctx.provider_model, "asset_ids": [asset.id]},
        )

    def classify_error(self, error: Exception) -> dict[str, Any]:
        message = str(error)
        if isinstance(error, TimeoutError) or "MOCK_FORCED_TIMEOUT" in message or "timeout" in message.lower() or "timed out" in message.lower():
            return {"code": "PROVIDER_TIMEOUT", "message": message, "retryable": True}
        return {"code": "PROVIDER_FAILED", "message": str(error), "retryable": True}

    def cancel(self, db: Session, ctx: ProviderContext, provider_task_id: str) -> dict[str, Any]:
        return {"status": "not_supported", "message": "mock provider completes synchronously; no upstream cancellation needed", "provider_task_id": provider_task_id}

    def health_check(self, db: Session, provider_id: str) -> dict[str, Any]:
        return {"status": "ok", "latency_ms": 0, "message": "mock provider ready", "detail": self.capabilities()}

    def query_account_quota(self, db: Session, ctx: ProviderContext) -> dict[str, Any]:
        return {
            "status": "ok",
            "message": "mock account quota is virtual",
            "quota_buckets": [
                {
                    "type": "credits",
                    "remaining_estimate": 999999,
                    "confidence": 1.0,
                    "source": "mock",
                }
            ],
            "detail": {"provider": ctx.provider_id, "account_id": ctx.account.id},
        }

    def _make_image(self, db: Session, asset_service: AssetService, ctx: ProviderContext, job: models.MediaJob) -> models.MediaAsset:
        width, height = 1024, 1024
        image = Image.new("RGB", (width, height), color=(24, 27, 31))
        draw = ImageDraw.Draw(image)
        title = job.logical_model
        lines = [
            "media2api mock image",
            f"job: {job.id}",
            f"model: {ctx.provider_model}",
            f"operation: {job.operation}",
        ]
        try:
            font = ImageFont.truetype("arial.ttf", 32)
            small = ImageFont.truetype("arial.ttf", 22)
        except Exception:
            font = ImageFont.load_default()
            small = ImageFont.load_default()
        draw.rectangle((48, 48, width - 48, height - 48), outline=(84, 185, 129), width=4)
        draw.text((72, 90), title, fill=(255, 255, 255), font=font)
        y = 180
        for line in lines:
            draw.text((72, y), line, fill=(198, 206, 217), font=small)
            y += 42
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            path = Path(tmp.name)
        image.save(path, format="PNG")
        try:
            return asset_service.create_from_file(
                db=db,
                user_id=job.user_id,
                file_path=path,
                kind="image",
                purpose="output",
                mime_type="image/png",
                source="provider_result",
                provider_meta={"provider": ctx.provider_id, "provider_model": ctx.provider_model},
            )
        finally:
            path.unlink(missing_ok=True)

    def _make_video(self, db: Session, asset_service: AssetService, ctx: ProviderContext, job: models.MediaJob) -> models.MediaAsset:
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            path = Path(tmp.name)
        cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=0x181b1f:s=1280x720:r=24",
            "-t",
            "3",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ]
        try:
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            duration_ms = 3000
            width, height = 1280, 720
        except Exception:
            path.write_bytes(base64.b64decode(TINY_MP4_BASE64))
            duration_ms = 1000
            width, height = 160, 90
        try:
            return asset_service.create_from_file(
                db=db,
                user_id=job.user_id,
                file_path=path,
                kind="video",
                purpose="output",
                mime_type="video/mp4",
                source="provider_result",
                provider_meta={"provider": ctx.provider_id, "provider_model": ctx.provider_model},
                duration_ms=duration_ms,
                width=width,
                height=height,
            )
        finally:
            path.unlink(missing_ok=True)


class DisabledProvider:
    def __init__(self, provider_id: str):
        self.provider_id = provider_id

    def capabilities(self) -> dict[str, Any]:
        return {"operations": [], "models": [], "disabled": True}

    def submit(self, db: Session, ctx: ProviderContext, job: models.MediaJob) -> ProviderSubmitResult:
        raise RuntimeError(f"Provider {self.provider_id} is configured but disabled.")

    def classify_error(self, error: Exception) -> dict[str, Any]:
        return {"code": "PROVIDER_DISABLED", "message": str(error), "retryable": False}

    def cancel(self, db: Session, ctx: ProviderContext, provider_task_id: str) -> dict[str, Any]:
        return {"status": "not_supported", "message": f"Provider {self.provider_id} is disabled", "provider_task_id": provider_task_id}

    def health_check(self, db: Session, provider_id: str) -> dict[str, Any]:
        return {"status": "disabled", "latency_ms": None, "message": f"Provider {provider_id} is disabled", "detail": {}}

    def query_account_quota(self, db: Session, ctx: ProviderContext) -> dict[str, Any]:
        return {"status": "not_supported", "message": f"Provider {ctx.provider_id} is disabled", "quota_buckets": [], "detail": {}}


class PollinationsProvider:
    provider_id = "pollinations"

    image_models = [
        "kontext",
        "nanobanana",
        "nanobanana-2",
        "nanobanana-pro",
        "seedream5",
        "seedream",
        "seedream-pro",
        "gptimage",
        "gptimage-large",
        "gpt-image-2",
        "flux",
        "zimage",
        "wan-image",
        "wan-image-pro",
        "qwen-image",
        "grok-imagine",
        "grok-imagine-pro",
    ]
    video_models = [
        "veo",
        "seedance",
        "seedance-pro",
        "seedance-2.0",
        "wan",
        "wan-fast",
        "wan-pro",
        "grok-video-pro",
        "ltx-2",
        "p-video",
        "nova-reel",
    ]

    def capabilities(self) -> dict[str, Any]:
        return {
            "operations": ["text_to_image", "image_to_image", "image_edit", "text_to_video", "image_to_video"],
            "models": [*self.image_models, *self.video_models],
            "mode": "direct_aggregator",
            "requires_credential": True,
            "supports_public_access": False,
        }

    def submit(self, db: Session, ctx: ProviderContext, job: models.MediaJob) -> ProviderSubmitResult:
        provider = db.get(models.Provider, ctx.provider_id)
        config = loads(provider.base_config_json if provider else "{}", {})
        base_url = str(config.get("base_url") or "https://gen.pollinations.ai").rstrip("/")
        headers = self._headers(db, config, ctx.account.credential_ref)
        if headers is None:
            raise RuntimeError("POLLINATIONS_KEY_MISSING")

        params = loads(job.normalized_params_json, {})
        prompt = str(params.get("prompt") or "media generation").strip() or "media generation"
        timeout = float(config.get("timeout_seconds") or (300 if job.operation in {"text_to_video", "image_to_video"} else 120))

        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            reference_urls = self._upload_references(db, client, base_url, headers, job, config)
            query = self._query_params(params, ctx.provider_model, job.operation, reference_urls, config)
            endpoint_kind = "video" if job.operation in {"text_to_video", "image_to_video", "video_extend"} else "image"
            url = f"{base_url}/{endpoint_kind}/{quote(prompt, safe='')}"
            response = client.get(url, params=query, headers=headers)
            if response.status_code >= 400:
                raise RuntimeError(f"pollinations status {response.status_code}: {response.text[:500]}")
            mime_type = response.headers.get("content-type", "").split(";", 1)[0] or ("video/mp4" if endpoint_kind == "video" else "image/jpeg")
            if endpoint_kind == "video" and not mime_type.startswith("video/"):
                raise RuntimeError(f"pollinations video response MIME invalid: {mime_type}")
            if endpoint_kind == "image" and not mime_type.startswith("image/"):
                raise RuntimeError(f"pollinations image response MIME invalid: {mime_type}")
            asset = AssetService().create_from_bytes(
                db,
                job.user_id,
                response.content,
                f"pollinations.{self._suffix(mime_type)}",
                endpoint_kind,
                "output",
                mime_type,
                source="provider_result",
                provider_meta={
                    "provider": ctx.provider_id,
                    "provider_model": ctx.provider_model,
                    "source": "pollinations",
                    "prompt": prompt[:500],
                    "reference_count": len(reference_urls),
                },
            )
        task_id = f"pollinations_{job.id}"
        return ProviderSubmitResult(
            provider_task_id=task_id,
            status="completed",
            assets=[asset],
            raw_status="completed",
            raw_response={
                "status": "completed",
                "provider": ctx.provider_id,
                "provider_model": ctx.provider_model,
                "asset_ids": [asset.id],
                "content_type": mime_type,
                "bytes": len(response.content),
                "endpoint": endpoint_kind,
                "query": redact_sensitive(query),
            },
        )

    def classify_error(self, error: Exception) -> dict[str, Any]:
        message = str(error)
        if "POLLINATIONS_KEY_MISSING" in message or "401" in message or "403" in message:
            return {"code": "AUTH_REQUIRED", "message": "Pollinations credential is missing or invalid.", "retryable": False}
        if "402" in message or "PAYMENT" in message.upper() or "budget" in message.lower() or "quota" in message.lower():
            return {"code": "QUOTA_EXHAUSTED", "message": message, "retryable": False}
        if "429" in message:
            return {"code": "RATE_LIMITED", "message": message, "retryable": True}
        if "timeout" in message.lower() or "timed out" in message.lower():
            return {"code": "PROVIDER_TIMEOUT", "message": message, "retryable": True}
        if "MIME invalid" in message:
            return {"code": "PROVIDER_BAD_RESPONSE", "message": message, "retryable": True}
        return {"code": "PROVIDER_FAILED", "message": message, "retryable": True}

    def cancel(self, db: Session, ctx: ProviderContext, provider_task_id: str) -> dict[str, Any]:
        return {"status": "not_supported", "message": "Pollinations direct generation is synchronous from this gateway.", "provider_task_id": provider_task_id}

    def health_check(self, db: Session, provider_id: str) -> dict[str, Any]:
        provider = db.get(models.Provider, provider_id)
        config = loads(provider.base_config_json if provider else "{}", {})
        base_url = str(config.get("base_url") or "https://gen.pollinations.ai").rstrip("/")
        accounts = (
            db.query(models.AccountResource)
            .filter(models.AccountResource.provider_id == provider_id, models.AccountResource.status == "active")
            .order_by(models.AccountResource.health_score.desc(), models.AccountResource.failure_score.asc(), models.AccountResource.id.asc())
            .all()
        )
        headers = self._headers(db, config, None)
        account_id = ""
        if headers is None:
            for account in accounts:
                headers = self._headers(db, config, account.credential_ref)
                if headers is not None:
                    account_id = account.id
                    break
        if headers is None:
            return {"status": "failed", "latency_ms": None, "message": "missing Pollinations credential", "detail": {"requires": "env://POLLINATIONS_KEY or secret:// credential"}}
        started = time.time()
        try:
            response = httpx.get(f"{base_url}/v1/models", headers=headers, timeout=float(config.get("health_timeout_seconds") or 10))
            latency_ms = int((time.time() - started) * 1000)
            if response.status_code >= 400:
                return {"status": "failed", "latency_ms": latency_ms, "message": f"pollinations health status {response.status_code}", "detail": {"body": response.text[:500]}}
            data = response.json()
            model_count = len(data.get("data", [])) if isinstance(data, dict) else 0
            return {"status": "ok", "latency_ms": latency_ms, "message": "pollinations reachable", "detail": {"model_count": model_count, "base_url": base_url, "account_id": account_id}}
        except Exception as exc:
            return {"status": "failed", "latency_ms": None, "message": str(exc), "detail": {"base_url": base_url}}

    def query_account_quota(self, db: Session, ctx: ProviderContext) -> dict[str, Any]:
        provider = db.get(models.Provider, ctx.provider_id)
        config = loads(provider.base_config_json if provider else "{}", {})
        headers = self._headers(db, config, ctx.account.credential_ref)
        if headers is None:
            raise RuntimeError("POLLINATIONS_KEY_MISSING")
        return {
            "status": "ok",
            "message": "Pollinations quota is account-managed upstream; exact balance is not exposed by this adapter.",
            "quota_buckets": [
                {
                    "type": "public_endpoint" if not headers else "external_account",
                    "remaining_estimate": None,
                    "confidence": 0.1 if not headers else 0.2,
                    "source": "pollinations",
                    "operations": self.capabilities()["operations"],
                    "provider_models": loads(ctx.account.supported_provider_models_json, []),
                }
            ],
            "detail": {"provider": ctx.provider_id, "account_id": ctx.account.id},
        }

    def _headers(self, db: Session, config: dict[str, Any], credential_ref: str | None) -> dict[str, str] | None:
        api_key = self._api_key(db, config, credential_ref)
        if not api_key:
            return None
        return {"Authorization": f"Bearer {api_key}"}

    def _public_access(self, config: dict[str, Any], credential_ref: str | None) -> bool:
        return False

    def _api_key(self, db: Session, config: dict[str, Any], credential_ref: str | None) -> str | None:
        return (
            resolve_credential(str(config.get("api_key_ref") or ""), db)
            or resolve_credential(credential_ref, db)
            or os.getenv("POLLINATIONS_KEY")
            or os.getenv("MEDIA2API_POLLINATIONS_KEY")
        )

    def _query_params(self, params: dict[str, Any], provider_model: str, operation: str, reference_urls: list[str], config: dict[str, Any]) -> dict[str, Any]:
        width, height = self._size(params)
        query: dict[str, Any] = {
            "model": provider_model,
            "width": width,
            "height": height,
            "enhance": str(bool(params.get("enhance") or config.get("enhance"))).lower(),
        }
        if params.get("seed") is not None:
            query["seed"] = int(params["seed"])
        if params.get("safe") is not None:
            query["safe"] = params["safe"]
        if operation in {"text_to_video", "image_to_video", "video_extend"}:
            if params.get("duration") is not None:
                query["duration"] = int(params["duration"])
            aspect_ratio = params.get("aspect_ratio") or params.get("aspectRatio")
            if aspect_ratio:
                query["aspectRatio"] = str(aspect_ratio)
            if params.get("audio") is not None:
                query["audio"] = str(bool(params["audio"])).lower()
        if reference_urls:
            query["image"] = "|".join(reference_urls)
        return query

    def _size(self, params: dict[str, Any]) -> tuple[int, int]:
        size = str(params.get("size") or "").lower()
        if "x" in size:
            left, right = size.split("x", 1)
            try:
                return max(64, int(left)), max(64, int(right))
            except ValueError:
                pass
        if params.get("width") and params.get("height"):
            return max(64, int(params["width"])), max(64, int(params["height"]))
        aspect = str(params.get("aspect_ratio") or params.get("aspectRatio") or "1:1")
        if aspect == "16:9":
            return 1280, 720
        if aspect == "9:16":
            return 720, 1280
        return 1024, 1024

    def _upload_references(
        self,
        db: Session,
        client: httpx.Client,
        base_url: str,
        headers: dict[str, str],
        job: models.MediaJob,
        config: dict[str, Any],
    ) -> list[str]:
        asset_ids = loads(job.input_asset_ids_json, [])
        if not asset_ids:
            return []
        result: list[str] = []
        asset_service = AssetService()
        max_refs = int(config.get("max_reference_assets") or 2)
        for asset_id in asset_ids[:max_refs]:
            asset = db.get(models.MediaAsset, asset_id)
            if not asset:
                continue
            data = asset_service.read_bytes(asset)
            filename = f"{asset.id}.{self._suffix(asset.mime_type)}"
            response = client.post(f"{base_url}/upload", headers=headers, files={"file": (filename, data, asset.mime_type)})
            if response.status_code >= 400:
                raise RuntimeError(f"pollinations upload status {response.status_code}: {response.text[:500]}")
            uploaded = response.json()
            media_url = self._extract_upload_url(uploaded)
            if not media_url:
                raise RuntimeError("pollinations upload response did not include a media URL")
            result.append(media_url)
        return result

    def _extract_upload_url(self, data: dict[str, Any]) -> str:
        for key in ["url", "media_url", "mediaUrl", "download_url", "downloadUrl", "content_url", "contentUrl"]:
            value = data.get(key)
            if isinstance(value, str) and value.startswith("http"):
                return value
        hash_value = data.get("hash") or data.get("id")
        if isinstance(hash_value, str) and hash_value:
            return f"https://media.pollinations.ai/{hash_value}"
        return ""

    def _suffix(self, mime_type: str) -> str:
        if mime_type in {"image/jpeg", "image/jpg"}:
            return "jpg"
        if mime_type == "image/webp":
            return "webp"
        if mime_type == "video/mp4":
            return "mp4"
        return "png"


def resolve_credential(ref: str | None, db: Session | None = None) -> str | None:
    if not ref:
        return None
    if ref.startswith("env://"):
        return os.getenv(ref.replace("env://", "", 1))
    if ref.startswith("secret://"):
        if db is None:
            return None
        return SecretService().resolve(db, ref.replace("secret://", "", 1))
    if ref.startswith("public://"):
        return None
    if ref.startswith("bearer://"):
        return ref.replace("bearer://", "", 1)
    if ref.startswith("plain://"):
        return ref.replace("plain://", "", 1)
    return None


class ConnectorProvider:
    """Generic adapter for already-authorized HTTP sidecars/connectors.

    This adapter intentionally assumes the upstream connector is already
    authorized and service-ready. It only handles media gateway translation,
    polling, result ingestion, and standardized error classification.
    """

    def __init__(self, provider_id: str):
        self.provider_id = provider_id

    def capabilities(self) -> dict[str, Any]:
        return {
            "operations": ["text_to_image", "image_to_image", "image_edit", "text_to_video", "image_to_video", "video_extend"],
            "mode": "connector",
        }

    def submit(self, db: Session, ctx: ProviderContext, job: models.MediaJob) -> ProviderSubmitResult:
        provider = db.get(models.Provider, ctx.provider_id)
        config = loads(provider.base_config_json if provider else "{}", {})
        base_url = str(config.get("base_url") or "").rstrip("/")
        if not base_url:
            raise RuntimeError(f"Provider {ctx.provider_id} is active but missing base_config.base_url")

        headers = self._headers(db, config, ctx.account.credential_ref)
        payload = self._payload(db, job, ctx, config)
        endpoint = self._endpoint(job.operation, config)
        timeout = float(config.get("timeout_seconds") or 120)

        with httpx.Client(timeout=timeout) as client:
            response = client.post(f"{base_url}{endpoint}", json=payload, headers=headers)
            if response.status_code >= 400:
                raise RuntimeError(f"connector status {response.status_code}: {response.text[:500]}")
            data = response.json()
            provider_task_id = self._provider_task_id(data, job, config)
            job.provider_task_id = provider_task_id
            if self._has_output_candidates(data, config):
                self._set_job_stage(
                    db,
                    job,
                    "fetching_assets",
                    "fetching_assets",
                    "Fetching connector result assets.",
                    metadata={"provider_task_id": provider_task_id, "raw_status": str(data.get("status") or "completed")},
                )
            assets = self._ingest_outputs(db, client, data, job, ctx, config)

            if not assets and provider_task_id:
                self._set_job_stage(
                    db,
                    job,
                    "provider_queued",
                    "provider_queued",
                    "Connector accepted the task for asynchronous processing.",
                    metadata={"provider_task_id": provider_task_id, "raw_status": str(data.get("status") or "queued")},
                )
                data = self._poll(db, job, client, base_url, endpoint, provider_task_id, headers, config)
                self._set_job_stage(
                    db,
                    job,
                    "fetching_assets",
                    "fetching_assets",
                    "Fetching connector result assets.",
                    metadata={"provider_task_id": provider_task_id, "raw_status": str(data.get("status") or "completed")},
                )
                assets = self._ingest_outputs(db, client, data, job, ctx, config)

            if not assets:
                raise RuntimeError("connector response did not include ingestible media outputs")
            return ProviderSubmitResult(
                provider_task_id=provider_task_id,
                status="completed",
                assets=assets,
                raw_status=str(data.get("status") or "completed"),
                raw_response=self._sanitize_connector_payload(data),
            )

    def classify_error(self, error: Exception) -> dict[str, Any]:
        message = str(error)
        if "PROVIDER_TIMEOUT" in message or "timed out" in message.lower() or "timeout" in message.lower():
            return {"code": "PROVIDER_TIMEOUT", "message": message, "retryable": True}
        if "401" in message or "403" in message:
            return {"code": "AUTH_REQUIRED", "message": message, "retryable": False}
        if "402" in message or "quota" in message.lower() or "insufficient" in message.lower():
            return {"code": "QUOTA_EXHAUSTED", "message": message, "retryable": False}
        if "429" in message:
            return {"code": "RATE_LIMITED", "message": message, "retryable": True}
        if "missing base_config" in message:
            return {"code": "PROVIDER_CONFIG_INVALID", "message": message, "retryable": False}
        return {"code": "PROVIDER_FAILED", "message": message, "retryable": True}

    def cancel(self, db: Session, ctx: ProviderContext, provider_task_id: str) -> dict[str, Any]:
        provider = db.get(models.Provider, ctx.provider_id)
        config = loads(provider.base_config_json if provider else "{}", {})
        base_url = str(config.get("base_url") or "").rstrip("/")
        cancel_endpoint = str(config.get("cancel_endpoint") or "").strip()
        if not base_url or not cancel_endpoint:
            return {
                "status": "not_supported",
                "message": "connector cancel_endpoint is not configured",
                "provider_task_id": provider_task_id,
            }
        endpoint = cancel_endpoint.replace("{provider_task_id}", provider_task_id).replace("{task_id}", provider_task_id)
        method = str(config.get("cancel_method") or "POST").upper()
        timeout = float(config.get("cancel_timeout_seconds") or config.get("timeout_seconds") or 30)
        headers = self._headers(db, config, ctx.account.credential_ref if ctx.account else None)
        payload = {"id": provider_task_id, "task_id": provider_task_id}
        if isinstance(config.get("cancel_payload"), dict):
            payload.update(config["cancel_payload"])
        started = time.time()
        with httpx.Client(timeout=timeout) as client:
            if method == "DELETE":
                response = client.delete(f"{base_url}{endpoint}", headers=headers)
            elif method == "GET":
                response = client.get(f"{base_url}{endpoint}", headers=headers)
            else:
                response = client.post(f"{base_url}{endpoint}", headers=headers, json=payload)
        latency_ms = int((time.time() - started) * 1000)
        if response.status_code >= 400:
            return {
                "status": "failed",
                "message": f"connector cancel status {response.status_code}",
                "provider_task_id": provider_task_id,
                "latency_ms": latency_ms,
                "detail": {"body": response.text[:500]},
            }
        detail: dict[str, Any]
        try:
            detail = response.json()
        except Exception:
            detail = {"body": response.text[:500]}
        return {
            "status": "cancelled",
            "message": "connector cancel requested",
            "provider_task_id": provider_task_id,
            "latency_ms": latency_ms,
            "detail": detail,
        }

    def health_check(self, db: Session, provider_id: str) -> dict[str, Any]:
        provider = db.get(models.Provider, provider_id)
        config = loads(provider.base_config_json if provider else "{}", {})
        base_url = str(config.get("base_url") or "").rstrip("/")
        if not base_url:
            return {"status": "failed", "latency_ms": None, "message": "missing base_config.base_url", "detail": {}}
        endpoint = str(config.get("health_endpoint") or "/health")
        timeout = float(config.get("health_timeout_seconds") or 10)
        account = db.query(models.AccountResource).filter(models.AccountResource.provider_id == provider_id).first()
        headers = self._headers(db, config, account.credential_ref if account else None)
        started = time.time()
        try:
            response = httpx.get(f"{base_url}{endpoint}", headers=headers, timeout=timeout)
            latency_ms = int((time.time() - started) * 1000)
            if response.status_code >= 400:
                return {
                    "status": "failed",
                    "latency_ms": latency_ms,
                    "message": f"connector health status {response.status_code}",
                    "detail": {"body": response.text[:500]},
                }
            detail: dict[str, Any]
            try:
                detail = response.json()
            except Exception:
                detail = {"body": response.text[:500]}
            return {"status": "ok", "latency_ms": latency_ms, "message": "connector reachable", "detail": detail}
        except Exception as exc:
            return {"status": "failed", "latency_ms": None, "message": str(exc), "detail": {}}

    def query_account_quota(self, db: Session, ctx: ProviderContext) -> dict[str, Any]:
        provider = db.get(models.Provider, ctx.provider_id)
        config = loads(provider.base_config_json if provider else "{}", {})
        base_url = str(config.get("base_url") or "").rstrip("/")
        endpoint = str(config.get("quota_endpoint") or "").strip()
        if not base_url or not endpoint:
            return {
                "status": "not_supported",
                "message": "connector quota_endpoint is not configured",
                "quota_buckets": [],
                "detail": {},
            }
        endpoint = endpoint.replace("{account_id}", ctx.account.id).replace("{provider_id}", ctx.provider_id)
        method = str(config.get("quota_method") or "GET").upper()
        timeout = float(config.get("quota_timeout_seconds") or config.get("health_timeout_seconds") or 10)
        headers = self._headers(db, config, ctx.account.credential_ref)
        payload = {
            "account_id": ctx.account.id,
            "provider_id": ctx.provider_id,
            "supported_operations": loads(ctx.account.supported_operations_json, []),
            "supported_provider_models": loads(ctx.account.supported_provider_models_json, []),
        }
        started = time.time()
        with httpx.Client(timeout=timeout) as client:
            if method == "POST":
                response = client.post(f"{base_url}{endpoint}", headers=headers, json=payload)
            else:
                response = client.get(f"{base_url}{endpoint}", headers=headers)
        latency_ms = int((time.time() - started) * 1000)
        if response.status_code >= 400:
            raise RuntimeError(f"connector quota status {response.status_code}: {response.text[:500]}")
        data = response.json()
        buckets = self._normalize_quota_buckets(data)
        if not buckets:
            raise RuntimeError("connector quota response did not include quota buckets")
        return {
            "status": str(data.get("status") or "ok"),
            "message": str(data.get("message") or "connector quota synced"),
            "quota_buckets": buckets,
            "latency_ms": latency_ms,
            "detail": redact_sensitive({k: v for k, v in data.items() if k not in {"quota_buckets", "quotas", "buckets"}}),
        }

    def _headers(self, db: Session, config: dict[str, Any], credential_ref: str | None) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        api_key = resolve_credential(str(config.get("api_key_ref") or ""), db) or resolve_credential(credential_ref, db)
        if api_key:
            header_name = str(config.get("api_key_header") or "Authorization")
            if header_name.lower() == "authorization":
                headers[header_name] = f"Bearer {api_key}"
            else:
                headers[header_name] = api_key
        return headers

    def _payload(self, db: Session, job: models.MediaJob, ctx: ProviderContext, config: dict[str, Any]) -> dict[str, Any]:
        payload = loads(job.normalized_params_json, {})
        payload["model"] = ctx.provider_model
        asset_urls = []
        asset_service = AssetService()
        asset_base_url = str(config.get("asset_base_url") or "").rstrip("/")
        asset_url_by_id: dict[str, str] = {}
        for asset_id in loads(job.input_asset_ids_json, []):
            asset = db.get(models.MediaAsset, asset_id)
            if not asset:
                continue
            url = asset_service.public_url(asset)
            if asset_base_url:
                parts = url.split("/v1/assets/", 1)
                url = f"{asset_base_url}/v1/assets/{parts[1]}" if len(parts) == 2 else url
            asset_url_by_id[asset_id] = url
            asset_urls.append(url)
        for field in ASSET_PAYLOAD_FIELDS:
            if field in payload:
                payload[field] = self._replace_asset_ids_with_urls(payload[field], asset_url_by_id)
        if asset_urls:
            payload["image"] = asset_urls[0] if len(asset_urls) == 1 else asset_urls
            payload["assets"] = asset_urls
        return payload

    def _replace_asset_ids_with_urls(self, value: Any, asset_url_by_id: dict[str, str]) -> Any:
        if isinstance(value, list):
            return [self._replace_asset_ids_with_urls(item, asset_url_by_id) for item in value]
        if isinstance(value, str) and value in asset_url_by_id:
            return asset_url_by_id[value]
        return value

    def _normalize_quota_buckets(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        candidates = data.get("quota_buckets") or data.get("quotas") or data.get("buckets")
        if isinstance(candidates, dict):
            candidates = [candidates]
        if not isinstance(candidates, list):
            scalar_keys = {"remaining_estimate", "remaining", "credits_remaining", "total", "limit", "used"}
            candidates = [data] if any(key in data for key in scalar_keys) else []
        buckets: list[dict[str, Any]] = []
        for item in candidates:
            if not isinstance(item, dict):
                continue
            bucket = dict(item)
            bucket["type"] = str(bucket.get("type") or bucket.get("unit") or "credits")
            for key in ["remaining_estimate", "remaining", "credits_remaining", "total", "limit", "used"]:
                if key in bucket and bucket[key] is not None:
                    try:
                        bucket[key] = float(bucket[key])
                    except (TypeError, ValueError):
                        pass
            if "operation" in bucket and "operations" not in bucket:
                bucket["operations"] = [bucket.pop("operation")]
            if "provider_model" in bucket and "provider_models" not in bucket:
                bucket["provider_models"] = [bucket.pop("provider_model")]
            bucket["confidence"] = float(bucket.get("confidence", 1.0) or 0.0)
            bucket["source"] = str(bucket.get("source") or "connector")
            buckets.append(bucket)
        return buckets

    def _endpoint(self, operation: str, config: dict[str, Any]) -> str:
        endpoints = config.get("endpoints") or {}
        if operation in endpoints:
            return str(endpoints[operation])
        if operation == "text_to_image":
            return "/v1/images/generations"
        if operation in {"image_to_image", "image_edit"}:
            return "/v1/images/edits"
        if operation in {"text_to_video", "image_to_video", "video_extend"}:
            return "/v1/videos/generations"
        raise RuntimeError(f"unsupported operation {operation}")

    def _poll(
        self,
        db: Session,
        job: models.MediaJob,
        client: httpx.Client,
        base_url: str,
        endpoint: str,
        provider_task_id: str,
        headers: dict[str, str],
        config: dict[str, Any],
    ) -> dict[str, Any]:
        poll_interval = float(config.get("poll_interval_seconds") or 2)
        deadline = time.time() + float(config.get("poll_timeout_seconds") or 180)
        poll_endpoint = str(config.get("poll_endpoint") or f"{endpoint}/{provider_task_id}")
        poll_endpoint = self._render_template(poll_endpoint, {"provider_task_id": provider_task_id, "task_id": provider_task_id, "id": provider_task_id})
        poll_method = str(config.get("poll_method") or "GET").upper()
        poll_payload = config.get("poll_payload") if isinstance(config.get("poll_payload"), dict) else {"id": provider_task_id, "task_id": provider_task_id}
        poll_payload = self._render_template_value(poll_payload, {"provider_task_id": provider_task_id, "task_id": provider_task_id, "id": provider_task_id})
        self._set_job_stage(
            db,
            job,
            "polling",
            "polling",
            "Polling connector task status.",
            metadata={"provider_task_id": provider_task_id, "poll_endpoint": poll_endpoint},
        )
        while time.time() < deadline:
            if poll_method == "POST":
                response = client.post(f"{base_url}{poll_endpoint}", headers=headers, json=poll_payload)
            else:
                response = client.get(f"{base_url}{poll_endpoint}", headers=headers)
            if response.status_code >= 400:
                raise RuntimeError(f"connector poll status {response.status_code}: {response.text[:500]}")
            data = response.json()
            status = self._connector_status(data, config)
            if status in self._status_set(config, "completed_statuses", {"completed", "succeeded", "success", "done"}) or self._has_output_candidates(data, config):
                return data
            if status in self._status_set(config, "failed_statuses", {"failed", "error", "cancelled"}):
                raise RuntimeError(f"connector task failed: {data}")
            time.sleep(poll_interval)
        raise RuntimeError("PROVIDER_TIMEOUT")

    def _provider_task_id(self, data: dict[str, Any], job: models.MediaJob, config: dict[str, Any]) -> str:
        for path in self._configured_paths(config, "task_id_paths", "task_id_fields", DEFAULT_TASK_ID_PATHS):
            for value in self._values_at_path(data, path):
                if isinstance(value, str | int | float) and str(value):
                    return str(value)
        return f"connector_{job.id}"

    def _connector_status(self, data: dict[str, Any], config: dict[str, Any]) -> str:
        for path in self._configured_paths(config, "status_paths", "status_fields", DEFAULT_STATUS_PATHS):
            for value in self._values_at_path(data, path):
                if isinstance(value, str | int | float) and str(value):
                    return str(value).lower()
        return ""

    def _status_set(self, config: dict[str, Any], key: str, default: set[str]) -> set[str]:
        values = config.get(key)
        if isinstance(values, str):
            return {item.strip().lower() for item in values.split(",") if item.strip()}
        if isinstance(values, list):
            return {str(item).lower() for item in values if str(item)}
        return default

    def _has_output_candidates(self, data: dict[str, Any], config: dict[str, Any]) -> bool:
        return any(self._is_ingestible_candidate(item) for item in self._extract_output_candidates(data, config))

    def _extract_output_candidates(self, data: dict[str, Any], config: dict[str, Any]) -> list[Any]:
        paths = self._configured_paths(config, "output_paths", "result_paths", DEFAULT_OUTPUT_PATHS)
        candidates: list[Any] = []
        seen: set[str] = set()
        for path in paths:
            for value in self._values_at_path(data, path):
                for item in self._normalize_candidate_value(value):
                    marker = repr(item)
                    if marker in seen:
                        continue
                    seen.add(marker)
                    candidates.append(item)
        return candidates

    def _configured_paths(self, config: dict[str, Any], primary: str, alias: str, default: list[str]) -> list[str]:
        value = config.get(primary) if config.get(primary) is not None else config.get(alias)
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        if isinstance(value, list):
            paths = [str(item).strip() for item in value if str(item).strip()]
            return paths or default
        return default

    def _values_at_path(self, value: Any, path: str) -> list[Any]:
        if not path:
            return [value]
        values = [value]
        for part in path.split("."):
            next_values: list[Any] = []
            for item in values:
                if isinstance(item, list):
                    if part == "*":
                        next_values.extend(item)
                    else:
                        for child in item:
                            if isinstance(child, dict) and part in child:
                                next_values.append(child[part])
                elif isinstance(item, dict):
                    if part == "*":
                        next_values.extend(item.values())
                    elif part in item:
                        next_values.append(item[part])
            values = next_values
            if not values:
                break
        return values

    def _normalize_candidate_value(self, value: Any) -> list[Any]:
        if value is None:
            return []
        if isinstance(value, list):
            items: list[Any] = []
            for item in value:
                items.extend(self._normalize_candidate_value(item))
            return items
        return [value]

    def _is_ingestible_candidate(self, item: Any) -> bool:
        if isinstance(item, str):
            return bool(item.strip())
        if isinstance(item, dict):
            return any(key in item and item.get(key) for key in MEDIA_ITEM_KEYS)
        return False

    def _render_template(self, value: str, variables: dict[str, str]) -> str:
        for key, replacement in variables.items():
            value = value.replace("{" + key + "}", replacement)
        return value

    def _render_template_value(self, value: Any, variables: dict[str, str]) -> Any:
        if isinstance(value, str):
            return self._render_template(value, variables)
        if isinstance(value, list):
            return [self._render_template_value(item, variables) for item in value]
        if isinstance(value, dict):
            return {key: self._render_template_value(item, variables) for key, item in value.items()}
        return value

    def _set_job_stage(
        self,
        db: Session,
        job: models.MediaJob,
        event_type: str,
        status: str,
        message: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        job.status = status
        attempt = (
            db.query(models.MediaJobAttempt)
            .filter(
                models.MediaJobAttempt.job_id == job.id,
                models.MediaJobAttempt.status.in_(["created", "submitting", "provider_queued", "polling", "fetching_assets", "storing"]),
            )
            .order_by(models.MediaJobAttempt.created_at.desc())
            .first()
        )
        if attempt:
            attempt.status = status
        db.add(
            models.MediaJobEvent(
                id=new_id("jevt"),
                job_id=job.id,
                user_id=job.user_id,
                event_type=event_type,
                status=job.status,
                provider_id=job.provider_id or "",
                account_id=job.account_id or "",
                attempt_id=attempt.id if attempt else "",
                message=message,
                metadata_json=dumps(metadata or {}),
            )
        )
        db.flush()

    def _ingest_outputs(
        self,
        db: Session,
        client: httpx.Client,
        data: dict[str, Any],
        job: models.MediaJob,
        ctx: ProviderContext,
        config: dict[str, Any],
    ) -> list[models.MediaAsset]:
        candidates = self._extract_output_candidates(data, config)
        assets: list[models.MediaAsset] = []
        for item in candidates:
            asset = self._ingest_item(db, client, item, job, ctx, config)
            if asset:
                assets.append(asset)
        return assets

    def _ingest_item(
        self,
        db: Session,
        client: httpx.Client,
        item: Any,
        job: models.MediaJob,
        ctx: ProviderContext,
        config: dict[str, Any],
    ) -> models.MediaAsset | None:
        if isinstance(item, str):
            data_uri = self._parse_data_uri(item)
            item = data_uri or ({"url": item} if item.startswith(("http://", "https://", "/")) else {"b64_json": item})
        if not isinstance(item, dict):
            return None

        asset_service = AssetService()
        kind = "video" if job.operation in {"text_to_video", "image_to_video", "video_extend"} else "image"
        purpose = "output"
        connector_item = self._sanitize_connector_payload(
            {k: v for k, v in item.items() if k not in {"b64_json", "base64", "image_base64", "video_base64"}}
        )
        meta = {"provider": ctx.provider_id, "provider_model": ctx.provider_model, "connector_item": connector_item}

        b64_value = item.get("b64_json") or item.get("base64") or item.get("image_base64") or item.get("video_base64")
        if b64_value:
            parsed = self._parse_data_uri(str(b64_value))
            if parsed:
                item = {**item, **parsed}
                b64_value = item["b64_json"]
            mime_type = str(item.get("mime_type") or item.get("content_type") or ("video/mp4" if kind == "video" else "image/png"))
            return asset_service.create_from_base64(
                db,
                job.user_id,
                str(b64_value),
                f"connector.{self._suffix(mime_type)}",
                kind,
                purpose,
                mime_type,
                source="provider_result",
                provider_meta=meta,
            )

        url = item.get("url") or item.get("download_url") or item.get("content_url") or item.get("media_url") or item.get("image_url") or item.get("video_url")
        if not url and item.get("asset_id"):
            provider = db.get(models.Provider, ctx.provider_id)
            provider_config = loads(provider.base_config_json if provider else "{}", {})
            base_url = str(provider_config.get("base_url") or "").rstrip("/")
            if base_url:
                url = f"{base_url}/v1/assets/{item['asset_id']}/content"
        if not url:
            return None
        if isinstance(url, str) and url.startswith("/"):
            base_url = str(config.get("base_url") or "").rstrip("/")
            url = f"{base_url}{url}" if base_url else url

        response = client.get(str(url), follow_redirects=True)
        if response.status_code >= 400:
            raise RuntimeError(f"failed to fetch connector asset {response.status_code}")
        mime_type = response.headers.get("content-type", "").split(";", 1)[0] or str(item.get("mime_type") or item.get("content_type") or ("video/mp4" if kind == "video" else "image/png"))
        filename = f"connector.{self._suffix(mime_type)}"
        return asset_service.create_from_bytes(db, job.user_id, response.content, filename, kind, purpose, mime_type, source="provider_result", provider_meta=meta)

    def _sanitize_connector_payload(self, value: Any, key: str = "") -> Any:
        if isinstance(value, dict):
            sanitized: dict[str, Any] = {}
            for child_key, child_value in value.items():
                child_key_text = str(child_key)
                lower_key = child_key_text.lower()
                if lower_key in {"b64_json", "base64", "image_base64", "video_base64"} and isinstance(child_value, str):
                    sanitized[f"{child_key_text}_sha256"] = hashlib.sha256(child_value.encode("utf-8")).hexdigest()
                    sanitized[f"{child_key_text}_chars"] = len(child_value)
                    continue
                if self._is_url_field(child_key_text) and isinstance(child_value, str) and child_value.startswith(("http://", "https://")):
                    sanitized[f"{child_key_text}_hash"] = hashlib.sha256(child_value.encode("utf-8")).hexdigest()
                    continue
                sanitized[child_key_text] = self._sanitize_connector_payload(child_value, child_key_text)
            return sanitized
        if isinstance(value, list):
            return [self._sanitize_connector_payload(item, key) for item in value]
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            return {"url_hash": hashlib.sha256(value.encode("utf-8")).hexdigest()}
        return value

    def _is_url_field(self, key: str) -> bool:
        lower_key = key.lower()
        return lower_key in {"url", "download_url", "content_url", "media_url", "image_url", "video_url", "uri"} or lower_key.endswith("_url")

    def _parse_data_uri(self, value: str) -> dict[str, str] | None:
        if not value.startswith("data:") or ";base64," not in value:
            return None
        header, payload = value.split(";base64,", 1)
        mime_type = header.replace("data:", "", 1) or "application/octet-stream"
        return {"b64_json": payload, "mime_type": mime_type}

    def _suffix(self, mime_type: str) -> str:
        if mime_type == "video/mp4":
            return "mp4"
        if mime_type in {"image/jpeg", "image/jpg"}:
            return "jpg"
        if mime_type == "image/webp":
            return "webp"
        return "png"


def get_provider(provider_id: str) -> MediaProviderAdapter:
    if provider_id == "mock":
        return MockProvider()
    if provider_id == "pollinations":
        return PollinationsProvider()
    return ConnectorProvider(provider_id)
