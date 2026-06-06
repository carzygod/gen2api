from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from . import models
from .services_alerts import AlertService
from .utils import DomainError, dumps, loads, new_id


TEXT_KEYS = {"prompt", "negative_prompt", "instruction", "instructions", "description", "caption", "text", "content"}
SKIP_KEYS = {"b64_json", "image", "images", "mask", "assets", "first_frame", "last_frame", "url", "webhook"}


class SafetyService:
    def __init__(self) -> None:
        self.alerts = AlertService()

    def evaluate(
        self,
        db: Session,
        user_id: str,
        api_key_id: str,
        operation: str,
        logical_model: str,
        params: dict[str, Any],
        job_id: str = "",
    ) -> list[models.SafetyEvent]:
        prompt_text = self._extract_prompt_text(params)
        if not prompt_text:
            return []

        policies = (
            db.query(models.SafetyPolicy)
            .filter(models.SafetyPolicy.enabled.is_(True))
            .order_by(models.SafetyPolicy.scope.desc(), models.SafetyPolicy.id.asc())
            .all()
        )
        events: list[models.SafetyEvent] = []
        rejection: tuple[models.SafetyPolicy, models.SafetyEvent] | None = None
        for policy in policies:
            if not self._scope_matches(policy, operation, logical_model):
                continue
            matched = self._matches(policy, prompt_text)
            if not matched:
                continue
            status = "blocked" if policy.action == "reject" else "logged"
            event = models.SafetyEvent(
                id=new_id("safety"),
                policy_id=policy.id,
                user_id=user_id,
                api_key_id=api_key_id,
                job_id=job_id,
                operation=operation,
                logical_model=logical_model,
                action=policy.action,
                severity=policy.severity,
                status=status,
                matched_terms_json=dumps(matched),
                prompt_excerpt=self._excerpt(prompt_text),
                metadata_json=dumps({"scope": policy.scope, "match_type": policy.match_type}),
            )
            db.add(event)
            events.append(event)
            if policy.action == "reject" and rejection is None:
                rejection = (policy, event)

        if events:
            db.flush()
        if rejection:
            policy, event = rejection
            self.alerts.trigger(
                db=db,
                event_type="safety_rejected",
                title=f"Safety policy {policy.id} rejected a job",
                message=policy.name,
                dimensions={"policy_id": policy.id, "action": policy.action, "severity": policy.severity, "matched_terms": loads(event.matched_terms_json, [])},
                user_id=user_id,
                job_id=job_id,
            )
            db.flush()
            raise DomainError(
                "SAFETY_REJECTED",
                f"Request rejected by safety policy {policy.name}.",
                status_code=400,
                retryable=False,
                extra={"job_id": job_id, "policy_id": policy.id, "safety_event_id": event.id},
            )
        return events

    def _scope_matches(self, policy: models.SafetyPolicy, operation: str, logical_model: str) -> bool:
        if policy.logical_model and policy.logical_model != logical_model:
            return False
        if policy.operation and policy.operation != operation:
            return False
        if policy.scope == "model" and not policy.logical_model:
            return False
        if policy.scope == "operation" and not policy.operation:
            return False
        return True

    def _matches(self, policy: models.SafetyPolicy, prompt_text: str) -> list[str]:
        matched: list[str] = []
        lower_text = prompt_text.lower()
        for term in loads(policy.terms_json, []):
            term_text = str(term).strip()
            if term_text and term_text.lower() in lower_text:
                matched.append(term_text)

        pattern = loads(policy.pattern_json, {})
        regexes = pattern.get("regex") if isinstance(pattern, dict) else None
        if isinstance(regexes, str):
            regexes = [regexes]
        if isinstance(regexes, list):
            for regex in regexes:
                try:
                    if re.search(str(regex), prompt_text, flags=re.IGNORECASE):
                        matched.append(str(regex))
                except re.error:
                    continue
        return matched

    def _extract_prompt_text(self, value: Any) -> str:
        chunks: list[str] = []

        def walk(item: Any, key: str = "") -> None:
            key_lower = key.lower()
            if key_lower in SKIP_KEYS:
                return
            if isinstance(item, str):
                if key_lower in TEXT_KEYS or key_lower.endswith("_prompt"):
                    chunks.append(item)
                return
            if isinstance(item, dict):
                for child_key, child_value in item.items():
                    walk(child_value, str(child_key))
                return
            if isinstance(item, list):
                for child in item:
                    walk(child, key)

        walk(value)
        return " ".join(chunk.strip() for chunk in chunks if chunk.strip())

    def _excerpt(self, text: str, limit: int = 160) -> str:
        compact = re.sub(r"\s+", " ", text).strip()
        if len(compact) <= limit:
            return compact
        return compact[: limit - 3] + "..."
