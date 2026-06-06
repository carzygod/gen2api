from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from . import models
from .utils import dumps, loads, new_id


class AlertService:
    FAILURE_SPIKE_WINDOW_MINUTES = 15
    FAILURE_SPIKE_MIN_FAILED = 3
    FAILURE_SPIKE_MIN_RATE = 0.6
    VIDEO_BURST_WINDOW_MINUTES = 60
    VIDEO_BURST_MIN_JOBS = 2
    VIDEO_BURST_MIN_AMOUNT = 400
    VIDEO_OPERATIONS = {"text_to_video", "image_to_video", "video_extend"}

    def trigger(
        self,
        db: Session,
        event_type: str,
        title: str,
        message: str,
        dimensions: dict[str, Any] | None = None,
        user_id: str = "",
        job_id: str = "",
        provider_id: str = "",
        account_id: str = "",
    ) -> list[models.AlertEvent]:
        dimensions = dimensions or {}
        rules = (
            db.query(models.AlertRule)
            .filter(models.AlertRule.enabled.is_(True), models.AlertRule.event_type == event_type)
            .order_by(models.AlertRule.severity.desc(), models.AlertRule.id.asc())
            .all()
        )
        events: list[models.AlertEvent] = []
        for rule in rules:
            if not self._matches(rule, dimensions):
                continue
            event = models.AlertEvent(
                id=new_id("alert"),
                rule_id=rule.id,
                event_type=event_type,
                severity=rule.severity,
                status="open",
                title=title,
                message=message,
                user_id=user_id,
                job_id=job_id,
                provider_id=provider_id,
                account_id=account_id,
                dimensions_json=dumps(dimensions),
            )
            db.add(event)
            events.append(event)
        return events

    def account_status_changed(self, db: Session, account: models.AccountResource, previous_status: str, reason: str) -> list[models.AlertEvent]:
        if account.status == "active" or account.status == previous_status:
            return []
        return self.trigger(
            db=db,
            event_type="account_status",
            title=f"Account {account.id} changed to {account.status}",
            message=reason,
            provider_id=account.provider_id,
            account_id=account.id,
            dimensions={"status": account.status, "previous_status": previous_status, "failure_score": account.failure_score},
        )

    def job_failed(self, db: Session, job: models.MediaJob) -> list[models.AlertEvent]:
        return self.trigger(
            db=db,
            event_type="job_failed",
            title=f"Job {job.id} failed",
            message=job.error_message or job.error_code or "Media job failed",
            user_id=job.user_id,
            job_id=job.id,
            provider_id=job.provider_id or "",
            account_id=job.account_id or "",
            dimensions={
                "error_code": job.error_code,
                "operation": job.operation,
                "logical_model": job.logical_model,
                "provider_model": job.provider_model,
            },
        )

    def high_cost_job(self, db: Session, job: models.MediaJob) -> list[models.AlertEvent]:
        amount = int(job.final_cost if job.final_cost is not None else job.cost_estimate)
        return self.trigger(
            db=db,
            event_type="high_cost_job",
            title=f"High cost job {job.id}",
            message=f"Job settled at {amount} credits.",
            user_id=job.user_id,
            job_id=job.id,
            provider_id=job.provider_id or "",
            account_id=job.account_id or "",
            dimensions={"amount": amount, "operation": job.operation, "logical_model": job.logical_model},
        )

    def provider_health(self, db: Session, check: models.ProviderHealthCheck) -> list[models.AlertEvent]:
        return self.trigger(
            db=db,
            event_type="provider_health",
            title=f"Provider {check.provider_id} health is {check.status}",
            message=check.message,
            provider_id=check.provider_id,
            dimensions={"status": check.status, "latency_ms": check.latency_ms},
        )

    def detect_usage_anomalies(self, db: Session, job: models.MediaJob) -> list[models.AlertEvent]:
        events: list[models.AlertEvent] = []
        events.extend(self.detect_failure_spike(db, job))
        events.extend(self.detect_high_cost_video_burst(db, job))
        return events

    def scan_usage_anomalies(self, db: Session, lookback_minutes: int = 60) -> list[models.AlertEvent]:
        cutoff = datetime.utcnow() - timedelta(minutes=max(1, lookback_minutes))
        jobs = (
            db.query(models.MediaJob)
            .filter(models.MediaJob.updated_at >= cutoff, models.MediaJob.status.in_(["completed", "failed", "cancelled", "expired"]))
            .order_by(models.MediaJob.updated_at.desc())
            .limit(500)
            .all()
        )
        events: list[models.AlertEvent] = []
        for job in jobs:
            events.extend(self.detect_usage_anomalies(db, job))
        return events

    def detect_failure_spike(self, db: Session, job: models.MediaJob) -> list[models.AlertEvent]:
        if job.status not in {"failed", "completed", "cancelled", "expired"}:
            return []
        cutoff = datetime.utcnow() - timedelta(minutes=self.FAILURE_SPIKE_WINDOW_MINUTES)
        query = db.query(models.MediaJob).filter(
            models.MediaJob.user_id == job.user_id,
            models.MediaJob.logical_model == job.logical_model,
            models.MediaJob.updated_at >= cutoff,
            models.MediaJob.status.in_(["completed", "failed", "cancelled", "expired"]),
        )
        if job.provider_id:
            query = query.filter(models.MediaJob.provider_id == job.provider_id)
        jobs = query.all()
        terminal = len(jobs)
        failed = [item for item in jobs if item.status == "failed"]
        if terminal < self.FAILURE_SPIKE_MIN_FAILED or len(failed) < self.FAILURE_SPIKE_MIN_FAILED:
            return []
        failure_rate = len(failed) / terminal
        if failure_rate < self.FAILURE_SPIKE_MIN_RATE:
            return []
        dimensions = {
            "anomaly_type": "failure_spike",
            "window_minutes": self.FAILURE_SPIKE_WINDOW_MINUTES,
            "terminal_jobs": terminal,
            "failed_jobs": len(failed),
            "failure_rate": round(failure_rate, 6),
            "operation": job.operation,
            "logical_model": job.logical_model,
            "provider_id": job.provider_id or "",
            "error_codes": self._error_counts(failed),
        }
        if self._has_recent_anomaly(db, dimensions, cutoff):
            return []
        return self.trigger(
            db=db,
            event_type="usage_anomaly",
            title=f"Failure spike for {job.logical_model}",
            message=f"{len(failed)}/{terminal} terminal jobs failed in {self.FAILURE_SPIKE_WINDOW_MINUTES} minutes.",
            user_id=job.user_id,
            job_id=job.id,
            provider_id=job.provider_id or "",
            account_id=job.account_id or "",
            dimensions=dimensions,
        )

    def detect_high_cost_video_burst(self, db: Session, job: models.MediaJob) -> list[models.AlertEvent]:
        if job.operation not in self.VIDEO_OPERATIONS:
            return []
        cutoff = datetime.utcnow() - timedelta(minutes=self.VIDEO_BURST_WINDOW_MINUTES)
        jobs = (
            db.query(models.MediaJob)
            .filter(
                models.MediaJob.user_id == job.user_id,
                models.MediaJob.operation.in_(list(self.VIDEO_OPERATIONS)),
                models.MediaJob.status == "completed",
                models.MediaJob.updated_at >= cutoff,
            )
            .all()
        )
        high_cost_jobs = [item for item in jobs if int(item.final_cost if item.final_cost is not None else item.cost_estimate or 0) >= 1]
        total_amount = sum(int(item.final_cost if item.final_cost is not None else item.cost_estimate or 0) for item in high_cost_jobs)
        if len(high_cost_jobs) < self.VIDEO_BURST_MIN_JOBS or total_amount < self.VIDEO_BURST_MIN_AMOUNT:
            return []
        dimensions = {
            "anomaly_type": "high_cost_video_burst",
            "window_minutes": self.VIDEO_BURST_WINDOW_MINUTES,
            "video_jobs": len(high_cost_jobs),
            "amount": total_amount,
            "logical_model": job.logical_model,
            "operation": job.operation,
        }
        if self._has_recent_anomaly(db, dimensions, cutoff):
            return []
        return self.trigger(
            db=db,
            event_type="usage_anomaly",
            title=f"High-cost video burst for user {job.user_id}",
            message=f"{len(high_cost_jobs)} video jobs consumed {total_amount} credits in {self.VIDEO_BURST_WINDOW_MINUTES} minutes.",
            user_id=job.user_id,
            job_id=job.id,
            provider_id=job.provider_id or "",
            account_id=job.account_id or "",
            dimensions=dimensions,
        )

    def _error_counts(self, jobs: list[models.MediaJob]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for job in jobs:
            code = job.error_code or "unknown"
            counts[code] = counts.get(code, 0) + 1
        return counts

    def _has_recent_anomaly(self, db: Session, dimensions: dict[str, Any], cutoff: datetime) -> bool:
        anomaly_type = dimensions.get("anomaly_type")
        logical_model = dimensions.get("logical_model")
        provider_id = dimensions.get("provider_id")
        recent = (
            db.query(models.AlertEvent)
            .filter(
                models.AlertEvent.event_type == "usage_anomaly",
                models.AlertEvent.status == "open",
                models.AlertEvent.created_at >= cutoff,
            )
            .order_by(models.AlertEvent.created_at.desc())
            .limit(100)
            .all()
        )
        for event in recent:
            existing = loads(event.dimensions_json, {})
            if existing.get("anomaly_type") != anomaly_type:
                continue
            if existing.get("logical_model") != logical_model:
                continue
            if provider_id is not None and existing.get("provider_id") != provider_id:
                continue
            return True
        return False

    def _matches(self, rule: models.AlertRule, dimensions: dict[str, Any]) -> bool:
        condition = loads(rule.condition_json, {})
        statuses = condition.get("statuses")
        if statuses and dimensions.get("status") not in statuses:
            return False
        error_codes = condition.get("error_codes")
        if error_codes and dimensions.get("error_code") not in error_codes:
            return False
        min_amount = condition.get("min_amount")
        if min_amount is not None and int(dimensions.get("amount") or 0) < int(min_amount):
            return False
        anomaly_types = condition.get("anomaly_types")
        if anomaly_types and dimensions.get("anomaly_type") not in anomaly_types:
            return False
        return True
