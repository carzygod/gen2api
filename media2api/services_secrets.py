from __future__ import annotations

import base64
from datetime import datetime
import hashlib
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from . import models
from .config import settings
from .utils import dumps, loads, new_id


ALLOWED_SECRET_KINDS = {
    "api_key",
    "bearer_token",
    "cookie",
    "cookie_secret",
    "custom",
    "subscription",
    "oauth_reference",
    "cli_credential",
    "agent_provider",
    "web_session",
    "mcp_config",
    "self_hosted_endpoint",
}
ALLOWED_SECRET_STATUSES = {"active", "disabled"}


class SecretService:
    def __init__(self) -> None:
        digest = hashlib.sha256(settings.secret_encryption_key.encode("utf-8")).digest()
        self.fernet = Fernet(base64.urlsafe_b64encode(digest))

    def create(
        self,
        db: Session,
        *,
        secret_id: str | None,
        name: str,
        value: str,
        kind: str = "api_key",
        provider_id: str = "",
        account_id: str = "",
        metadata: dict[str, Any] | None = None,
        status: str = "active",
        notes: str = "",
    ) -> models.CredentialSecret:
        self.validate(kind, status)
        item = models.CredentialSecret(
            id=secret_id or new_id("secret"),
            name=name,
            kind=kind,
            provider_id=provider_id,
            account_id=account_id,
            ciphertext=self.encrypt(value),
            fingerprint=self.fingerprint(value),
            preview=self.preview(value),
            metadata_json=dumps(metadata or {}),
            status=status,
            notes=notes,
        )
        db.add(item)
        db.flush()
        return item

    def update_value(self, secret: models.CredentialSecret, value: str) -> None:
        secret.ciphertext = self.encrypt(value)
        secret.fingerprint = self.fingerprint(value)
        secret.preview = self.preview(value)

    def resolve(self, db: Session, secret_id: str) -> str | None:
        secret = db.get(models.CredentialSecret, secret_id)
        if not secret or secret.status != "active":
            return None
        try:
            value = self.decrypt(secret.ciphertext)
        except InvalidToken:
            return None
        secret.last_used_at = datetime.utcnow()
        db.flush()
        return value

    def encrypt(self, value: str) -> str:
        return self.fernet.encrypt(value.encode("utf-8")).decode("ascii")

    def decrypt(self, ciphertext: str) -> str:
        return self.fernet.decrypt(ciphertext.encode("ascii")).decode("utf-8")

    def fingerprint(self, value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def preview(self, value: str) -> str:
        if len(value) <= 8:
            return "***"
        return f"{value[:4]}...{value[-4:]}"

    def validate(self, kind: str, status: str) -> None:
        if kind not in ALLOWED_SECRET_KINDS:
            raise ValueError("SECRET_KIND_INVALID")
        if status not in ALLOWED_SECRET_STATUSES:
            raise ValueError("SECRET_STATUS_INVALID")


def serialize_secret(secret: models.CredentialSecret) -> dict[str, Any]:
    return {
        "id": secret.id,
        "ref": f"secret://{secret.id}",
        "name": secret.name,
        "kind": secret.kind,
        "provider_id": secret.provider_id,
        "account_id": secret.account_id,
        "status": secret.status,
        "preview": secret.preview,
        "fingerprint": secret.fingerprint,
        "metadata": loads(secret.metadata_json, {}),
        "notes": secret.notes,
        "last_used_at": secret.last_used_at.isoformat() + "Z" if secret.last_used_at else None,
        "created_at": secret.created_at.isoformat() + "Z",
        "updated_at": secret.updated_at.isoformat() + "Z",
    }
