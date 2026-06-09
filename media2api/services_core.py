from __future__ import annotations

from datetime import datetime, timedelta
import math
import os
from typing import Any

from sqlalchemy import func, update
from sqlalchemy.orm import Session

from . import models
from .config import settings
from .providers import ProviderContext, get_provider
from .services_alerts import AlertService
from .services_governance import GovernanceService
from .services_models import ModelRegistryService
from .services_safety import SafetyService
from .services_webhooks import WebhookService
from .utils import DomainError, dumps, loads, new_id, redact_sensitive


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
TERMINAL_JOB_STATUSES = {"completed", "failed", "cancelled", "expired"}
ACTIVE_ATTEMPT_STATUSES = {"created", "submitting", "provider_queued", "polling", "fetching_assets", "storing"}
UNLEASED_STALLED_JOB_STATUSES = {"admitted", "leasing_account"}
PROVIDERS_WITH_VIRTUAL_CREDENTIALS = {"mock"}
EXTERNAL_REFERENCE_CREDENTIAL_PREFIXES = (
    "vault://",
    "subscription://",
    "oauth://",
    "cli://",
    "websession://",
    "agent://",
    "mcp://",
    "endpoint://",
    "connector://",
    "tokenref://",
)


def quota_bucket_matches(bucket: dict[str, Any], operation: str, provider_model: str) -> bool:
    operations = bucket.get("operations")
    if operations is None and bucket.get("operation"):
        operations = [bucket.get("operation")]
    if operations and operation not in [str(item) for item in operations]:
        return False
    models = bucket.get("provider_models")
    if models is None and bucket.get("provider_model"):
        models = [bucket.get("provider_model")]
    if models and provider_model not in [str(item) for item in models]:
        return False
    return True


def quota_remaining(bucket: dict[str, Any]) -> float | None:
    for key in ["remaining_estimate", "remaining", "credits_remaining"]:
        if key in bucket and bucket[key] is not None:
            try:
                return float(bucket[key])
            except (TypeError, ValueError):
                return None
    return None


def set_quota_remaining(bucket: dict[str, Any], value: float) -> None:
    key = "remaining_estimate"
    for candidate in ["remaining_estimate", "remaining", "credits_remaining"]:
        if candidate in bucket:
            key = candidate
            break
    bucket[key] = max(0, int(value) if value.is_integer() else value)


def quota_available_for_account(account: models.AccountResource, operation: str, provider_model: str) -> bool:
    buckets = loads(account.quota_buckets_json, [])
    if not buckets:
        return True
    matching = [bucket for bucket in buckets if isinstance(bucket, dict) and quota_bucket_matches(bucket, operation, provider_model)]
    if not matching:
        return False
    for bucket in matching:
        remaining = quota_remaining(bucket)
        if remaining is None or remaining > 0:
            return True
    return False


def consume_account_quota(account: models.AccountResource, operation: str, provider_model: str, amount: int) -> bool:
    if amount <= 0:
        return False
    buckets = loads(account.quota_buckets_json, [])
    matching = [bucket for bucket in buckets if isinstance(bucket, dict) and quota_bucket_matches(bucket, operation, provider_model)]
    for bucket in matching:
        remaining = quota_remaining(bucket)
        if remaining is None:
            continue
        if remaining > 0:
            set_quota_remaining(bucket, remaining - amount)
    account.quota_buckets_json = dumps(buckets)
    return True


def account_credential_available(db: Session, account: models.AccountResource) -> bool:
    if account.provider_id in PROVIDERS_WITH_VIRTUAL_CREDENTIALS:
        return True
    credential_ref = (account.credential_ref or "").strip()
    if credential_ref.startswith("public://"):
        return True
    if credential_ref.startswith(EXTERNAL_REFERENCE_CREDENTIAL_PREFIXES):
        return True
    if credential_ref.startswith("env://"):
        return bool(os.getenv(credential_ref.replace("env://", "", 1)))
    if credential_ref.startswith("secret://"):
        secret_id = credential_ref.replace("secret://", "", 1)
        secret = db.get(models.CredentialSecret, secret_id)
        return bool(secret and secret.status == "active")
    if credential_ref.startswith(("plain://", "bearer://")):
        return bool(credential_ref.split("://", 1)[1])
    return False


def preferred_account_ids_from_params(params: dict[str, Any] | None) -> list[str]:
    params = params or {}
    value = params.get("preferred_account_ids")
    if value is None:
        value = params.get("preferred_account_id")
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()]


