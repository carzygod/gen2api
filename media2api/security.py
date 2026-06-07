from __future__ import annotations

import hashlib
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from . import models
from .database import get_db
from .services_governance import GovernanceService


governance_service = GovernanceService()


def hash_api_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass
class AuthContext:
    user: models.User
    api_key: models.ApiKey
    request_id: str


def is_admin_user(user: models.User | None) -> bool:
    return bool(user and user.status == "active" and (user.tier == "admin" or user.id == "usr_admin"))


def extract_api_key(authorization: str | None, x_api_key: str | None) -> str | None:
    if x_api_key:
        return x_api_key.strip()
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None


def require_auth(
    request: Request,
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> AuthContext:
    raw_key = extract_api_key(authorization, x_api_key) or request.cookies.get("media2api_admin_key")
    if not raw_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail={"error": "API_KEY_REQUIRED"})

    api_key = db.query(models.ApiKey).filter(models.ApiKey.key_hash == hash_api_key(raw_key)).first()
    if not api_key or api_key.status != "active":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail={"error": "INVALID_API_KEY"})
    user = db.get(models.User, api_key.user_id)
    if not user or user.status != "active":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"error": "USER_DISABLED"})

    governance_service.enforce_api_request(db, user, api_key)

    request_id = request.headers.get("x-request-id") or f"req_{hashlib.sha1(raw_key.encode()).hexdigest()[:12]}"
    return AuthContext(user=user, api_key=api_key, request_id=request_id)


def require_admin(ctx: AuthContext = Depends(require_auth)) -> AuthContext:
    if not is_admin_user(ctx.user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"error": "ADMIN_REQUIRED"})
    return ctx
