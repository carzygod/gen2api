from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timedelta
import time
from typing import Any

from sqlalchemy.orm import Session

from . import models
from .config import settings
from .utils import DomainError, dumps, loads, new_id


ACTIVE_JOB_STATUSES = {
    "created",
    "admitted",
    "queued",
    "leasing_account",
    "preparing_assets",
    "submitting",
    "provider_queued",
    "polling",
    "fetching_assets",
    "storing",
}
DEFAULT_REQUESTS_PER_MINUTE = 600
DEFAULT_DAILY_JOB_LIMIT = 10000
DEFAULT_CONCURRENT_JOB_LIMIT = 100

_request_windows: dict[str, deque[float]] = defaultdict(deque)
_redis_client: Any | None = None
_redis_failed = False
_redis_last_error = ""


class GovernanceService:
    def redis_status(self) -> dict[str, Any]:
        if not settings.redis_url:
            return {"configured": False, "status": "disabled", "error": ""}
        try:
            import redis

            client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
            client.ping()
            return {"configured": True, "status": "ok", "error": ""}
        except Exception as exc:
            return {"configured": True, "status": "failed", "error": exc.__class__.__name__}

    def policy_for_user(self, db: Session, user: models.User) -> models.UserLimitPolicy | None:
        policies = (
            db.query(models.UserLimitPolicy)
            .filter(models.UserLimitPolicy.enabled.is_(True))
            .all()
        )
        candidates: list[tuple[int, models.UserLimitPolicy]] = []
        for policy in policies:
            if policy.user_id and policy.user_id != user.id:
                continue
            if policy.tier and policy.tier != user.tier:
                continue
            score = int(bool(policy.user_id)) * 4 + int(bool(policy.tier)) * 2
            candidates.append((score, policy))
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1]

    def policy_snapshot(self, db: Session, user: models.User) -> dict[str, Any]:
        policy = self.policy_for_user(db, user)
        return {
            "policy_id": policy.id if policy else "runtime_default",
            "name": policy.name if policy else "Runtime default limits",
            "user_id": policy.user_id if policy else "",
            "tier": policy.tier if policy else "",
            "requests_per_minute": policy.requests_per_minute if policy else DEFAULT_REQUESTS_PER_MINUTE,
            "daily_job_limit": policy.daily_job_limit if policy else DEFAULT_DAILY_JOB_LIMIT,
            "concurrent_job_limit": policy.concurrent_job_limit if policy else DEFAULT_CONCURRENT_JOB_LIMIT,
            "allowed_models": loads(policy.allowed_models_json, []) if policy else [],
            "high_cost_models": loads(policy.high_cost_models_json, []) if policy else [],
            "high_cost_allowed": policy.high_cost_allowed if policy else True,
            "enabled": policy.enabled if policy else True,
        }

    def enforce_api_request(self, db: Session, user: models.User, api_key: models.ApiKey) -> None:
        policy = self.policy_for_user(db, user)
        limit = int(policy.requests_per_minute if policy else DEFAULT_REQUESTS_PER_MINUTE)
        if limit <= 0:
            return
        count = self._hit_rate_bucket(api_key.id, limit)
        if count > limit:
            raise DomainError("RATE_LIMITED", "API key request rate limit exceeded.", status_code=429, retryable=True)

    def enforce_job_create(
        self,
        db: Session,
        user_id: str,
        api_key_id: str,
        operation: str,
        logical_model: str,
        params: dict[str, Any],
        job_id: str = "",
    ) -> None:
        user = db.get(models.User, user_id)
        if not user:
            raise DomainError("USER_NOT_FOUND", status_code=404, extra={"job_id": job_id} if job_id else None)
        self._enforce_breaker(db, "user", user_id, job_id=job_id)
        self._enforce_breaker(db, "model", logical_model, job_id=job_id)

        policy = self.policy_for_user(db, user)
        snapshot = self.policy_snapshot(db, user)
        allowed_models = set(snapshot["allowed_models"])
        if allowed_models and logical_model not in allowed_models:
            raise DomainError(
                "MODEL_NOT_ALLOWED",
                f"Model {logical_model} is not enabled for this user policy.",
                status_code=403,
                retryable=False,
                extra={"job_id": job_id, "policy_id": snapshot["policy_id"]},
            )

        high_cost_models = set(snapshot["high_cost_models"])
        if high_cost_models and logical_model in high_cost_models and not snapshot["high_cost_allowed"]:
            raise DomainError(
                "MODEL_REQUIRES_WHITELIST",
                f"Model {logical_model} requires an allowlisted user policy.",
                status_code=403,
                retryable=False,
                extra={"job_id": job_id, "policy_id": snapshot["policy_id"]},
            )

        concurrent_limit = int(snapshot["concurrent_job_limit"])
        if concurrent_limit > 0:
            concurrent_count = (
                db.query(models.MediaJob)
                .filter(
                    models.MediaJob.user_id == user_id,
                    models.MediaJob.status.in_(ACTIVE_JOB_STATUSES),
                    models.MediaJob.id != job_id,
                )
                .count()
            )
            if concurrent_count >= concurrent_limit:
                raise DomainError(
                    "CONCURRENT_JOB_LIMIT_EXCEEDED",
                    "User concurrent media job limit exceeded.",
                    status_code=429,
                    retryable=True,
                    extra={"job_id": job_id, "policy_id": snapshot["policy_id"], "limit": concurrent_limit},
                )

        daily_limit = int(snapshot["daily_job_limit"])
        if daily_limit > 0:
            day_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            daily_count = (
                db.query(models.MediaJob)
                .filter(models.MediaJob.user_id == user_id, models.MediaJob.created_at >= day_start, models.MediaJob.id != job_id)
                .count()
            )
            if daily_count >= daily_limit:
                raise DomainError(
                    "DAILY_JOB_LIMIT_EXCEEDED",
                    "User daily media job limit exceeded.",
                    status_code=429,
                    retryable=True,
                    extra={"job_id": job_id, "policy_id": snapshot["policy_id"], "limit": daily_limit},
                )

    def filter_mappings(self, db: Session, mappings: list[models.ProviderModelMapping]) -> list[models.ProviderModelMapping]:
        return [mapping for mapping in mappings if not self.is_blocked(db, "provider", mapping.provider_id)]

    def account_available(self, db: Session, account: models.AccountResource) -> bool:
        return not self.is_blocked(db, "provider", account.provider_id) and not self.is_blocked(db, "account", account.id)

    def is_blocked(self, db: Session, scope: str, target_id: str) -> bool:
        return self.active_breaker(db, scope, target_id) is not None

    def active_breaker(self, db: Session, scope: str, target_id: str) -> models.CircuitBreaker | None:
        now = datetime.utcnow()
        breakers = (
            db.query(models.CircuitBreaker)
            .filter(
                models.CircuitBreaker.enabled.is_(True),
                models.CircuitBreaker.status == "open",
                models.CircuitBreaker.scope == scope,
                models.CircuitBreaker.target_id == target_id,
            )
            .order_by(models.CircuitBreaker.updated_at.desc())
            .all()
        )
        for breaker in breakers:
            if breaker.block_until is None or breaker.block_until > now:
                return breaker
            breaker.status = "closed"
        if breakers:
            db.flush()
        return None

    def observe_provider_error(
        self,
        db: Session,
        provider_id: str,
        account_id: str | None,
        error_code: str,
        message: str,
        job_id: str = "",
    ) -> models.CircuitBreaker | None:
        durations = {
            "RATE_LIMITED": timedelta(minutes=2),
            "PROVIDER_TIMEOUT": timedelta(minutes=5),
            "PROVIDER_CONFIG_INVALID": timedelta(minutes=30),
            "AUTH_REQUIRED": None,
            "QUOTA_EXHAUSTED": None,
            "INSUFFICIENT_QUOTA": None,
        }
        if error_code not in durations:
            return None
        if account_id:
            return self.open_breaker(
                db,
                scope="account",
                target_id=account_id,
                reason=message,
                error_code=error_code,
                block_for=durations[error_code],
                metadata={"provider_id": provider_id, "job_id": job_id},
            )
        return self.open_breaker(
            db,
            scope="provider",
            target_id=provider_id,
            reason=message,
            error_code=error_code,
            block_for=durations[error_code],
            metadata={"job_id": job_id},
        )

    def open_breaker(
        self,
        db: Session,
        scope: str,
        target_id: str,
        reason: str,
        error_code: str = "",
        block_for: timedelta | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> models.CircuitBreaker:
        breaker_id = f"cb_{scope}_{target_id}".replace(":", "_").replace("/", "_")
        breaker = db.get(models.CircuitBreaker, breaker_id)
        block_until = datetime.utcnow() + block_for if block_for else None
        if breaker:
            breaker.status = "open"
            breaker.reason = reason
            breaker.error_code = error_code
            breaker.block_until = block_until
            breaker.enabled = True
            breaker.metadata_json = dumps(metadata or {})
        else:
            breaker = models.CircuitBreaker(
                id=breaker_id,
                scope=scope,
                target_id=target_id,
                status="open",
                reason=reason,
                error_code=error_code,
                block_until=block_until,
                enabled=True,
                metadata_json=dumps(metadata or {}),
            )
            db.add(breaker)
        db.flush()
        return breaker

    def _enforce_breaker(self, db: Session, scope: str, target_id: str, job_id: str = "") -> None:
        breaker = self.active_breaker(db, scope, target_id)
        if not breaker:
            return
        raise DomainError(
            "CIRCUIT_OPEN",
            f"{scope} {target_id} is temporarily blocked: {breaker.reason or breaker.error_code}",
            status_code=429,
            retryable=True,
            extra={"job_id": job_id, "breaker_id": breaker.id, "scope": scope, "target_id": target_id},
        )

    def _hit_rate_bucket(self, api_key_id: str, limit: int) -> int:
        redis_client = self._redis()
        bucket = int(time.time() // 60)
        if redis_client is not None:
            try:
                key = f"media2api:rate:{api_key_id}:{bucket}"
                count = int(redis_client.incr(key))
                if count == 1:
                    redis_client.expire(key, 120)
                return count
            except Exception:
                pass

        now = time.time()
        window = _request_windows[api_key_id]
        while window and now - window[0] > 60:
            window.popleft()
        window.append(now)
        return len(window)

    def _redis(self) -> Any | None:
        global _redis_client, _redis_failed, _redis_last_error
        if _redis_failed or not settings.redis_url:
            return None
        if _redis_client is not None:
            return _redis_client
        try:
            import redis

            _redis_client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
            _redis_client.ping()
            _redis_last_error = ""
            return _redis_client
        except Exception as exc:
            _redis_failed = True
            _redis_last_error = exc.__class__.__name__
            return None
