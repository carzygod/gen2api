from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import httpx
from sqlalchemy.orm import Session

from . import models
from .providers import resolve_credential
from .services_connector_registry import (
    RUNTIME_BASE_URL_FIELD_NAMES,
    provider_runtime_base_url_allowed,
    provider_runtime_config,
    strip_runtime_base_url_fields,
)
from .utils import dumps, loads, new_id, redact_sensitive


SAFE_CREDENTIAL_REF_PREFIXES = (
    "env://",
    "secret://",
    "public://",
    "vault://",
    "subscription://",
    "oauth://",
    "cli://",
    "websession://",
    "mcp://",
    "endpoint://",
    "connector://",
    "tokenref://",
    "agent://",
)

SUCCESS_STATUSES = {"completed", "complete", "succeeded", "success", "done", "authorized", "ready"}
FAILED_STATUSES = {"failed", "failure", "error", "errored", "cancelled", "expired", "rejected"}
AUTH_METHOD_ALIASES = {
    "oauth": "agent_provider_credential",
    "oauth_ref": "agent_provider_credential",
    "oauth_reference": "agent_provider_credential",
    "web": "cookie_secret",
    "web_session": "cookie_secret",
    "websession": "cookie_secret",
    "browser_session": "cookie_secret",
    "cookie": "cookie_secret",
    "cookie_reference": "cookie_secret",
    "cookie_secret": "cookie_secret",
    "cookie_header": "cookie_secret",
    "cookie_jar": "cookie_secret",
    "cli": "agent_provider_credential",
    "cli_credential": "agent_provider_credential",
    "cli_credential_reference": "agent_provider_credential",
    "agent": "agent_provider_credential",
    "agent_provider": "agent_provider_credential",
    "agent_provider_credential": "agent_provider_credential",
    "subscription": "agent_provider_credential",
    "subscription_url": "agent_provider_credential",
    "mcp": "agent_provider_credential",
    "mcp_config": "agent_provider_credential",
    "mcp_config_reference": "agent_provider_credential",
    "endpoint": "agent_provider_credential",
    "self_hosted_endpoint": "agent_provider_credential",
    "aggregator_api_key": "agent_provider_credential",
    "api_key": "agent_provider_credential",
    "token": "agent_provider_credential",
    "token_reference": "agent_provider_credential",
    "secret_json": "agent_provider_credential",
}
AUTH_METHOD_BY_REF_PREFIX = {
    "subscription://": "agent_provider_credential",
    "oauth://": "agent_provider_credential",
    "cli://": "agent_provider_credential",
    "websession://": "cookie_secret",
    "agent://": "agent_provider_credential",
    "mcp://": "agent_provider_credential",
    "endpoint://": "agent_provider_credential",
    "connector://": "agent_provider_credential",
    "tokenref://": "agent_provider_credential",
    "vault://": "agent_provider_credential",
}

RESOURCE_TYPE_BY_AUTH_METHOD = {
    "cookie_secret": "web_cookie_provider",
    "web_session_reference": "web_cookie_provider",
    "agent_provider_credential": "agent_provider",
    "oauth_reference": "agent_provider",
    "cli_credential_reference": "agent_provider",
    "mcp_config_reference": "agent_provider",
}
RESOURCE_TYPE_BY_REF_PREFIX = {
    "agent://": "agent_provider",
    "websession://": "web_cookie_provider",
    "oauth://": "agent_provider",
    "cli://": "agent_provider",
    "mcp://": "agent_provider",
    "endpoint://": "agent_provider",
    "connector://": "agent_provider",
    "tokenref://": "agent_provider",
    "subscription://": "agent_provider",
    "vault://": "agent_provider",
    "env://": "agent_provider",
    "public://": "agent_provider",
}
ACCOUNT_RESOURCE_TYPES = {"web_cookie_provider", "agent_provider"}


def _normalized_auth_method(auth_method: str | None) -> str:
    value = str(auth_method or "").strip()
    return AUTH_METHOD_ALIASES.get(value.lower(), value)


