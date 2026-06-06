from __future__ import annotations

from datetime import datetime
import time
from typing import Any

import httpx
from sqlalchemy.orm import Session

from . import models
from .provider_templates import PROVIDER_TEMPLATES
from .providers import get_provider, resolve_credential
from .utils import dumps, loads, redact_sensitive


OPERATION_DEFAULTS: dict[str, dict[str, Any]] = {
    "text_to_image": {
        "input_asset_fields": [],
        "max_input_assets": 0,
        "output_kind": "image",
        "params": ["prompt", "size", "quality", "n", "seed", "negative_prompt"],
    },
    "image_to_image": {
        "input_asset_fields": ["image", "images"],
        "max_input_assets": 4,
        "output_kind": "image",
        "params": ["prompt", "image", "images", "size", "quality", "n", "seed", "negative_prompt"],
    },
    "image_edit": {
        "input_asset_fields": ["image", "images", "mask"],
        "max_input_assets": 5,
        "output_kind": "image",
        "params": ["prompt", "image", "images", "mask", "size", "quality", "n", "seed", "negative_prompt"],
    },
    "text_to_video": {
        "input_asset_fields": [],
        "max_input_assets": 0,
        "output_kind": "video",
        "duration_seconds": {"min": 1, "max": 30},
        "params": ["prompt", "duration", "aspect_ratio", "quality", "seed", "negative_prompt"],
    },
    "image_to_video": {
        "input_asset_fields": ["image", "images", "first_frame", "last_frame"],
        "max_input_assets": 4,
        "output_kind": "video",
        "duration_seconds": {"min": 1, "max": 30},
        "params": ["prompt", "image", "images", "first_frame", "last_frame", "duration", "aspect_ratio", "quality", "seed", "negative_prompt"],
    },
    "video_extend": {
        "input_asset_fields": ["video", "videos"],
        "max_input_assets": 2,
        "output_kind": "video",
        "duration_seconds": {"min": 1, "max": 30},
        "params": ["prompt", "video", "videos", "duration", "aspect_ratio", "quality", "seed", "negative_prompt"],
    },
}


