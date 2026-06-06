from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def now_utc() -> datetime:
    return datetime.utcnow()


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, onupdate=now_utc, nullable=False)


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    tier: Mapped[str] = mapped_column(String(32), default="default", nullable=False)
    wallet_balance: Mapped[int] = mapped_column(Integer, default=100000, nullable=False)


class ApiKey(TimestampMixin, Base):
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    user: Mapped[User] = relationship()


class CredentialSecret(TimestampMixin, Base):
    __tablename__ = "credential_secrets"

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), default="api_key", nullable=False)
    provider_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    account_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(128), nullable=False)
    preview: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class LogicalModel(TimestampMixin, Base):
    __tablename__ = "logical_models"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    operations_json: Mapped[str] = mapped_column(Text, nullable=False)
    constraints_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    default_params_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    billing_class: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Provider(TimestampMixin, Base):
    __tablename__ = "providers"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    adapter_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="disabled", nullable=False)
    base_config_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)


class ProviderModelMapping(TimestampMixin, Base):
    __tablename__ = "provider_model_mappings"

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    logical_model: Mapped[str] = mapped_column(String(64), ForeignKey("logical_models.id"), nullable=False)
    provider_id: Mapped[str] = mapped_column(String(64), ForeignKey("providers.id"), nullable=False)
    provider_model: Mapped[str] = mapped_column(String(120), nullable=False)
    operations_json: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    weight: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    cost_score: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    speed_score: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    quality_score: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    reliability_score: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class AccountResource(TimestampMixin, Base):
    __tablename__ = "account_resources"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider_id: Mapped[str] = mapped_column(String(64), ForeignKey("providers.id"), nullable=False)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    credential_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    supported_operations_json: Mapped[str] = mapped_column(Text, nullable=False)
    supported_provider_models_json: Mapped[str] = mapped_column(Text, nullable=False)
    quota_buckets_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    concurrency_limit: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    current_leases: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    health_score: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    failure_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    region: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    plan: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    last_error_code: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    last_error_message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    last_failed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_health_check_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AccountLease(TimestampMixin, Base):
    __tablename__ = "account_leases"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(String(64), ForeignKey("media_jobs.id"), nullable=False)
    account_id: Mapped[str] = mapped_column(String(64), ForeignKey("account_resources.id"), nullable=False)
    provider_id: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_model: Mapped[str] = mapped_column(String(120), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)


class MediaAsset(TimestampMixin, Base):
    __tablename__ = "media_assets"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(120), nullable=False)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sha256: Mapped[str] = mapped_column(String(128), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_meta_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)


class MediaJob(TimestampMixin, Base):
    __tablename__ = "media_jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), nullable=False)
    api_key_id: Mapped[str] = mapped_column(String(64), ForeignKey("api_keys.id"), nullable=False)
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    logical_model: Mapped[str] = mapped_column(String(64), ForeignKey("logical_models.id"), nullable=False)
    normalized_params_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    input_asset_ids_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    output_asset_ids_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    provider_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    account_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider_task_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="created", nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    cost_estimate: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    final_cost: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class MediaJobAttempt(TimestampMixin, Base):
    __tablename__ = "media_job_attempts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(String(64), ForeignKey("media_jobs.id"), nullable=False)
    provider_id: Mapped[str] = mapped_column(String(64), nullable=False)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_model: Mapped[str] = mapped_column(String(120), nullable=False)
    provider_task_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="created", nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_status: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    request_snapshot_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    raw_response_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class MediaJobEvent(TimestampMixin, Base):
    __tablename__ = "media_job_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(String(64), ForeignKey("media_jobs.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    provider_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    account_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    attempt_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)