class BillingService:
    def estimate(self, db: Session, operation: str, logical_model: str, params: dict[str, Any]) -> int:
        rule = self.pricing_rule(db, operation, logical_model)
        return self._amount_from_rule(rule, params, provider_cost=False)

    def enforce_cost_policy(self, job: models.MediaJob, params: dict[str, Any]) -> None:
        limit = self._cost_limit(params)
        if limit is None:
            return
        if job.cost_estimate > limit:
            raise DomainError(
                "COST_POLICY_REJECTED",
                f"Estimated cost {job.cost_estimate} exceeds max_cost={limit}.",
                status_code=402,
                retryable=False,
                extra={"job_id": job.id, "cost_estimate": job.cost_estimate, "max_cost": limit},
            )

    def provider_cost(self, db: Session, job: models.MediaJob) -> int:
        rule = self.pricing_rule(db, job.operation, job.logical_model)
        return self._amount_from_rule(rule, loads(job.normalized_params_json, {}), provider_cost=True)

    def pricing_rule(self, db: Session, operation: str, logical_model: str) -> models.PricingRule:
        logical = db.get(models.LogicalModel, logical_model)
        billing_class = logical.billing_class if logical else ""
        rules = db.query(models.PricingRule).filter(models.PricingRule.enabled.is_(True)).all()
        candidates: list[tuple[int, models.PricingRule]] = []
        for rule in rules:
            if rule.logical_model and rule.logical_model != logical_model:
                continue
            if rule.billing_class and rule.billing_class != billing_class:
                continue
            if rule.operation and rule.operation != operation:
                continue
            score = int(bool(rule.logical_model)) * 4 + int(bool(rule.operation)) * 2 + int(bool(rule.billing_class))
            candidates.append((score, rule))
        if not candidates:
            raise DomainError("PRICING_RULE_NOT_FOUND", f"No pricing rule for {logical_model}/{operation}", status_code=400)
        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1]

    def _amount_from_rule(self, rule: models.PricingRule, params: dict[str, Any], provider_cost: bool) -> int:
        units = self._billable_units(rule.unit, params)
        input_assets = self._input_asset_count(params)
        quality = str(params.get("quality") or "standard")
        multiplier = float(loads(rule.quality_multipliers_json, {}).get(quality, 1))
        if provider_cost:
            amount = rule.provider_cost_base + rule.provider_cost_unit * units + rule.provider_cost_input_asset * input_assets
        else:
            amount = rule.base_amount + rule.unit_amount * units + rule.input_asset_amount * input_assets
        return max(1, int(math.ceil(amount * multiplier)))

    def _billable_units(self, unit: str, params: dict[str, Any]) -> int:
        if unit == "second":
            return max(1, int(params.get("duration") or 1))
        if unit == "task":
            return 1
        return max(1, int(params.get("n") or 1))

    def _input_asset_count(self, params: dict[str, Any]) -> int:
        count = 0
        for key in ["image", "images", "assets", "first_frame", "last_frame", "mask", "video", "videos"]:
            value = params.get(key)
            if isinstance(value, list):
                count += len(value)
            elif value:
                count += 1
        return count

    def _cost_limit(self, params: dict[str, Any]) -> int | None:
        for key in ["max_cost", "max_credits", "budget", "budget_credits"]:
            value = params.get(key)
            if value is not None:
                return max(0, int(float(value)))
        policy = params.get("cost_policy")
        if isinstance(policy, dict):
            for key in ["max_cost", "max_credits", "budget", "budget_credits"]:
                value = policy.get(key)
                if value is not None:
                    return max(0, int(float(value)))
        if isinstance(policy, str):
            for prefix in ["max_cost:", "max_credits:", "budget:", "max:"]:
                if policy.startswith(prefix):
                    return max(0, int(float(policy.split(":", 1)[1].strip())))
        return None

    def hold(self, db: Session, job: models.MediaJob) -> models.BillingHold:
        user = db.get(models.User, job.user_id)
        if user is None:
            raise DomainError("USER_NOT_FOUND", status_code=404)
        if user.wallet_balance < job.cost_estimate:
            raise DomainError("INSUFFICIENT_BALANCE", "Insufficient wallet balance for estimated job cost.", status_code=402)
        user.wallet_balance -= job.cost_estimate
        hold = models.BillingHold(id=new_id("hold"), job_id=job.id, user_id=job.user_id, amount=job.cost_estimate, status="held")
        db.add(hold)
        db.flush()
        return hold

    def settle(self, db: Session, job: models.MediaJob, amount: int | None = None) -> None:
        amount = job.cost_estimate if amount is None else amount
        hold = db.query(models.BillingHold).filter(models.BillingHold.job_id == job.id, models.BillingHold.status == "held").first()
        if hold:
            if hold.amount > amount:
                user = db.get(models.User, job.user_id)
                if user:
                    user.wallet_balance += hold.amount - amount
            hold.status = "settled"
        job.final_cost = amount
        provider_cost = self.provider_cost(db, job)
        db.add(
            models.UsageRecord(
                id=new_id("usage"),
                job_id=job.id,
                user_id=job.user_id,
                operation=job.operation,
                logical_model=job.logical_model,
                provider_id=job.provider_id or "",
                amount=amount,
                status="settled",
            )
        )
        db.add(
            models.ProviderCostRecord(
                id=new_id("pcost"),
                job_id=job.id,
                user_id=job.user_id,
                operation=job.operation,
                logical_model=job.logical_model,
                provider_id=job.provider_id or "",
                provider_model=job.provider_model or "",
                amount=provider_cost,
                status="estimated",
            )
        )

    def refund(self, db: Session, job: models.MediaJob) -> None:
        hold = db.query(models.BillingHold).filter(models.BillingHold.job_id == job.id, models.BillingHold.status == "held").first()
        if hold:
            user = db.get(models.User, job.user_id)
            if user:
                user.wallet_balance += hold.amount
            hold.status = "refunded"
        job.final_cost = 0
        db.add(
            models.UsageRecord(
                id=new_id("usage"),
                job_id=job.id,
                user_id=job.user_id,
                operation=job.operation,
                logical_model=job.logical_model,
                provider_id=job.provider_id or "",
                amount=0,
                status="refunded",
            )
        )