def _expected_resource_type_for_auth_method(auth_method: str | None) -> str:
    return RESOURCE_TYPE_BY_AUTH_METHOD.get(_normalized_auth_method(auth_method), "")


def _expected_resource_type_for_credential_ref(credential_ref: str | None) -> str:
    ref = str(credential_ref or "").strip().lower()
    for prefix, resource_type in RESOURCE_TYPE_BY_REF_PREFIX.items():
        if ref.startswith(prefix):
            return resource_type
    return ""


def _credential_ref_prefix(credential_ref: str | None) -> str:
    ref = str(credential_ref or "").strip()
    if "://" not in ref:
        return ""
    return ref.split("://", 1)[0] + "://"


class ConnectorOAuthSessionService:
    def start_session(self, db: Session, payload: dict[str, Any]) -> dict[str, Any]:
        provider_id = str(payload.get("provider_id") or "").strip()
        if not provider_id:
            raise ValueError("PROVIDER_ID_REQUIRED")
        provider = db.get(models.Provider, provider_id)
        if not provider:
            raise ValueError("PROVIDER_NOT_FOUND")

        provider_config = provider_runtime_config(provider_id, loads(provider.base_config_json, {}))
        allow_provider_config_base_url = bool(payload.get("allow_provider_config_base_url", True))
        configured_base_url = provider_config.get("base_url") if allow_provider_config_base_url else ""
        base_url = str(payload.get("provider_base_url") or configured_base_url or "").rstrip("/")
        endpoint = str(payload.get("oauth_start_endpoint") or provider_config.get("oauth_start_endpoint") or "/oauth/start")
        session_id = str(payload.get("session_id") or new_id("arsess"))
        account_id = str(payload.get("account_id") or f"acct_{provider_id}_{new_id('auth')[-8:]}")
        auth_method = str(payload.get("auth_method") or "agent_provider_credential")
        callback_url = str(
            payload.get("callback_url")
            or provider_config.get("oauth_callback_url")
            or provider_config.get("callback_url")
            or f"/v1/admin/authorized-resource-sessions/{session_id}/callback"
        )
        callback_url = callback_url.replace("{session_id}", session_id).replace("{account_id}", account_id).replace("{provider_id}", provider_id)
        now = datetime.utcnow()
        session = models.ConnectorOAuthSession(
            id=session_id,
            provider_id=provider_id,
            account_id=account_id,
            label=str(payload.get("label") or f"{provider_id} authorization session"),
            status="planned" if payload.get("dry_run") or not base_url else "pending",
            auth_method=auth_method,
            connector_base_url=base_url,
            callback_url=callback_url,
            requested_operations_json=dumps(payload.get("supported_operations") or payload.get("requested_operations") or []),
            requested_provider_models_json=dumps(payload.get("supported_provider_models") or payload.get("requested_provider_models") or []),
            metadata_json=dumps({"request": redact_sensitive(payload), "provider_config_keys": sorted(provider_config)}),
            expires_at=now + timedelta(minutes=int(payload.get("ttl_minutes") or 30)),
        )
        db.add(session)
        db.flush()
        transient_credential_value = ""

        if base_url and not payload.get("dry_run"):
            try:
                response = self._post(
                    db,
                    provider_config,
                    f"{base_url}{endpoint}",
                    {
                        "session_id": session.id,
                        "provider_id": provider_id,
                        "account_id": account_id,
                        "label": session.label,
                        "auth_method": auth_method,
                        "resource_type": payload.get("resource_type") or "",
                        "resource_profile": payload.get("resource_profile") or {},
                        "callback_url": session.callback_url,
                        "requested_operations": loads(session.requested_operations_json, []),
                        "requested_provider_models": loads(session.requested_provider_models_json, []),
                        "metadata": payload.get("metadata") or {},
                    },
                    timeout=float(provider_config.get("oauth_timeout_seconds") or 30),
                )
                data = response.json()
                completion = self._normalize_completion_payload(session, payload, data)
                self._validate_completion_resource_type(
                    provider_id=session.provider_id,
                    requested_auth_method=auth_method,
                    requested_resource_type=str(payload.get("resource_type") or ""),
                    completion=completion,
                )
                credential_ref = completion["credential_ref"]
                transient_credential_value = str(completion.get("_credential_value") or "").strip()
                session.connector_session_id = completion["connector_session_id"] or session.connector_session_id
                session.authorize_url = completion["authorize_url"] or session.authorize_url
                session.auth_method = completion["auth_method"] or session.auth_method
                if completion["account_id"]:
                    session.account_id = completion["account_id"]
                if completion["label"]:
                    session.label = completion["label"]
                if completion["supported_operations"]:
                    session.requested_operations_json = dumps(completion["supported_operations"])
                if completion["supported_provider_models"]:
                    session.requested_provider_models_json = dumps(completion["supported_provider_models"])
                if credential_ref:
                    session.credential_ref = credential_ref
                    session.status = "completed"
                    session.completed_at = datetime.utcnow()
                elif transient_credential_value and completion["status"] == "completed":
                    session.status = "completed"
                    session.completed_at = datetime.utcnow()
                elif completion["status"] in FAILED_STATUSES:
                    session.status = "failed"
                session.metadata_json = dumps(
                    {
                        "request": redact_sensitive(payload),
                        "start_response": self._sanitize_response(data),
                        "completion": self._sanitize_response(completion),
                        "provider_config_keys": sorted(provider_config),
                    }
                )
            except Exception as exc:
                session.status = "failed"
                session.error_code = type(exc).__name__
                session.error_message = str(exc)
        db.commit()
        result = self.serialize(session)
        if transient_credential_value:
            result["_credential_value"] = transient_credential_value
        return result

    def complete_session(self, db: Session, session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        session = db.get(models.ConnectorOAuthSession, session_id)
        if not session:
            raise ValueError("AUTHORIZED_RESOURCE_SESSION_NOT_FOUND")
        provider = db.get(models.Provider, session.provider_id)
        provider_config = provider_runtime_config(session.provider_id, loads(provider.base_config_json if provider else "{}", {}))
        data = payload.get("connector_response") if isinstance(payload.get("connector_response"), dict) else {}
        completion = self._normalize_completion_payload(session, payload, data)
        credential_ref = completion["credential_ref"]
        transient_credential_value = str(completion.get("_credential_value") or "").strip()

        if not credential_ref and session.connector_base_url:
            endpoint_template = str(payload.get("oauth_status_endpoint") or provider_config.get("oauth_status_endpoint") or "/oauth/sessions/{session_id}")
            connector_session_id = session.connector_session_id or session.id
            endpoint = endpoint_template.replace("{session_id}", connector_session_id).replace("{connector_session_id}", connector_session_id)
            try:
                response = self._request(
                    db,
                    provider_config,
                    str(payload.get("oauth_status_method") or provider_config.get("oauth_status_method") or "GET"),
                    f"{session.connector_base_url}{endpoint}",
                    {"session_id": connector_session_id, "account_id": session.account_id, "provider_id": session.provider_id},
                    timeout=float(provider_config.get("oauth_timeout_seconds") or 30),
                )
                data = response.json()
                completion = self._normalize_completion_payload(session, payload, data)
                credential_ref = completion["credential_ref"]
                transient_credential_value = str(completion.get("_credential_value") or "").strip()
            except Exception as exc:
                session.status = "failed"
                session.error_code = type(exc).__name__
                session.error_message = str(exc)
                db.commit()
                return self.serialize(session)

        self._validate_completion_resource_type(
            provider_id=session.provider_id,
            requested_auth_method=session.auth_method,
            requested_resource_type=str(payload.get("resource_type") or ""),
            completion=completion,
        )
        if completion["connector_session_id"]:
            session.connector_session_id = completion["connector_session_id"]
        if completion["authorize_url"]:
            session.authorize_url = completion["authorize_url"]
        if completion["account_id"]:
            session.account_id = completion["account_id"]
        if completion["label"]:
            session.label = completion["label"]
        if completion["auth_method"]:
            session.auth_method = completion["auth_method"]
        if completion["provider_base_url"]:
            session.connector_base_url = completion["provider_base_url"]
        if completion["supported_operations"]:
            session.requested_operations_json = dumps(completion["supported_operations"])
        if completion["supported_provider_models"]:
            session.requested_provider_models_json = dumps(completion["supported_provider_models"])
        if credential_ref:
            session.credential_ref = credential_ref
            session.status = "completed"
            session.completed_at = datetime.utcnow()
            merged = loads(session.metadata_json, {})
            merged["complete_response"] = self._sanitize_response(data)
            merged["completion"] = self._sanitize_response(completion)
            session.metadata_json = dumps(merged)
        elif transient_credential_value and completion["status"] == "completed":
            session.status = "completed"
            session.completed_at = datetime.utcnow()
            merged = loads(session.metadata_json, {})
            merged["complete_response"] = self._sanitize_response(data)
            merged["completion"] = self._sanitize_response(completion)
            session.metadata_json = dumps(merged)
        elif completion["status"] in FAILED_STATUSES:
            session.status = "failed"
            session.error_code = session.error_code or "CONNECTOR_LOGIN_FAILED"
            session.error_message = session.error_message or str(completion.get("message") or "Connector login failed.")
        elif session.status not in {"failed", "completed"}:
            session.status = "pending"
        db.commit()
        result = self.serialize(session)
        if transient_credential_value:
            result["_credential_value"] = transient_credential_value
        return result

    def list_sessions(self, db: Session, provider_id: str | None = None, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        query = db.query(models.ConnectorOAuthSession)
        if provider_id:
            query = query.filter(models.ConnectorOAuthSession.provider_id == provider_id)
        if status:
            query = query.filter(models.ConnectorOAuthSession.status == status)
        rows = query.order_by(models.ConnectorOAuthSession.created_at.desc()).limit(min(limit, 500)).all()
        return [self.serialize(row) for row in rows]

    def serialize(self, session: models.ConnectorOAuthSession) -> dict[str, Any]:
        runtime_base_url_allowed = provider_runtime_base_url_allowed(session.provider_id)
        connector_base_url = session.connector_base_url if runtime_base_url_allowed else ""
        metadata = loads(session.metadata_json, {})
        if not runtime_base_url_allowed:
            metadata = strip_runtime_base_url_fields(metadata)
            provider_config_keys = metadata.get("provider_config_keys")
            if isinstance(provider_config_keys, list):
                metadata["provider_config_keys"] = [
                    key for key in provider_config_keys
                    if str(key) not in RUNTIME_BASE_URL_FIELD_NAMES
                ]
        return {
            "object": "media2api.authorized_resource_session",
            "compat_object": "media2api.connector_oauth_session",
            "id": session.id,
            "provider_id": session.provider_id,
            "account_id": session.account_id,
            "label": session.label,
            "status": session.status,
            "auth_method": session.auth_method,
            "connector_base_url": connector_base_url,
            "connector_session_id": session.connector_session_id,
            "authorize_url": session.authorize_url,
            "callback_url": session.callback_url,
            "credential_ref": session.credential_ref,
            "requested_operations": loads(session.requested_operations_json, []),
            "requested_provider_models": loads(session.requested_provider_models_json, []),
            "supported_operations": loads(session.requested_operations_json, []),
            "supported_provider_models": loads(session.requested_provider_models_json, []),
            "provider_base_url": connector_base_url,
            "account_label": session.label,
            "quota_buckets": (metadata.get("completion") or {}).get("quota_buckets") or [],
            "concurrency_limit": (metadata.get("completion") or {}).get("concurrency_limit"),
            "region": (metadata.get("completion") or {}).get("region") or "",
            "plan": (metadata.get("completion") or {}).get("plan") or "",
            "metadata": metadata,
            "error_code": session.error_code,
            "error_message": session.error_message,
            "expires_at": session.expires_at.isoformat() + "Z" if session.expires_at else None,
            "completed_at": session.completed_at.isoformat() + "Z" if session.completed_at else None,
            "created_at": session.created_at.isoformat() + "Z" if session.created_at else None,
            "updated_at": session.updated_at.isoformat() + "Z" if session.updated_at else None,
        }

    def _post(self, db: Session, config: dict[str, Any], url: str, payload: dict[str, Any], timeout: float) -> httpx.Response:
        return self._request(db, config, "POST", url, payload, timeout)

    def _request(self, db: Session, config: dict[str, Any], method: str, url: str, payload: dict[str, Any], timeout: float) -> httpx.Response:
        headers = self._headers(db, config)
        with httpx.Client(timeout=timeout) as client:
            if method.upper() == "GET":
                response = client.get(url, headers=headers)
            else:
                response = client.post(url, headers=headers, json=payload)
        if response.status_code >= 400:
            raise RuntimeError(f"authorized resource session status {response.status_code}: {response.text[:500]}")
        return response

    def _headers(self, db: Session, config: dict[str, Any]) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        api_key = (
            resolve_credential(str(config.get("oauth_credential_ref") or ""), db)
            or resolve_credential(str(config.get("credential_ref") or ""), db)
            or resolve_credential(str(config.get("api_key_ref") or ""), db)
        )
        if api_key:
            header_name = str(config.get("oauth_api_key_header") or config.get("api_key_header") or "Authorization")
            headers[header_name] = f"Bearer {api_key}" if header_name.lower() == "authorization" else api_key
        return headers

    def _extract_credential_ref(self, data: dict[str, Any]) -> str:
        for key in [
            "credential_ref",
            "credentialRef",
            "credential_reference",
            "account_ref",
            "accountRef",
            "oauth_ref",
            "oauthRef",
            "websession_ref",
            "web_session_ref",
            "webSessionRef",
            "session_ref",
            "sessionRef",
            "token_reference",
            "tokenReference",
            "subscription_ref",
            "subscriptionRef",
            "vault_ref",
            "vaultRef",
            "resource_ref",
            "resourceRef",
        ]:
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        for key in ["account", "resource", "credential", "credentials", "session", "data"]:
            nested = data.get(key)
            if isinstance(nested, dict):
                ref = self._extract_credential_ref(nested)
                if ref:
                    return ref
            if isinstance(nested, list):
                for item in nested:
                    if isinstance(item, dict):
                        ref = self._extract_credential_ref(item)
                        if ref:
                            return ref
        return ""

    def _normalize_credential_value(self, value: Any) -> str:
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, (dict, list)):
            return dumps(value)
        return ""

    def _extract_credential_value(self, data: dict[str, Any]) -> str:
        sources: list[Any] = [data]
        for source in sources:
            if not isinstance(source, dict):
                continue
            for key in [
                "credential_value",
                "credentialValue",
                "credential_material",
                "credentialMaterial",
                "credential_secret",
                "credentialSecret",
                "secret_value",
                "secretValue",
            ]:
                value = self._normalize_credential_value(source.get(key))
                if value:
                    return value
            for key in ["account", "resource", "credential", "credentials", "session", "data"]:
                nested = source.get(key)
                if isinstance(nested, dict):
                    sources.append(nested)
                elif isinstance(nested, list):
                    sources.extend(item for item in nested if isinstance(item, dict))
        return ""

    def _first(self, data: dict[str, Any], *keys: str) -> str:
        for key in keys:
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    def _sanitize_response(self, data: dict[str, Any]) -> dict[str, Any]:
        return redact_sensitive(data)

    def _validate_completion_resource_type(
        self,
        *,
        provider_id: str,
        requested_auth_method: str | None,
        requested_resource_type: str | None,
        completion: dict[str, Any],
    ) -> None:
        credential_ref = str(completion.get("credential_ref") or "").strip()
        if credential_ref and not credential_ref.startswith(SAFE_CREDENTIAL_REF_PREFIXES):
            raise ValueError("AUTHORIZED_RESOURCE_CREDENTIAL_REF_UNSUPPORTED")
        requested_type = str(requested_resource_type or "").strip()
        requested_type = requested_type if requested_type in ACCOUNT_RESOURCE_TYPES else ""
        auth_resource_type = _expected_resource_type_for_auth_method(requested_auth_method)
        if requested_type and auth_resource_type and requested_type != auth_resource_type:
            raise ValueError(
                "AUTHORIZED_RESOURCE_TYPE_AUTH_METHOD_MISMATCH: "
                f"provider={provider_id} resource_type={requested_type} auth_method={requested_auth_method} "
                f"expected_resource_type={auth_resource_type}"
            )
        expected_resource_type = auth_resource_type or requested_type
        completion_resource_type = _expected_resource_type_for_auth_method(str(completion.get("auth_method") or ""))
        if expected_resource_type and completion_resource_type and completion_resource_type != expected_resource_type:
            raise ValueError(
                "AUTHORIZED_RESOURCE_AUTH_METHOD_RESOURCE_MISMATCH: "
                f"provider={provider_id} auth_method={completion.get('auth_method')} "
                f"expected_resource_type={expected_resource_type} actual_resource_type={completion_resource_type}"
            )
        credential_resource_type = _expected_resource_type_for_credential_ref(credential_ref)
        if expected_resource_type and credential_resource_type and credential_resource_type != expected_resource_type:
            raise ValueError(
                "AUTHORIZED_RESOURCE_CREDENTIAL_REF_RESOURCE_MISMATCH: "
                f"provider={provider_id} credential_ref_prefix={_credential_ref_prefix(credential_ref)} "
                f"expected_resource_type={expected_resource_type} actual_resource_type={credential_resource_type}"
            )

    def _normalize_completion_payload(self, session: models.ConnectorOAuthSession, payload: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
        stored_completion = self._stored_completion(session)
        account = self._first_dict(data, "account", "resource", "credential", "credentials", "session")
        credential_ref = (
            str(payload.get("credential_ref") or "").strip()
            or self._extract_credential_ref(data)
            or str(session.credential_ref or "").strip()
        )
        credential_value = (
            self._normalize_credential_value(payload.get("credential_value"))
            or self._extract_credential_value(data)
        )
        status = self._normalize_status(
            self._first(payload, "status", "state", "phase")
            or self._first(data, "status", "state", "phase")
            or self._first(account, "status", "state", "phase")
            or str(stored_completion.get("status") or "")
            or session.status
        )
        auth_method = self._normalize_auth_method(
            str(payload.get("auth_method") or "").strip()
            or self._first(data, "auth_method", "auth_type", "authentication", "credential_kind")
            or self._first(account, "auth_method", "auth_type", "authentication", "credential_kind")
            or str(stored_completion.get("auth_method") or "")
            or session.auth_method,
            credential_ref,
        )
        provider_base_url = (
            str(payload.get("provider_base_url") or "").strip()
            or self._first(data, "provider_base_url", "connector_base_url", "base_url")
            or self._first(account, "provider_base_url", "connector_base_url", "base_url")
            or str(stored_completion.get("provider_base_url") or "")
        )
        supported_operations = (
            self._first_list(payload, "supported_operations", "requested_operations", "operations")
            or self._first_list(data, "supported_operations", "requested_operations", "operations")
            or self._first_list(account, "supported_operations", "requested_operations", "operations")
            or self._first_list(stored_completion, "supported_operations", "requested_operations", "operations")
        )
        supported_provider_models = (
            self._first_list(payload, "supported_provider_models", "requested_provider_models", "provider_models", "models")
            or self._first_list(data, "supported_provider_models", "requested_provider_models", "provider_models", "models")
            or self._first_list(account, "supported_provider_models", "requested_provider_models", "provider_models", "models")
            or self._first_list(stored_completion, "supported_provider_models", "requested_provider_models", "provider_models", "models")
        )
        resource_profile = self._merge_resource_profiles(
            self._resource_profile(stored_completion),
            self._resource_profile(payload),
            self._resource_profile(data),
            self._resource_profile(account),
        )
        return {
            "status": status,
            "message": self._first(data, "message", "error", "error_message") or self._first(account, "message", "error", "error_message") or self._first(stored_completion, "message", "error", "error_message"),
            "credential_ref": credential_ref,
            "_credential_value": credential_value,
            "credential_value_provided": bool(credential_value),
            "auth_method": auth_method,
            "account_id": str(payload.get("account_id") or "").strip() or self._first(data, "account_id", "accountId") or self._first(account, "account_id", "accountId", "id") or str(stored_completion.get("account_id") or "").strip(),
            "label": str(payload.get("account_label") or payload.get("label") or "").strip() or self._first(data, "account_label", "label", "name") or self._first(account, "account_label", "label", "name") or self._first(stored_completion, "account_label", "label", "name"),
            "provider_base_url": provider_base_url,
            "connector_session_id": self._first(payload, "connector_session_id", "session_id") or self._first(data, "connector_session_id", "session_id", "id", "state") or self._first(account, "connector_session_id", "session_id") or self._first(stored_completion, "connector_session_id", "session_id"),
            "authorize_url": self._first(data, "authorize_url", "auth_url", "url", "login_url") or self._first(account, "authorize_url", "auth_url", "url", "login_url") or self._first(stored_completion, "authorize_url", "auth_url", "url", "login_url"),
            "supported_operations": supported_operations,
            "supported_provider_models": supported_provider_models,
            "resource_profile": resource_profile,
            "quota_buckets": self._quota_buckets(payload) or self._quota_buckets(data) or self._quota_buckets(account) or self._quota_buckets(stored_completion),
            "concurrency_limit": self._first_int(data, "concurrency_limit") or self._first_int(account, "concurrency_limit") or self._first_int(payload, "concurrency_limit") or self._first_int(stored_completion, "concurrency_limit"),
            "region": str(payload.get("region") or "").strip() or self._first(data, "region") or self._first(account, "region") or self._first(stored_completion, "region"),
            "plan": str(payload.get("plan") or "").strip() or self._first(data, "plan", "tier") or self._first(account, "plan", "tier") or self._first(stored_completion, "plan", "tier"),
        }

    def _normalize_status(self, status: str) -> str:
        value = str(status or "").strip().lower()
        if value in SUCCESS_STATUSES:
            return "completed"
        if value in FAILED_STATUSES:
            return "failed"
        return value or "pending"

    def _normalize_auth_method(self, auth_method: str, credential_ref: str) -> str:
        value = AUTH_METHOD_ALIASES.get(str(auth_method or "").strip().lower(), "")
        if value:
            return value
        for prefix, method in AUTH_METHOD_BY_REF_PREFIX.items():
            if credential_ref.startswith(prefix):
                return method
        return auth_method or "agent_provider_credential"

    def _first_dict(self, data: dict[str, Any], *keys: str) -> dict[str, Any]:
        for key in keys:
            value = data.get(key)
            if isinstance(value, dict):
                return value
        return {}

    def _first_list(self, data: dict[str, Any], *keys: str) -> list[Any]:
        for key in keys:
            value = data.get(key)
            if isinstance(value, list):
                return value
            if isinstance(value, str) and value.strip():
                return [item.strip() for item in value.split(",") if item.strip()]
        return []

    def _resource_profile(self, data: dict[str, Any]) -> dict[str, Any]:
        for key in ["resource_profile", "resourceProfile", "account_profile", "accountProfile"]:
            value = data.get(key)
            if isinstance(value, dict):
                return value
        return {}

    def _merge_resource_profiles(self, *profiles: dict[str, Any]) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        for profile in profiles:
            if not isinstance(profile, dict):
                continue
            for key, value in profile.items():
                if value not in (None, "", [], {}):
                    merged[key] = value
        return merged

    def _stored_completion(self, session: models.ConnectorOAuthSession) -> dict[str, Any]:
        metadata = loads(session.metadata_json, {})
        completion = metadata.get("completion") if isinstance(metadata, dict) else {}
        return completion if isinstance(completion, dict) else {}

    def _quota_buckets(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        value = data.get("quota_buckets") or data.get("quotas") or data.get("quota")
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            return [value]
        return []

    def _first_int(self, data: dict[str, Any], *keys: str) -> int | None:
        for key in keys:
            value = data.get(key)
            if value is None or value == "":
                continue
            try:
                return int(value)
            except (TypeError, ValueError):
                continue
        return None
