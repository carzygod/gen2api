from __future__ import annotations

import json
import secrets
from datetime import datetime
from typing import Any


SENSITIVE_KEY_PARTS = {"authorization", "api_key", "apikey", "cookie", "credential", "key", "password", "secret", "token"}


class DomainError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str | None = None,
        status_code: int = 400,
        retryable: bool = False,
        extra: dict[str, Any] | None = None,
    ):
        super().__init__(message or code)
        self.code = code
        self.message = message or code
        self.status_code = status_code
        self.retryable = retryable
        self.extra = extra or {}


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(12)}"


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def loads(value: str | None, default: Any = None) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.isoformat() + "Z"


def redact_sensitive(value: Any, max_depth: int = 6, max_string: int = 1000) -> Any:
    if max_depth <= 0:
        return "[truncated]"
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if is_sensitive_key(key_text):
                redacted[key_text] = "[redacted]"
            else:
                redacted[key_text] = redact_sensitive(item, max_depth=max_depth - 1, max_string=max_string)
        return redacted
    if isinstance(value, list):
        return [redact_sensitive(item, max_depth=max_depth - 1, max_string=max_string) for item in value[:100]]
    if isinstance(value, tuple):
        return [redact_sensitive(item, max_depth=max_depth - 1, max_string=max_string) for item in value[:100]]
    if isinstance(value, str):
        lowered = value.lower()
        if lowered.startswith(("bearer ", "sk-", "sess-", "eyj")):
            return "[redacted]"
        if len(value) > max_string:
            return value[:max_string] + "...[truncated]"
        return value
    return value


def is_sensitive_key(key: str) -> bool:
    lowered = key.lower().replace("-", "_")
    return any(part in lowered for part in SENSITIVE_KEY_PARTS)
