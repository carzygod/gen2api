from __future__ import annotations

import ipaddress
import socket
import time
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy.orm import Session

from . import models
from .config import settings
from .services_assets import AssetService
from .utils import dumps, loads, new_id


class WebhookService:
    def build_payload(self, db: Session, job: models.MediaJob) -> dict[str, Any]:
        asset_service = AssetService()
        outputs = []
        for asset_id in loads(job.output_asset_ids_json, []):
            asset = db.get(models.MediaAsset, asset_id)
            if asset:
                outputs.append(
                    {
                        "id": asset.id,
                        "kind": asset.kind,
                        "mime_type": asset.mime_type,
                        "url": asset_service.public_url(asset),
                        "size_bytes": asset.size_bytes,
                    }
                )
        return {
            "event": "media_job.finished",
            "job": {
                "id": job.id,
                "status": job.status,
                "operation": job.operation,
                "model": job.logical_model,
                "provider": job.provider_id,
                "provider_model": job.provider_model,
                "error": {"code": job.error_code, "message": job.error_message} if job.error_code else None,
                "outputs": outputs,
                "cost_estimate": job.cost_estimate,
                "final_cost": job.final_cost,
            },
        }

    def maybe_deliver(self, db: Session, job: models.MediaJob) -> None:
        params = loads(job.normalized_params_json, {})
        webhook_url = params.get("webhook") or params.get("webhook_url")
        if not webhook_url:
            return
        payload = self.build_payload(db, job)
        delivery = models.WebhookDelivery(
            id=new_id("wh"),
            job_id=job.id,
            user_id=job.user_id,
            target_url=str(webhook_url),
            status="pending",
            attempts=0,
            payload_json=dumps(payload),
        )
        db.add(delivery)
        db.flush()
        self.deliver_with_retries(db, delivery)

    def deliver(self, db: Session, delivery: models.WebhookDelivery) -> None:
        delivery.attempts += 1
        try:
            target_url = self._validate_target_url(delivery.target_url)
            response = httpx.post(target_url, json=loads(delivery.payload_json, {}), timeout=10, follow_redirects=False)
            delivery.last_status_code = response.status_code
            if 200 <= response.status_code < 300:
                delivery.status = "delivered"
                delivery.last_error = ""
            else:
                delivery.status = "failed"
                delivery.last_error = response.text[:1000]
        except ValueError as exc:
            delivery.status = "failed"
            delivery.last_error = str(exc)
        except Exception as exc:
            delivery.status = "failed"
            delivery.last_error = str(exc)
        db.flush()

    def deliver_with_retries(self, db: Session, delivery: models.WebhookDelivery, max_attempts: int | None = None) -> None:
        max_attempts = max(1, int(max_attempts or settings.webhook_max_attempts))
        while delivery.status != "delivered" and delivery.attempts < max_attempts:
            self.deliver(db, delivery)
            if delivery.status == "delivered" or delivery.attempts >= max_attempts:
                break
            if delivery.last_error.startswith("WEBHOOK_URL_"):
                break
            if settings.webhook_retry_delay_seconds > 0:
                time.sleep(settings.webhook_retry_delay_seconds)

    def retry(self, db: Session, delivery: models.WebhookDelivery, attempts: int = 1) -> models.WebhookDelivery:
        delivery.status = "pending"
        delivery.last_error = ""
        target_attempts = delivery.attempts + max(1, int(attempts))
        self.deliver_with_retries(db, delivery, max_attempts=target_attempts)
        return delivery

    def retry_failed(self, db: Session, limit: int = 50, attempts: int = 1) -> list[models.WebhookDelivery]:
        deliveries = (
            db.query(models.WebhookDelivery)
            .filter(models.WebhookDelivery.status.in_(["failed", "pending"]))
            .order_by(models.WebhookDelivery.updated_at.asc())
            .limit(min(limit, 500))
            .all()
        )
        for delivery in deliveries:
            self.retry(db, delivery, attempts=attempts)
        return deliveries

    def _validate_target_url(self, url: str) -> str:
        candidate = (url or "").strip()
        if not candidate or len(candidate) > settings.webhook_url_max_length:
            raise ValueError("WEBHOOK_URL_INVALID")
        parsed = urlparse(candidate)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("WEBHOOK_URL_SCHEME_UNSUPPORTED")
        if parsed.username or parsed.password:
            raise ValueError("WEBHOOK_URL_CREDENTIALS_UNSUPPORTED")
        if not parsed.hostname:
            raise ValueError("WEBHOOK_URL_HOST_REQUIRED")
        host = parsed.hostname.rstrip(".").lower()
        allowed_hosts = settings.webhook_url_allowed_hosts
        if allowed_hosts and host not in allowed_hosts:
            raise ValueError("WEBHOOK_URL_HOST_NOT_ALLOWED")
        if not settings.webhook_url_allow_private and host not in allowed_hosts:
            self._validate_public_host(host, parsed.port, parsed.scheme)
        return candidate

    def _validate_public_host(self, host: str, port: int | None, scheme: str) -> None:
        try:
            infos = socket.getaddrinfo(host, port or (443 if scheme == "https" else 80), type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise ValueError("WEBHOOK_URL_RESOLUTION_FAILED") from exc
        if not infos:
            raise ValueError("WEBHOOK_URL_RESOLUTION_FAILED")
        for info in infos:
            address = info[4][0]
            try:
                parsed_address = ipaddress.ip_address(address)
            except ValueError as exc:
                raise ValueError("WEBHOOK_URL_RESOLUTION_FAILED") from exc
            if not parsed_address.is_global:
                raise ValueError("WEBHOOK_URL_PRIVATE_ADDRESS_BLOCKED")