class ModelRouter:
    def __init__(self) -> None:
        self.governance = GovernanceService()
        self._last_explanations: dict[str, dict[str, Any]] = {}

    def candidate_mappings(
        self,
        db: Session,
        logical_model: str,
        operation: str,
        params: dict[str, Any] | None = None,
    ) -> list[models.ProviderModelMapping]:
        params = params or {}
        mappings = (
            db.query(models.ProviderModelMapping)
            .join(models.Provider, models.Provider.id == models.ProviderModelMapping.provider_id)
            .filter(
                models.ProviderModelMapping.logical_model == logical_model,
                models.ProviderModelMapping.enabled.is_(True),
                models.Provider.status == "active",
            )
            .all()
        )
        mappings = [mapping for mapping in mappings if operation in loads(mapping.operations_json, [])]
        included = self._list_param(params, "providers") or self._list_param(params, "provider_ids")
        provider_models = self._list_param(params, "provider_models")
        if params.get("provider_model"):
            provider_models = [str(params["provider_model"])]
        preferred = self._list_param(params, "provider_preference") or self._list_param(params, "preferred_providers")
        if params.get("provider"):
            preferred = [str(params["provider"])]
        excluded = set(self._list_param(params, "excluded_providers"))
        preferred_account_ids = preferred_account_ids_from_params(params)
        if included:
            allowed = set(included)
            mappings = [mapping for mapping in mappings if mapping.provider_id in allowed]
        if provider_models:
            allowed_models = set(provider_models)
            mappings = [mapping for mapping in mappings if mapping.provider_model in allowed_models]
        if excluded:
            mappings = [mapping for mapping in mappings if mapping.provider_id not in excluded]
        mappings = self.governance.filter_mappings(db, mappings)
        mappings = [mapping for mapping in mappings if self._has_available_account(db, mapping, operation, preferred_account_ids)]

        policy = str(params.get("route_policy") or params.get("routing_strategy") or params.get("cost_policy") or "balanced")
        if policy not in {"balanced", "lowest_cost", "fastest", "best_quality"}:
            policy = "balanced"
        explanations = {mapping.id: self.explain_mapping(db, mapping, operation, policy, preferred, preferred_account_ids) for mapping in mappings}
        mappings.sort(key=lambda mapping: self._sort_key(mapping, policy, preferred, explanations.get(mapping.id, {})))
        self._last_explanations = explanations
        return mappings

    def choose_mapping(self, db: Session, logical_model: str, operation: str, params: dict[str, Any] | None = None) -> models.ProviderModelMapping:
        mappings = self.candidate_mappings(db, logical_model, operation, params)
        for mapping in mappings:
            return mapping
        raise RuntimeError("UNSUPPORTED_MODEL_OPERATION")

    def explain_mapping(
        self,
        db: Session,
        mapping: models.ProviderModelMapping,
        operation: str,
        policy: str,
        preferred: list[str] | None = None,
        preferred_account_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        preferred = preferred or []
        preference_rank = preferred.index(mapping.provider_id) if mapping.provider_id in preferred else len(preferred)
        success_rate = self._recent_success_rate(db, mapping.provider_id, mapping.provider_model)
        account_health, load_ratio, available_accounts = self._account_health_and_load(db, mapping, operation, preferred_account_ids or [])
        queue_length = self._provider_queue_length(db, mapping.provider_id)
        queue_penalty = min(0.5, queue_length / 20)
        dynamic_reliability = max(0.0, min(1.0, mapping.reliability_score * 0.45 + success_rate * 0.35 + account_health * 0.2 - queue_penalty))
        speed_effective = max(0.0, min(1.0, mapping.speed_score - min(0.4, load_ratio * 0.3) - queue_penalty))
        if policy == "lowest_cost":
            score = mapping.cost_score * 0.7 + dynamic_reliability * 0.2 + speed_effective * 0.1
        elif policy == "fastest":
            score = speed_effective * 0.65 + dynamic_reliability * 0.25 + mapping.cost_score * 0.1
        elif policy == "best_quality":
            score = mapping.quality_score * 0.65 + dynamic_reliability * 0.25 + speed_effective * 0.1
        else:
            score = dynamic_reliability * 0.4 + speed_effective * 0.25 + mapping.quality_score * 0.2 + mapping.cost_score * 0.15
        return {
            "policy": policy,
            "preference_rank": preference_rank,
            "score": round(score, 6),
            "recent_success_rate": round(success_rate, 6),
            "account_health": round(account_health, 6),
            "account_load_ratio": round(load_ratio, 6),
            "available_accounts": available_accounts,
            "provider_active_jobs": queue_length,
            "queue_penalty": round(queue_penalty, 6),
            "dynamic_reliability": round(dynamic_reliability, 6),
            "effective_speed": round(speed_effective, 6),
        }

    def explain_last(self, mapping: models.ProviderModelMapping) -> dict[str, Any]:
        return self._last_explanations.get(mapping.id, {})

    def _sort_key(self, mapping: models.ProviderModelMapping, policy: str, preferred: list[str], explanation: dict[str, Any]) -> tuple[float, ...]:
        preference_rank = preferred.index(mapping.provider_id) if mapping.provider_id in preferred else len(preferred)
        score = float(explanation.get("score") or 0)
        dynamic_reliability = float(explanation.get("dynamic_reliability") or mapping.reliability_score)
        effective_speed = float(explanation.get("effective_speed") or mapping.speed_score)
        if policy == "lowest_cost":
            return (preference_rank, -mapping.cost_score, mapping.priority, -dynamic_reliability, -effective_speed)
        if policy == "fastest":
            return (preference_rank, -effective_speed, mapping.priority, -dynamic_reliability, -mapping.cost_score)
        if policy == "best_quality":
            return (preference_rank, -mapping.quality_score, mapping.priority, -dynamic_reliability, -effective_speed)
        return (preference_rank, mapping.priority, -score)

    def _list_param(self, params: dict[str, Any], key: str) -> list[str]:
        value = params.get(key)
        if value is None:
            return []
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        if isinstance(value, list):
            return [str(item) for item in value if str(item)]
        return [str(value)]

    def _has_available_account(
        self,
        db: Session,
        mapping: models.ProviderModelMapping,
        operation: str,
        preferred_account_ids: list[str] | None = None,
    ) -> bool:
        query = db.query(models.AccountResource).filter(
            models.AccountResource.provider_id == mapping.provider_id,
            models.AccountResource.status == "active",
            models.AccountResource.current_leases < models.AccountResource.concurrency_limit,
        )
        if preferred_account_ids:
            query = query.filter(models.AccountResource.id.in_(preferred_account_ids))
        accounts = query.all()
        for account in accounts:
            if not self.governance.account_available(db, account):
                continue
            if not account_credential_available(db, account):
                continue
            if operation not in loads(account.supported_operations_json, []):
                continue
            if mapping.provider_model not in loads(account.supported_provider_models_json, []):
                continue
            if not quota_available_for_account(account, operation, mapping.provider_model):
                continue
            return True
        return False

    def _recent_success_rate(self, db: Session, provider_id: str, provider_model: str) -> float:
        cutoff = datetime.utcnow() - timedelta(hours=24)
        total = (
            db.query(func.count(models.MediaJobAttempt.id))
            .filter(
                models.MediaJobAttempt.provider_id == provider_id,
                models.MediaJobAttempt.provider_model == provider_model,
                models.MediaJobAttempt.created_at >= cutoff,
            )
            .scalar()
            or 0
        )
        if not total:
            return 0.5
        completed = (
            db.query(func.count(models.MediaJobAttempt.id))
            .filter(
                models.MediaJobAttempt.provider_id == provider_id,
                models.MediaJobAttempt.provider_model == provider_model,
                models.MediaJobAttempt.created_at >= cutoff,
                models.MediaJobAttempt.status == "completed",
            )
            .scalar()
            or 0
        )
        return float(completed) / float(total)

    def _account_health_and_load(
        self,
        db: Session,
        mapping: models.ProviderModelMapping,
        operation: str,
        preferred_account_ids: list[str] | None = None,
    ) -> tuple[float, float, int]:
        query = db.query(models.AccountResource).filter(models.AccountResource.provider_id == mapping.provider_id, models.AccountResource.status == "active")
        if preferred_account_ids:
            query = query.filter(models.AccountResource.id.in_(preferred_account_ids))
        accounts = query.all()
        eligible = []
        for account in accounts:
            if not self.governance.account_available(db, account):
                continue
            if not account_credential_available(db, account):
                continue
            if operation not in loads(account.supported_operations_json, []):
                continue
            if mapping.provider_model not in loads(account.supported_provider_models_json, []):
                continue
            eligible.append(account)
        if not eligible:
            return 0.0, 1.0, 0
        health = sum(account.health_score for account in eligible) / len(eligible)
        total_limit = sum(max(0, account.concurrency_limit) for account in eligible)
        total_leases = sum(max(0, account.current_leases) for account in eligible)
        load_ratio = 1.0 if total_limit <= 0 else min(1.0, total_leases / total_limit)
        available = sum(1 for account in eligible if account.current_leases < account.concurrency_limit and quota_available_for_account(account, operation, mapping.provider_model))
        return float(health), float(load_ratio), int(available)

    def _provider_queue_length(self, db: Session, provider_id: str) -> int:
        return int(
            db.query(func.count(models.MediaJob.id))
            .filter(models.MediaJob.provider_id == provider_id, models.MediaJob.status.in_(list(ACTIVE_JOB_STATUSES)))
            .scalar()
            or 0
        )


class AccountScheduler:
    def __init__(self) -> None:
        self.governance = GovernanceService()

    def acquire(
        self,
        db: Session,
        job_id: str,
        mapping: models.ProviderModelMapping,
        operation: str,
        preferred_account_ids: list[str] | None = None,
    ) -> models.AccountLease:
        accounts = self._eligible_accounts(db, mapping.provider_id, preferred_account_ids or [])
        if not accounts:
            if preferred_account_ids:
                for account_id in preferred_account_ids:
                    self.reconcile(db, provider_id=mapping.provider_id, account_id=account_id)
            else:
                self.reconcile(db, provider_id=mapping.provider_id)
            accounts = self._eligible_accounts(db, mapping.provider_id, preferred_account_ids or [])
        for account in accounts:
            if not self.governance.account_available(db, account):
                continue
            if not account_credential_available(db, account):
                continue
            if operation not in loads(account.supported_operations_json, []):
                continue
            if mapping.provider_model not in loads(account.supported_provider_models_json, []):
                continue
            if not quota_available_for_account(account, operation, mapping.provider_model):
                continue
            acquired = self._try_increment_lease(db, account.id)
            if not acquired:
                continue
            db.refresh(account)
            lease = models.AccountLease(
                id=new_id("lease"),
                job_id=job_id,
                account_id=account.id,
                provider_id=mapping.provider_id,
                provider_model=mapping.provider_model,
                expires_at=datetime.utcnow() + timedelta(minutes=30),
                status="active",
            )
            db.add(lease)
            db.flush()
            return lease
        raise RuntimeError("NO_ACCOUNT_AVAILABLE")

    def _try_increment_lease(self, db: Session, account_id: str) -> bool:
        result = db.execute(
            update(models.AccountResource)
            .where(
                models.AccountResource.id == account_id,
                models.AccountResource.status == "active",
                models.AccountResource.current_leases < models.AccountResource.concurrency_limit,
            )
            .values(
                current_leases=models.AccountResource.current_leases + 1,
                last_used_at=datetime.utcnow(),
            )
            .execution_options(synchronize_session=False)
        )
        return bool(result.rowcount)

    def _eligible_accounts(self, db: Session, provider_id: str, preferred_account_ids: list[str] | None = None) -> list[models.AccountResource]:
        query = db.query(models.AccountResource).filter(
            models.AccountResource.provider_id == provider_id,
            models.AccountResource.status == "active",
            models.AccountResource.current_leases < models.AccountResource.concurrency_limit,
        )
        if preferred_account_ids:
            query = query.filter(models.AccountResource.id.in_(preferred_account_ids))
        return query.order_by(models.AccountResource.health_score.desc(), models.AccountResource.failure_score.asc()).all()

    def active_lease_count(self, db: Session, account_id: str) -> int:
        return int(
            db.query(func.count(models.AccountLease.id))
            .filter(models.AccountLease.account_id == account_id, models.AccountLease.status == "active")
            .scalar()
            or 0
        )

    def sync_account_lease_count(self, db: Session, account_id: str) -> models.AccountResource | None:
        account = db.get(models.AccountResource, account_id)
        if not account:
            return None
        account.current_leases = self.active_lease_count(db, account_id)
        db.flush()
        return account

    def reconcile(self, db: Session, provider_id: str | None = None, account_id: str | None = None) -> dict[str, Any]:
        lease_query = (
            db.query(models.AccountLease)
            .join(models.MediaJob, models.MediaJob.id == models.AccountLease.job_id)
            .filter(models.AccountLease.status == "active", models.MediaJob.status.in_(TERMINAL_JOB_STATUSES))
        )
        if provider_id:
            lease_query = lease_query.filter(models.AccountLease.provider_id == provider_id)
        if account_id:
            lease_query = lease_query.filter(models.AccountLease.account_id == account_id)
        released_terminal_leases = 0
        for lease in lease_query.order_by(models.AccountLease.created_at.asc()).all():
            result = db.execute(
                update(models.AccountLease)
                .where(models.AccountLease.id == lease.id, models.AccountLease.status == "active")
                .values(status="released")
                .execution_options(synchronize_session=False)
            )
            if result.rowcount:
                lease.status = "released"
                released_terminal_leases += 1

        query = db.query(models.AccountResource)
        if provider_id:
            query = query.filter(models.AccountResource.provider_id == provider_id)
        if account_id:
            query = query.filter(models.AccountResource.id == account_id)
        checked = 0
        updated = 0
        accounts: list[dict[str, Any]] = []
        for account in query.order_by(models.AccountResource.provider_id, models.AccountResource.id).all():
            checked += 1
            before = int(account.current_leases or 0)
            actual = self.active_lease_count(db, account.id)
            if before != actual:
                account.current_leases = actual
                updated += 1
                accounts.append({"id": account.id, "provider_id": account.provider_id, "before": before, "after": actual})
        if updated or released_terminal_leases:
            db.commit()
        return {"checked": checked, "updated": updated, "released_terminal_leases": released_terminal_leases, "accounts": accounts}

    def release(
        self,
        db: Session,
        lease: models.AccountLease | None,
        success: bool,
        error_code: str | None = None,
        error_message: str | None = None,
        operation: str | None = None,
        quota_amount: int = 0,
        neutral: bool = False,
    ) -> models.AccountResource | None:
        if not lease or lease.status != "active":
            return None
        result = db.execute(
            update(models.AccountLease)
            .where(models.AccountLease.id == lease.id, models.AccountLease.status == "active")
            .values(status="released")
            .execution_options(synchronize_session=False)
        )
        if not result.rowcount:
            return None
        lease.status = "released"
        account = self.sync_account_lease_count(db, lease.account_id)
        if account:
            previous_status = account.status
            if neutral:
                pass
            elif success:
                if operation:
                    consume_account_quota(account, operation, lease.provider_model, quota_amount)
                account.health_score = min(1.0, account.health_score + 0.01)
                account.failure_score = max(0.0, account.failure_score - 0.05)
                account.last_error_code = ""
                account.last_error_message = ""
                account.last_failed_at = None
                if operation and not quota_available_for_account(account, operation, lease.provider_model):
                    account.status = "quota_exhausted"
                    account.last_error_code = "QUOTA_EXHAUSTED"
                    account.last_error_message = "Account quota exhausted after successful job settlement."
                elif account.status in {"rate_limited", "cooldown"} and account.failure_score < 0.25:
                    account.status = "active"
            else:
                account.failure_score = min(1.0, account.failure_score + 0.2)
                account.health_score = max(0.0, account.health_score - 0.1)
                account.last_error_code = error_code or "PROVIDER_FAILED"
                account.last_error_message = error_message or error_code or "Provider attempt failed."
                account.last_failed_at = datetime.utcnow()
                if error_code == "RATE_LIMITED":
                    account.status = "rate_limited"
                elif error_code == "AUTH_REQUIRED":
                    account.status = "auth_required"
                elif error_code in {"QUOTA_EXHAUSTED", "INSUFFICIENT_QUOTA"}:
                    account.status = "quota_exhausted"
                elif account.failure_score >= 0.75:
                    account.status = "cooldown"
            if account.status != previous_status:
                return account
        return account

    def release_expired(self, db: Session) -> int:
        leases = (
            db.query(models.AccountLease)
            .filter(models.AccountLease.status == "active", models.AccountLease.expires_at < datetime.utcnow())
            .all()
        )
        count = 0
        for lease in leases:
            result = db.execute(
                update(models.AccountLease)
                .where(models.AccountLease.id == lease.id, models.AccountLease.status == "active")
                .values(status="expired")
                .execution_options(synchronize_session=False)
            )
            if not result.rowcount:
                continue
            lease.status = "expired"
            account = self.sync_account_lease_count(db, lease.account_id)
            if account:
                account.failure_score = min(1.0, account.failure_score + 0.05)
                account.last_error_code = "LEASE_EXPIRED"
                account.last_error_message = "Account lease expired before job completed."
                account.last_failed_at = datetime.utcnow()
            count += 1
        if count:
            db.commit()
        return count


class JobRuntime:
    def __init__(self) -> None:
        self.billing = BillingService()
        self.router = ModelRouter()
        self.scheduler = AccountScheduler()
        self.alerts = AlertService()
        self.governance = GovernanceService()
        self.models = ModelRegistryService()
        self.safety = SafetyService()
        self.webhooks = WebhookService()

    def next_queued_job(self, db: Session) -> models.MediaJob | None:
        for _ in range(20):
            row = (
                db.query(models.MediaJob.id)
                .filter(models.MediaJob.status == "queued")
                .order_by(models.MediaJob.priority.asc(), models.MediaJob.created_at.asc())
                .first()
            )
            if not row:
                return None
            job_id = row[0]
            if not self.claim_queued_job(db, job_id):
                db.expire_all()
                continue
            job = db.get(models.MediaJob, job_id)
            if not job:
                db.rollback()
                continue
            self.record_event(db, job, "admitted", "Job admitted by worker.")
            db.commit()
            return job
        return None

    def claim_queued_job(self, db: Session, job_id: str) -> bool:
        result = db.execute(
            update(models.MediaJob)
            .where(models.MediaJob.id == job_id, models.MediaJob.status == "queued")
            .values(status="admitted", updated_at=datetime.utcnow())
            .execution_options(synchronize_session=False)
        )
        return bool(result.rowcount)

    def runtime_counts(self, db: Session) -> dict[str, int]:
        statuses = [
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
            "completed",
            "failed",
            "cancelled",
            "expired",
        ]
        return {status: db.query(models.MediaJob).filter(models.MediaJob.status == status).count() for status in statuses}

    def recover_stalled_jobs(self, db: Session, max_age_seconds: int | None = None, limit: int = 100, job_id: str | None = None) -> dict[str, Any]:
        max_age = max(1, int(max_age_seconds or settings.worker_stalled_job_seconds))
        cutoff = datetime.utcnow() - timedelta(seconds=max_age)
        query = db.query(models.MediaJob).filter(
            models.MediaJob.status.in_(list(UNLEASED_STALLED_JOB_STATUSES)),
            models.MediaJob.updated_at < cutoff,
        )
        if job_id:
            query = query.filter(models.MediaJob.id == job_id)
        jobs = query.order_by(models.MediaJob.updated_at.asc()).limit(max(1, min(int(limit or 100), 1000))).all()
        recovered: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        for job in jobs:
            active_lease = (
                db.query(models.AccountLease)
                .filter(models.AccountLease.job_id == job.id, models.AccountLease.status == "active")
                .order_by(models.AccountLease.created_at.desc())
                .first()
            )
            if active_lease:
                skipped.append({"job_id": job.id, "status": job.status, "reason": "active_lease", "lease_id": active_lease.id})
                continue
            active_attempt = (
                db.query(models.MediaJobAttempt)
                .filter(models.MediaJobAttempt.job_id == job.id, models.MediaJobAttempt.status.in_(list(ACTIVE_ATTEMPT_STATUSES)))
                .order_by(models.MediaJobAttempt.created_at.desc())
                .first()
            )
            if active_attempt:
                skipped.append({"job_id": job.id, "status": job.status, "reason": "active_attempt", "attempt_id": active_attempt.id})
                continue
            previous = {
                "status": job.status,
                "provider_id": job.provider_id or "",
                "provider_model": job.provider_model or "",
                "account_id": job.account_id or "",
                "provider_task_id": job.provider_task_id or "",
                "updated_at": job.updated_at.isoformat() + "Z" if job.updated_at else None,
            }
            job.status = "queued"
            job.provider_id = None
            job.provider_model = None
            job.account_id = None
            job.provider_task_id = None
            job.error_code = None
            job.error_message = None
            self.record_event(
                db,
                job,
                "stalled_job_requeued",
                "Stalled unleased job recovered and returned to the queue.",
                metadata={"previous": previous, "max_age_seconds": max_age},
            )
            recovered.append({"job_id": job.id, "previous_status": previous["status"], "new_status": job.status})
        if recovered:
            db.commit()
        return {"checked": len(jobs), "recovered": len(recovered), "skipped": skipped, "jobs": recovered, "max_age_seconds": max_age, "job_id": job_id or ""}

    def sweep_expired_leases(self, db: Session) -> int:
        leases = (
            db.query(models.AccountLease)
            .filter(models.AccountLease.status == "active", models.AccountLease.expires_at < datetime.utcnow())
            .order_by(models.AccountLease.expires_at.asc())
            .all()
        )
        expired = 0
        for lease in leases:
            result = db.execute(
                update(models.AccountLease)
                .where(models.AccountLease.id == lease.id, models.AccountLease.status == "active")
                .values(status="expired")
                .execution_options(synchronize_session=False)
            )
            if not result.rowcount:
                continue
            lease.status = "expired"
            account = self.scheduler.sync_account_lease_count(db, lease.account_id)
            if account:
                account.failure_score = min(1.0, account.failure_score + 0.05)
                account.last_error_code = "LEASE_EXPIRED"
                account.last_error_message = "Account lease expired before provider attempt completed."
                account.last_failed_at = datetime.utcnow()

            job = db.get(models.MediaJob, lease.job_id)
            attempt = (
                db.query(models.MediaJobAttempt)
                .filter(
                    models.MediaJobAttempt.job_id == lease.job_id,
                    models.MediaJobAttempt.account_id == lease.account_id,
                    models.MediaJobAttempt.status.in_(list(ACTIVE_ATTEMPT_STATUSES)),
                )
                .order_by(models.MediaJobAttempt.created_at.desc())
                .first()
            )
            if attempt:
                attempt.status = "expired"
                attempt.error_code = "LEASE_EXPIRED"
                attempt.error_message = "Account lease expired before provider attempt completed."
                attempt.raw_status = attempt.raw_status or "lease_expired"
                attempt.raw_response_json = dumps(redact_sensitive({"error_code": "LEASE_EXPIRED", "lease_id": lease.id}))
                attempt.finished_at = datetime.utcnow()

            if job and job.status not in TERMINAL_JOB_STATUSES:
                job.status = "expired"
                job.error_code = "LEASE_EXPIRED"
                job.error_message = "Account lease expired before job completed; retry the job to resubmit."
                self.record_event(
                    db,
                    job,
                    "lease_expired",
                    job.error_message,
                    attempt_id=attempt.id if attempt else "",
                    metadata={"lease_id": lease.id, "account_id": lease.account_id, "provider_model": lease.provider_model},
                )
                self.billing.refund(db, job)
                self.alerts.job_failed(db, job)
                self.alerts.detect_usage_anomalies(db, job)
                self.webhooks.maybe_deliver(db, job)
            expired += 1

        if expired:
            db.commit()
        return expired

    def record_event(
        self,
        db: Session,
        job: models.MediaJob,
        event_type: str,
        message: str = "",
        attempt_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> models.MediaJobEvent:
        event = models.MediaJobEvent(
            id=new_id("jevt"),
            job_id=job.id,
            user_id=job.user_id,
            event_type=event_type,
            status=job.status,
            provider_id=job.provider_id or "",
            account_id=job.account_id or "",
            attempt_id=attempt_id,
            message=message,
            metadata_json=dumps(metadata or {}),
        )
        db.add(event)
        db.flush()
        return event

    def adjust_mapping_reliability(
        self,
        db: Session,
        job: models.MediaJob,
        mapping: models.ProviderModelMapping,
        success: bool,
        attempt_id: str = "",
        error_code: str | None = None,
        retryable: bool | None = None,
    ) -> None:
        before = float(mapping.reliability_score or 0.0)
        if success:
            delta = 0.02
            reason = "success_recovery"
        else:
            code = error_code or "PROVIDER_FAILED"
            reason = code.lower()
            if code in {"AUTH_REQUIRED", "PROVIDER_CONFIG_INVALID"}:
                delta = -0.18
            elif code in {"QUOTA_EXHAUSTED", "INSUFFICIENT_QUOTA"}:
                delta = -0.14
            elif code == "RATE_LIMITED":
                delta = -0.08
            elif retryable is False:
                delta = -0.10
            else:
                delta = -0.05
        after = max(0.05, min(1.0, before + delta))
        if math.isclose(before, after, abs_tol=0.000001):
            return
        mapping.reliability_score = round(after, 6)
        self.record_event(
            db,
            job,
            "mapping_reliability_adjusted",
            f"Mapping reliability {'recovered' if success else 'degraded'} for {mapping.provider_id}/{mapping.provider_model}.",
            attempt_id=attempt_id,
            metadata={
                "mapping_id": mapping.id,
                "provider_id": mapping.provider_id,
                "provider_model": mapping.provider_model,
                "success": success,
                "reason": reason,
                "error_code": error_code or "",
                "retryable": retryable,
                "previous_reliability_score": round(before, 6),
                "reliability_score": mapping.reliability_score,
                "delta": round(mapping.reliability_score - before, 6),
            },
        )

    def create_job(
        self,
        db: Session,
        user_id: str,
        api_key_id: str,
        operation: str,
        logical_model: str,
        params: dict[str, Any],
        input_asset_ids: list[str] | None = None,
        priority: int = 100,
        enqueue: bool = True,
    ) -> models.MediaJob:
        _, params = self.models.normalize_and_validate(db, logical_model, operation, params)
        cost = self.billing.estimate(db, operation, logical_model, params)
        job = models.MediaJob(
            id=new_id("job"),
            user_id=user_id,
            api_key_id=api_key_id,
            operation=operation,
            logical_model=logical_model,
            normalized_params_json=dumps(params),
            input_asset_ids_json=dumps(input_asset_ids or []),
            output_asset_ids_json=dumps([]),
            status="created",
            priority=priority,
            cost_estimate=cost,
        )
        db.add(job)
        db.flush()
        self.record_event(db, job, "created", "Media job created.", metadata={"operation": operation, "logical_model": logical_model})
        try:
            self.billing.enforce_cost_policy(job, params)
        except DomainError as exc:
            job.status = "failed"
            job.error_code = exc.code
            job.error_message = exc.message
            job.final_cost = 0
            self.record_event(db, job, "cost_policy_rejected", exc.message, metadata={"error_code": exc.code, **exc.extra})
            db.commit()
            raise
        try:
            self.governance.enforce_job_create(db, user_id, api_key_id, operation, logical_model, params, job_id=job.id)
        except DomainError as exc:
            job.status = "failed"
            job.error_code = exc.code
            job.error_message = exc.message
            job.final_cost = 0
            self.record_event(db, job, "governance_rejected", exc.message, metadata={"error_code": exc.code, **exc.extra})
            db.commit()
            raise
        try:
            self.safety.evaluate(db, user_id, api_key_id, operation, logical_model, params, job_id=job.id)
        except DomainError as exc:
            job.status = "failed"
            job.error_code = exc.code
            job.error_message = exc.message
            job.final_cost = 0
            self.record_event(db, job, "safety_rejected", exc.message, metadata={"error_code": exc.code, **exc.extra})
            db.commit()
            raise
        self.billing.hold(db, job)
        self.record_event(db, job, "billing_held", "Estimated cost held.", metadata={"amount": job.cost_estimate})
        if enqueue:
            job.status = "queued"
            self.record_event(db, job, "queued", "Job queued for execution.")
        else:
            self.record_event(db, job, "sync_processing_locked", "Job held for synchronous processing.")
        db.commit()
        return job

    def process_job(self, db: Session, job_id: str) -> models.MediaJob:
        job = db.get(models.MediaJob, job_id)
        if not job:
            raise RuntimeError("JOB_NOT_FOUND")
        params = loads(job.normalized_params_json, {})
        sync_process_lock = bool(params.get("_sync_process_lock") or params.get("_self_test_sync"))
        try:
            _, params = self.models.normalize_and_validate(db, job.logical_model, job.operation, params)
            job.normalized_params_json = dumps(params)
            sync_process_lock = bool(params.get("_sync_process_lock") or params.get("_self_test_sync"))
        except DomainError as exc:
            job.status = "failed"
            job.error_code = exc.code
            job.error_message = exc.message
            self.record_event(db, job, "model_rejected", exc.message, metadata={"error_code": exc.code})
            self.billing.refund(db, job)
            self.webhooks.maybe_deliver(db, job)
            db.commit()
            return job
        try:
            self.governance.enforce_job_create(db, job.user_id, job.api_key_id, job.operation, job.logical_model, params, job_id=job.id)
        except DomainError as exc:
            job.status = "failed"
            job.error_code = exc.code
            job.error_message = exc.message
            self.record_event(db, job, "governance_rejected", exc.message, metadata={"error_code": exc.code, **exc.extra})
            self.billing.refund(db, job)
            self.webhooks.maybe_deliver(db, job)
            db.commit()
            return job
        try:
            self.safety.evaluate(db, job.user_id, job.api_key_id, job.operation, job.logical_model, params, job_id=job.id)
        except DomainError as exc:
            job.status = "failed"
            job.error_code = exc.code
            job.error_message = exc.message
            self.record_event(db, job, "safety_rejected", exc.message, metadata={"error_code": exc.code, **exc.extra})
            self.billing.refund(db, job)
            self.webhooks.maybe_deliver(db, job)
            db.commit()
            return job
        mappings = self.router.candidate_mappings(db, job.logical_model, job.operation, params)
        if not mappings:
            job.status = "failed"
            job.error_code = "UNSUPPORTED_MODEL_OPERATION"
            job.error_message = f"No active provider mapping for {job.logical_model}/{job.operation}"
            self.record_event(db, job, "routing_failed", job.error_message, metadata={"error_code": job.error_code})
            self.billing.refund(db, job)
            db.commit()
            return job

        preferred_account_ids = preferred_account_ids_from_params(params)
        last_error: dict[str, Any] | None = None
        for mapping in mappings:
            lease = None
            attempt = None
            provider = get_provider(mapping.provider_id)
            try:
                job.status = "leasing_account"
                job.provider_id = mapping.provider_id
                job.provider_model = mapping.provider_model
                job.account_id = None
                job.provider_task_id = None
                self.record_event(
                    db,
                    job,
                    "provider_selected",
                    f"Selected provider {mapping.provider_id}/{mapping.provider_model}.",
                    metadata={"provider_model": mapping.provider_model},
                )
                db.commit()

                lease = self.scheduler.acquire(db, job.id, mapping, job.operation, preferred_account_ids)
                job.account_id = lease.account_id
                self.record_event(db, job, "account_leased", f"Leased account {lease.account_id}.", metadata={"lease_id": lease.id})
                job.status = "preparing_assets"
                self.record_event(db, job, "preparing_assets", "Preparing platform assets for provider submit.")
                job.status = "submitting"
                attempt = models.MediaJobAttempt(
                    id=new_id("attempt"),
                    job_id=job.id,
                    provider_id=mapping.provider_id,
                    account_id=lease.account_id,
                    provider_model=mapping.provider_model,
                    status="submitting",
                    started_at=datetime.utcnow(),
                    request_snapshot_json=dumps(
                        redact_sensitive(
                            {
                                "operation": job.operation,
                                "logical_model": job.logical_model,
                                "provider_id": mapping.provider_id,
                                "provider_model": mapping.provider_model,
                                "params": loads(job.normalized_params_json, {}),
                                "input_asset_ids": loads(job.input_asset_ids_json, []),
                            }
                        )
                    ),
                )
                db.add(attempt)
                db.flush()
                self.record_event(db, job, "attempt_started", "Provider attempt started.", attempt_id=attempt.id)
                db.commit()

                account = db.get(models.AccountResource, lease.account_id)
                ctx = ProviderContext(provider_id=mapping.provider_id, provider_model=mapping.provider_model, account=account, user_id=job.user_id)
                result = provider.submit(db, ctx, job)
                db.refresh(job)
                db.refresh(lease)
                if job.status == "cancelled":
                    if attempt:
                        attempt.status = "cancelled"
                        attempt.error_code = "CANCELLED"
                        attempt.error_message = "Provider result was discarded because the job was cancelled."
                        attempt.raw_response_json = dumps(redact_sensitive({"discarded_provider_result": result.raw_response or result.raw_status}))
                        attempt.finished_at = datetime.utcnow()
                    self.scheduler.release(db, lease, success=False, error_code="CANCELLED", neutral=True)
                    self.record_event(db, job, "provider_result_discarded", "Provider result discarded after cancellation.", attempt_id=attempt.id if attempt else "")
                    db.commit()
                    return job
                job.provider_task_id = result.provider_task_id
                job.status = "storing"
                attempt.provider_task_id = result.provider_task_id
                attempt.raw_status = result.raw_status
                attempt.raw_response_json = dumps(
                    redact_sensitive(
                        result.raw_response
                        or {
                            "status": result.status,
                            "raw_status": result.raw_status,
                            "provider_task_id": result.provider_task_id,
                            "asset_ids": [asset.id for asset in result.assets],
                        }
                    )
                )
                self.record_event(
                    db,
                    job,
                    "provider_completed",
                    "Provider returned a completed result.",
                    attempt_id=attempt.id,
                    metadata={"provider_task_id": result.provider_task_id, "raw_status": result.raw_status},
                )
                output_ids = [asset.id for asset in result.assets]
                job.output_asset_ids_json = dumps(output_ids)
                job.status = "completed"
                job.error_code = None
                job.error_message = None
                attempt.status = "completed"
                attempt.finished_at = datetime.utcnow()
                provider_cost = self.billing.provider_cost(db, job)
                self.billing.settle(db, job)
                account_after_release = self.scheduler.release(db, lease, success=True, operation=job.operation, quota_amount=provider_cost)
                if account_after_release and account_after_release.status == "quota_exhausted":
                    self.alerts.account_status_changed(db, account_after_release, "active", account_after_release.last_error_message)
                self.adjust_mapping_reliability(db, job, mapping, success=True, attempt_id=attempt.id)
                self.record_event(db, job, "completed", "Media job completed.", attempt_id=attempt.id, metadata={"output_asset_ids": output_ids, "final_cost": job.final_cost})
                self.alerts.high_cost_job(db, job)
                self.alerts.detect_usage_anomalies(db, job)
                self.webhooks.maybe_deliver(db, job)
                db.commit()
                return job
            except Exception as exc:
                classified = provider.classify_error(exc)
                retryable = classified.get("retryable")
                retryable_flag = retryable if isinstance(retryable, bool) else None
                last_error = classified
                if attempt:
                    attempt.status = "failed"
                    attempt.error_code = str(classified.get("code") or "PROVIDER_FAILED")
                    attempt.error_message = str(classified.get("message") or exc)
                    attempt.raw_response_json = dumps(redact_sensitive({"error": classified, "message": str(exc)}))
                    attempt.finished_at = datetime.utcnow()
                    self.record_event(
                        db,
                        job,
                        "attempt_failed",
                        attempt.error_message or attempt.error_code or "Provider attempt failed.",
                        attempt_id=attempt.id,
                        metadata={"error_code": attempt.error_code, "retryable": classified.get("retryable")},
                    )
                    self.adjust_mapping_reliability(
                        db,
                        job,
                        mapping,
                        success=False,
                        attempt_id=attempt.id,
                        error_code=attempt.error_code,
                        retryable=retryable_flag,
                    )
                breaker = self.governance.observe_provider_error(
                    db,
                    mapping.provider_id,
                    lease.account_id if lease else None,
                    str(classified.get("code") or "PROVIDER_FAILED"),
                    str(classified.get("message") or exc),
                    job_id=job.id,
                )
                if breaker:
                    self.alerts.trigger(
                        db=db,
                        event_type="circuit_open",
                        title=f"Circuit opened for {breaker.scope} {breaker.target_id}",
                        message=breaker.reason,
                        dimensions={"scope": breaker.scope, "target_id": breaker.target_id, "error_code": breaker.error_code},
                        user_id=job.user_id,
                        job_id=job.id,
                        provider_id=mapping.provider_id,
                        account_id=lease.account_id if lease else "",
                    )
                account_after_release = self.scheduler.release(
                    db,
                    lease,
                    success=False,
                    error_code=str(classified.get("code") or "PROVIDER_FAILED"),
                    error_message=str(classified.get("message") or exc),
                )
                if account_after_release:
                    self.alerts.account_status_changed(db, account_after_release, "active", str(classified.get("message") or exc))
                job.status = "created" if sync_process_lock else "queued"
                job.error_code = str(classified.get("code") or "PROVIDER_FAILED")
                job.error_message = str(classified.get("message") or exc)
                self.record_event(db, job, "fallback_queued", job.error_message or "Attempt failed; trying next candidate.", metadata={"error_code": job.error_code})
                db.commit()
                if str(classified.get("code") or "") in {"INVALID_INPUT", "SAFETY_REJECTED"}:
                    break

        job.status = "failed"
        job.error_code = str((last_error or {}).get("code") or "PROVIDER_FAILED")
        job.error_message = str((last_error or {}).get("message") or "All provider attempts failed")
        self.billing.refund(db, job)
        self.record_event(db, job, "failed", job.error_message or "Media job failed.", metadata={"error_code": job.error_code})
        self.alerts.job_failed(db, job)
        self.alerts.detect_usage_anomalies(db, job)
        self.webhooks.maybe_deliver(db, job)
        db.commit()
        return job

    def cancel_job(self, db: Session, job_id: str) -> models.MediaJob:
        job = db.get(models.MediaJob, job_id)
        if not job:
            raise RuntimeError("JOB_NOT_FOUND")
        if job.status in TERMINAL_JOB_STATUSES:
            return job
        lease = (
            db.query(models.AccountLease)
            .filter(models.AccountLease.job_id == job.id, models.AccountLease.status == "active")
            .order_by(models.AccountLease.created_at.desc())
            .first()
        )
        attempt = (
            db.query(models.MediaJobAttempt)
            .filter(models.MediaJobAttempt.job_id == job.id, models.MediaJobAttempt.status.in_(list(ACTIVE_ATTEMPT_STATUSES)))
            .order_by(models.MediaJobAttempt.created_at.desc())
            .first()
        )
        provider_cancel: dict[str, Any] = {"status": "not_needed", "message": "job was not submitted to provider"}
        if job.provider_id and job.provider_task_id and lease:
            account = db.get(models.AccountResource, lease.account_id)
            if account:
                provider = get_provider(job.provider_id)
                ctx = ProviderContext(provider_id=job.provider_id, provider_model=job.provider_model or "", account=account, user_id=job.user_id)
                try:
                    provider_cancel = provider.cancel(db, ctx, job.provider_task_id)
                except Exception as exc:
                    provider_cancel = {"status": "failed", "message": str(exc), "provider_task_id": job.provider_task_id}
                    self.record_event(db, job, "provider_cancel_failed", str(exc), attempt_id=attempt.id if attempt else "")
        if attempt:
            attempt.status = "cancelled"
            attempt.error_code = "CANCELLED"
            attempt.error_message = "Media job cancelled by user or administrator."
            attempt.raw_response_json = dumps(redact_sensitive({"provider_cancel": provider_cancel}))
            attempt.finished_at = datetime.utcnow()
        job.status = "cancelled"
        job.error_code = "CANCELLED"
        job.error_message = "Media job cancelled."
        if lease:
            self.scheduler.release(db, lease, success=False, error_code="CANCELLED", neutral=True)
        self.billing.refund(db, job)
        self.record_event(
            db,
            job,
            "cancelled",
            "Media job cancelled.",
            attempt_id=attempt.id if attempt else "",
            metadata={"provider_cancel": provider_cancel, "lease_id": lease.id if lease else ""},
        )
        self.webhooks.maybe_deliver(db, job)
        db.commit()
        return job

    def retry_job(self, db: Session, job_id: str, priority: int | None = None) -> models.MediaJob:
        job = db.get(models.MediaJob, job_id)
        if not job:
            raise DomainError("JOB_NOT_FOUND", status_code=404)
        if job.status not in {"failed", "cancelled", "expired"}:
            raise DomainError("JOB_NOT_RETRYABLE", "Only failed, cancelled, or expired jobs can be retried.", status_code=409, extra={"job_id": job.id})

        params = loads(job.normalized_params_json, {})
        previous_error = {"code": job.error_code, "message": job.error_message}
        self.record_event(db, job, "retry_requested", "Retry requested for media job.", metadata={"previous_error": previous_error})
        job.status = "created"
        job.error_code = None
        job.error_message = None
        job.provider_id = None
        job.provider_model = None
        job.account_id = None
        job.provider_task_id = None
        job.output_asset_ids_json = dumps([])
        job.final_cost = None
        if priority is not None:
            job.priority = priority
        try:
            _, params = self.models.normalize_and_validate(db, job.logical_model, job.operation, params)
        except DomainError as exc:
            job.status = "failed"
            job.error_code = exc.code
            job.error_message = exc.message
            job.final_cost = 0
            self.record_event(db, job, "model_rejected", exc.message, metadata={"error_code": exc.code})
            db.commit()
            raise
        job.normalized_params_json = dumps(params)
        job.cost_estimate = self.billing.estimate(db, job.operation, job.logical_model, params)
        self.record_event(db, job, "retry_prepared", "Retry prepared and revalidated.", metadata={"cost_estimate": job.cost_estimate})
        try:
            self.billing.enforce_cost_policy(job, params)
        except DomainError as exc:
            job.status = "failed"
            job.error_code = exc.code
            job.error_message = exc.message
            job.final_cost = 0
            self.record_event(db, job, "cost_policy_rejected", exc.message, metadata={"error_code": exc.code, **exc.extra})
            db.commit()
            raise

        try:
            self.governance.enforce_job_create(db, job.user_id, job.api_key_id, job.operation, job.logical_model, params, job_id=job.id)
        except DomainError as exc:
            job.status = "failed"
            job.error_code = exc.code
            job.error_message = exc.message
            job.final_cost = 0
            self.record_event(db, job, "governance_rejected", exc.message, metadata={"error_code": exc.code, **exc.extra})
            db.commit()
            raise
        try:
            self.safety.evaluate(db, job.user_id, job.api_key_id, job.operation, job.logical_model, params, job_id=job.id)
        except DomainError as exc:
            job.status = "failed"
            job.error_code = exc.code
            job.error_message = exc.message
            job.final_cost = 0
            self.record_event(db, job, "safety_rejected", exc.message, metadata={"error_code": exc.code, **exc.extra})
            db.commit()
            raise

        self.billing.hold(db, job)
        self.record_event(db, job, "billing_held", "Estimated cost held for retry.", metadata={"amount": job.cost_estimate})
        job.status = "queued"
        self.record_event(db, job, "queued", "Retried job queued for execution.")
        db.commit()
        return job