class BillingHold(TimestampMixin, Base):
    __tablename__ = "billing_holds"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(String(64), ForeignKey("media_jobs.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="held", nullable=False)


class UsageRecord(TimestampMixin, Base):
    __tablename__ = "usage_records"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(String(64), ForeignKey("media_jobs.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), nullable=False)
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    logical_model: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)


class PricingRule(TimestampMixin, Base):
    __tablename__ = "pricing_rules"

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    logical_model: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    billing_class: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    operation: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    base_amount: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    unit_amount: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    input_asset_amount: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    provider_cost_base: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    provider_cost_unit: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    provider_cost_input_asset: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    quality_multipliers_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    currency: Mapped[str] = mapped_column(String(16), default="credits", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class ProviderCostRecord(TimestampMixin, Base):
    __tablename__ = "provider_cost_records"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(String(64), ForeignKey("media_jobs.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), nullable=False)
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    logical_model: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    provider_model: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(16), default="credits", nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)


class AlertRule(TimestampMixin, Base):
    __tablename__ = "alert_rules"

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), default="warning", nullable=False)
    condition_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class AlertEvent(TimestampMixin, Base):
    __tablename__ = "alert_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    rule_id: Mapped[str] = mapped_column(String(96), ForeignKey("alert_rules.id"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="open", nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    user_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    job_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    provider_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    account_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    dimensions_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)


class SafetyPolicy(TimestampMixin, Base):
    __tablename__ = "safety_policies"

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    scope: Mapped[str] = mapped_column(String(32), default="global", nullable=False)
    logical_model: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    operation: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    action: Mapped[str] = mapped_column(String(32), default="reject", nullable=False)
    severity: Mapped[str] = mapped_column(String(32), default="warning", nullable=False)
    match_type: Mapped[str] = mapped_column(String(32), default="term", nullable=False)
    terms_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    pattern_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)


class SafetyEvent(TimestampMixin, Base):
    __tablename__ = "safety_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    policy_id: Mapped[str] = mapped_column(String(96), ForeignKey("safety_policies.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    api_key_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    job_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    operation: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    logical_model: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    action: Mapped[str] = mapped_column(String(32), default="reject", nullable=False)
    severity: Mapped[str] = mapped_column(String(32), default="warning", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="blocked", nullable=False)
    matched_terms_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    prompt_excerpt: Mapped[str] = mapped_column(Text, default="", nullable=False)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)


class UserLimitPolicy(TimestampMixin, Base):
    __tablename__ = "user_limit_policies"

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    user_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    tier: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    requests_per_minute: Mapped[int] = mapped_column(Integer, default=600, nullable=False)
    daily_job_limit: Mapped[int] = mapped_column(Integer, default=10000, nullable=False)
    concurrent_job_limit: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    allowed_models_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    high_cost_models_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    high_cost_allowed: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)


class CircuitBreaker(TimestampMixin, Base):
    __tablename__ = "circuit_breakers"

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[str] = mapped_column(String(96), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="open", nullable=False)
    reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    error_code: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    block_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)


class RequestAuditLog(TimestampMixin, Base):
    __tablename__ = "request_audit_logs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    request_id: Mapped[str] = mapped_column(String(96), nullable=False)
    method: Mapped[str] = mapped_column(String(16), nullable=False)
    path: Mapped[str] = mapped_column(String(512), nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    user_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    api_key_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    job_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    attempt_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    provider_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    account_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    logical_model: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    provider_model: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    provider_task_id: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    standard_error_code: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    error_code: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    client_ip: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    user_agent: Mapped[str] = mapped_column(Text, default="", nullable=False)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)


class ProviderContractResult(TimestampMixin, Base):
    __tablename__ = "provider_contract_results"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider_id: Mapped[str] = mapped_column(String(64), ForeignKey("providers.id"), nullable=False)
    adapter_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    operation: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    provider_model: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    run_submit: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    checks_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    error_message: Mapped[str] = mapped_column(Text, default="", nullable=False)


class ProviderHealthCheck(TimestampMixin, Base):
    __tablename__ = "provider_health_checks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider_id: Mapped[str] = mapped_column(String(64), ForeignKey("providers.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    detail_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)


class WebhookDelivery(TimestampMixin, Base):
    __tablename__ = "webhook_deliveries"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(String(64), ForeignKey("media_jobs.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), nullable=False)
    target_url: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