class ProviderCapabilityService:
    def sync_remote(self, db: Session, provider: models.Provider, endpoint: str | None = None, timeout_seconds: float | None = None) -> dict[str, Any]:
        config = loads(provider.base_config_json, {})
        base_url = str(config.get("base_url") or "").rstrip("/")
        if not base_url:
            return {
                "object": "provider_capability_sync",
                "provider_id": provider.id,
                "status": "failed",
                "error_code": "PROVIDER_CONFIG_INVALID",
                "message": "Provider base_config.base_url is required.",
            }
        capability_endpoint = str(endpoint or config.get("capability_endpoint") or config.get("capabilities_endpoint") or "/capabilities")
        if not capability_endpoint.startswith("/"):
            capability_endpoint = "/" + capability_endpoint
        timeout = float(timeout_seconds or config.get("capability_timeout_seconds") or config.get("health_timeout_seconds") or 10)
        account = (
            db.query(models.AccountResource)
            .filter(models.AccountResource.provider_id == provider.id, models.AccountResource.status == "active")
            .order_by(models.AccountResource.updated_at.desc())
            .first()
        )
        headers = self._headers(db, config, account.credential_ref if account else None)
        started = time.time()
        try:
            response = httpx.get(f"{base_url}{capability_endpoint}", headers=headers, timeout=timeout)
            latency_ms = int((time.time() - started) * 1000)
            if response.status_code >= 400:
                return {
                    "object": "provider_capability_sync",
                    "provider_id": provider.id,
                    "status": "failed",
                    "error_code": "CAPABILITY_SYNC_FAILED",
                    "message": f"connector capabilities status {response.status_code}",
                    "latency_ms": latency_ms,
                    "detail": {"body": response.text[:500]},
                }
            raw = response.json()
        except Exception as exc:
            return {
                "object": "provider_capability_sync",
                "provider_id": provider.id,
                "status": "failed",
                "error_code": "CAPABILITY_SYNC_FAILED",
                "message": str(exc),
            }

        normalized = self.normalize_remote_capabilities(raw)
        if not normalized.get("operations") and not normalized.get("models") and not normalized.get("operation_capabilities"):
            return {
                "object": "provider_capability_sync",
                "provider_id": provider.id,
                "status": "failed",
                "error_code": "CAPABILITY_PAYLOAD_INVALID",
                "message": "Connector capabilities response did not include operations, models, or operation_capabilities.",
                "latency_ms": latency_ms,
                "raw": redact_sensitive(raw),
            }

        before = config.get("capabilities") if isinstance(config.get("capabilities"), dict) else {}
        config["capabilities"] = normalized
        config["capability_endpoint"] = capability_endpoint
        config["capability_last_sync_at"] = datetime.utcnow().isoformat() + "Z"
        provider.base_config_json = dumps(config)
        db.commit()
        return {
            "object": "provider_capability_sync",
            "provider_id": provider.id,
            "status": "ok",
            "message": "Provider capabilities synchronized from connector.",
            "latency_ms": latency_ms,
            "endpoint": capability_endpoint,
            "before": redact_sensitive(before),
            "capabilities": normalized,
            "snapshot": self.snapshot(db, provider),
        }

    def normalize_remote_capabilities(self, data: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(data, dict):
            return {}
        payload = data.get("capabilities") if isinstance(data.get("capabilities"), dict) else data
        operations = self._string_list(payload.get("operations") or payload.get("supported_operations") or payload.get("tasks"))
        models_ = self._model_list(payload.get("models") or payload.get("provider_models") or payload.get("model_ids"))
        operation_capabilities = payload.get("operation_capabilities") or payload.get("operation_profiles") or {}
        normalized_profiles: dict[str, dict[str, Any]] = {}
        if isinstance(operation_capabilities, dict):
            for operation, profile in operation_capabilities.items():
                if not isinstance(profile, dict):
                    continue
                op = str(operation)
                normalized_profiles[op] = redact_sensitive(dict(profile))
                if op not in operations:
                    operations.append(op)
        for model in payload.get("model_capabilities") or []:
            if isinstance(model, dict):
                model_id = model.get("id") or model.get("model") or model.get("name")
                if model_id and str(model_id) not in models_:
                    models_.append(str(model_id))
                for operation in self._string_list(model.get("operations") or model.get("supported_operations")):
                    if operation not in operations:
                        operations.append(operation)
        return {
            "operations": sorted(dict.fromkeys(operations)),
            "models": sorted(dict.fromkeys(models_)),
            "operation_capabilities": normalized_profiles,
            "source": "connector_capabilities",
        }

    def snapshot(self, db: Session, provider: models.Provider) -> dict[str, Any]:
        template = PROVIDER_TEMPLATES.get(provider.id)
        adapter = get_provider(provider.id)
        adapter_caps = adapter.capabilities()
        config = loads(provider.base_config_json, {})
        configured_caps = config.get("capabilities") if isinstance(config.get("capabilities"), dict) else {}
        mappings = db.query(models.ProviderModelMapping).filter(models.ProviderModelMapping.provider_id == provider.id).order_by(models.ProviderModelMapping.logical_model).all()
        accounts = db.query(models.AccountResource).filter(models.AccountResource.provider_id == provider.id).all()

        operations = set(adapter_caps.get("operations") or [])
        models_ = set(adapter_caps.get("models") or [])
        if template:
            operations.update(template.operations)
            models_.update(template.models)
        for mapping in mappings:
            operations.update(loads(mapping.operations_json, []))
            models_.add(mapping.provider_model)
        if configured_caps.get("operations"):
            operations.update(configured_caps["operations"])
        if configured_caps.get("models"):
            models_.update(configured_caps["models"])

        operation_capabilities = {}
        configured_operations = configured_caps.get("operation_capabilities") if isinstance(configured_caps.get("operation_capabilities"), dict) else {}
        for operation in sorted(operations):
            profile = dict(OPERATION_DEFAULTS.get(operation, {"input_asset_fields": [], "max_input_assets": None, "output_kind": "unknown", "params": []}))
            if isinstance(configured_operations.get(operation), dict):
                profile.update(configured_operations[operation])
            operation_capabilities[operation] = profile

        active_accounts = [account for account in accounts if account.status == "active"]
        return {
            "provider_id": provider.id,
            "name": provider.name,
            "status": provider.status,
            "adapter_type": provider.adapter_type,
            "template_available": template is not None,
            "operations": sorted(operations),
            "models": sorted(model for model in models_ if model),
            "logical_models": sorted({mapping.logical_model for mapping in mappings}),
            "operation_capabilities": operation_capabilities,
            "mappings": [
                {
                    "id": mapping.id,
                    "logical_model": mapping.logical_model,
                    "provider_model": mapping.provider_model,
                    "operations": loads(mapping.operations_json, []),
                    "enabled": mapping.enabled,
                }
                for mapping in mappings
            ],
            "accounts": {
                "total": len(accounts),
                "active": len(active_accounts),
                "available_capacity": sum(max(account.concurrency_limit - account.current_leases, 0) for account in active_accounts),
            },
            "raw_adapter_capabilities": adapter_caps,
        }

    def _headers(self, db: Session, config: dict[str, Any], credential_ref: str | None) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        api_key = resolve_credential(str(config.get("api_key_ref") or ""), db) or resolve_credential(credential_ref, db)
        if api_key:
            header_name = str(config.get("api_key_header") or "Authorization")
            headers[header_name] = f"Bearer {api_key}" if header_name.lower() == "authorization" else api_key
        return headers

    def _string_list(self, value: Any) -> list[str]:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return []

    def _model_list(self, value: Any) -> list[str]:
        if isinstance(value, str):
            return self._string_list(value)
        if not isinstance(value, list):
            return []
        models_: list[str] = []
        for item in value:
            if isinstance(item, dict):
                model_id = item.get("id") or item.get("model") or item.get("name")
                if model_id:
                    models_.append(str(model_id))
            elif str(item).strip():
                models_.append(str(item).strip())
        return models_
