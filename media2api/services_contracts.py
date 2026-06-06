from __future__ import annotations

import time
from typing import Any

from sqlalchemy.orm import Session

from . import models
from .providers import ProviderContext, get_provider
from .services_capabilities import ProviderCapabilityService
from .utils import DomainError, dumps, loads, new_id


class ProviderContractService:
    def __init__(self) -> None:
        self.capabilities = ProviderCapabilityService()

    def run(
        self,
        db: Session,
        provider_id: str,
        operation: str = "text_to_image",
        provider_model: str | None = None,
        run_submit: bool = False,
    ) -> models.ProviderContractResult:
        started = time.time()
        provider = db.get(models.Provider, provider_id)
        if not provider:
            raise DomainError("PROVIDER_NOT_FOUND", status_code=404)

        checks: list[dict[str, Any]] = []
        status = "passed"
        error_message = ""
        adapter = get_provider(provider_id)

        try:
            capabilities = adapter.capabilities()
            self._check(checks, "capabilities_shape", isinstance(capabilities, dict), "Adapter capabilities must be a dict.", capabilities)
            operations = capabilities.get("operations") if isinstance(capabilities, dict) else None
            self._check(checks, "capabilities_operations", isinstance(operations, list) and bool(operations), "Adapter must declare supported operations.", {"operations": operations})
            if isinstance(operations, list):
                self._check(checks, "operation_declared", operation in operations, f"Operation {operation} must be declared.", {"operation": operation})

            capability_snapshot = self.capabilities.snapshot(db, provider)
            self._validate_capability_snapshot(checks, capability_snapshot, operation, provider_model)

            health = adapter.health_check(db, provider_id)
            self._check(checks, "health_check_shape", isinstance(health, dict), "Health check must return a dict.", health)
            health_ok = isinstance(health, dict) and health.get("status") == "ok"
            self._check(checks, "health_check_ok", health_ok, "Health check must return status=ok.", health)

            mappings = self._candidate_mappings(db, provider_id, operation, provider_model)
            self._check(checks, "mapping_available", bool(mappings), "Provider must have at least one compatible mapping.", {"operation": operation, "provider_model": provider_model})

            accounts = db.query(models.AccountResource).filter(models.AccountResource.provider_id == provider_id).all()
            self._check(checks, "account_declared", bool(accounts), "Provider must have at least one account resource.", {"account_count": len(accounts)})
            active_accounts = [account for account in accounts if account.status == "active"]
            self._check(checks, "account_active", bool(active_accounts), "Provider must have at least one active account.", {"active_account_count": len(active_accounts)})
            self._validate_account_capability_alignment(checks, active_accounts, capability_snapshot)

            if run_submit:
                self._submit_contract(db, adapter, provider_id, operation, provider_model, mappings, active_accounts, checks)
        except Exception as exc:
            status = "failed"
            error_message = str(exc)
            checks.append({"name": "contract_exception", "status": "failed", "message": str(exc), "detail": {"type": type(exc).__name__}})

        if any(check["status"] == "failed" for check in checks):
            status = "failed"
        duration_ms = int((time.time() - started) * 1000)
        result = models.ProviderContractResult(
            id=new_id("pcontract"),
            provider_id=provider_id,
            adapter_type=provider.adapter_type,
            status=status,
            operation=operation,
            provider_model=provider_model or "",
            run_submit=run_submit,
            duration_ms=duration_ms,
            checks_json=dumps(checks),
            error_message=error_message,
        )
        db.add(result)
        db.commit()
        return result

    def latest_matrix(self, db: Session) -> list[dict[str, Any]]:
        providers = db.query(models.Provider).order_by(models.Provider.id).all()
        rows: list[dict[str, Any]] = []
        for provider in providers:
            latest = (
                db.query(models.ProviderContractResult)
                .filter(models.ProviderContractResult.provider_id == provider.id)
                .order_by(models.ProviderContractResult.created_at.desc())
                .first()
            )
            rows.append(
                {
                    "provider_id": provider.id,
                    "provider_status": provider.status,
                    "adapter_type": provider.adapter_type,
                    "latest_result_id": latest.id if latest else "",
                    "contract_status": latest.status if latest else "untested",
                    "operation": latest.operation if latest else "",
                    "run_submit": latest.run_submit if latest else False,
                    "checked_at": latest.created_at.isoformat() + "Z" if latest else None,
                }
            )
        return rows

    def _validate_capability_snapshot(self, checks: list[dict[str, Any]], snapshot: dict[str, Any], operation: str, provider_model: str | None) -> None:
        operations = snapshot.get("operations")
        models_ = snapshot.get("models")
        profiles = snapshot.get("operation_capabilities")
        self._check(checks, "effective_capabilities_shape", isinstance(snapshot, dict), "Effective provider capability snapshot must be a dict.", {"provider_id": snapshot.get("provider_id")})
        self._check(checks, "effective_capabilities_operations", isinstance(operations, list) and bool(operations), "Effective capabilities must include operations.", {"operations": operations})
        self._check(checks, "effective_capabilities_models", isinstance(models_, list) and bool(models_), "Effective capabilities must include provider models.", {"models": models_})
        self._check(checks, "effective_operation_declared", isinstance(operations, list) and operation in operations, f"Effective capabilities must include {operation}.", {"operation": operation, "operations": operations})
        if provider_model:
            self._check(
                checks,
                "effective_provider_model_declared",
                isinstance(models_, list) and provider_model in models_,
                "Requested provider_model must be declared in capabilities.",
                {"provider_model": provider_model, "models": models_},
            )
        self._check(checks, "operation_capabilities_shape", isinstance(profiles, dict) and bool(profiles), "Effective capabilities must include operation_capabilities.", {"operation_capabilities": profiles})
        profile = profiles.get(operation) if isinstance(profiles, dict) else None
        self._check(checks, "operation_profile_declared", isinstance(profile, dict), f"Operation profile for {operation} must be declared.", {"operation": operation, "profile": profile})
        if not isinstance(profile, dict):
            return
        output_kind = profile.get("output_kind")
        self._check(checks, "operation_profile_output_kind", output_kind in {"image", "video"}, "Operation profile must declare output_kind=image|video.", {"output_kind": output_kind})
        max_input_assets = profile.get("max_input_assets")
        self._check(
            checks,
            "operation_profile_max_input_assets",
            max_input_assets is None or (isinstance(max_input_assets, int) and max_input_assets >= 0),
            "Operation profile must declare non-negative max_input_assets or null.",
            {"max_input_assets": max_input_assets},
        )
        params = profile.get("params")
        self._check(checks, "operation_profile_params", isinstance(params, list), "Operation profile must declare supported params list.", {"params": params})
        if output_kind == "video":
            duration = profile.get("duration_seconds")
            duration_ok = isinstance(duration, dict) and int(duration.get("min") or 0) >= 0 and int(duration.get("max") or 0) >= int(duration.get("min") or 0)
            self._check(checks, "operation_profile_duration", duration_ok, "Video operation profile must declare duration_seconds min/max.", {"duration_seconds": duration})
        for mapping in snapshot.get("mappings") or []:
            mapping_id = mapping.get("id")
            mapping_model = mapping.get("provider_model")
            mapping_operations = mapping.get("operations") or []
            self._check(
                checks,
                f"mapping_model_declared:{mapping_id}",
                mapping_model in (models_ or []),
                "Every mapping provider_model must be declared in capabilities.",
                {"provider_model": mapping_model},
            )
            undeclared = [item for item in mapping_operations if item not in (operations or [])]
            self._check(
                checks,
                f"mapping_operations_declared:{mapping_id}",
                not undeclared,
                "Every mapping operation must be declared in capabilities.",
                {"undeclared_operations": undeclared},
            )

    def _validate_account_capability_alignment(self, checks: list[dict[str, Any]], accounts: list[models.AccountResource], snapshot: dict[str, Any]) -> None:
        models_ = set(snapshot.get("models") or [])
        operations = set(snapshot.get("operations") or [])
        for account in accounts:
            account_models = set(loads(account.supported_provider_models_json, []))
            account_operations = set(loads(account.supported_operations_json, []))
            undeclared_models = sorted(account_models - models_)
            undeclared_operations = sorted(account_operations - operations)
            self._check(
                checks,
                f"account_models_declared:{account.id}",
                not undeclared_models,
                "Account supported_provider_models must be declared in provider capabilities.",
                {"undeclared_models": undeclared_models},
            )
            self._check(
                checks,
                f"account_operations_declared:{account.id}",
                not undeclared_operations,
                "Account supported_operations must be declared in provider capabilities.",
                {"undeclared_operations": undeclared_operations},
            )

    def _candidate_mappings(
        self,
        db: Session,
        provider_id: str,
        operation: str,
        provider_model: str | None,
    ) -> list[models.ProviderModelMapping]:
        mappings = db.query(models.ProviderModelMapping).filter(models.ProviderModelMapping.provider_id == provider_id, models.ProviderModelMapping.enabled.is_(True)).all()
        result = []
        for mapping in mappings:
            if provider_model and mapping.provider_model != provider_model:
                continue
            if operation not in loads(mapping.operations_json, []):
                continue
            result.append(mapping)
        return result

    def _submit_contract(
        self,
        db: Session,
        adapter: Any,
        provider_id: str,
        operation: str,
        provider_model: str | None,
        mappings: list[models.ProviderModelMapping],
        accounts: list[models.AccountResource],
        checks: list[dict[str, Any]],
    ) -> None:
        mapping = mappings[0] if mappings else None
        if not mapping:
            self._check(checks, "submit_mapping", False, "Submit contract requires a compatible mapping.", {})
            return
        account = self._compatible_account(accounts, mapping, operation)
        if not account:
            self._check(checks, "submit_account", False, "Submit contract requires an active compatible account.", {"provider_model": mapping.provider_model})
            return

        job = models.MediaJob(
            id=new_id("contractjob"),
            user_id="usr_admin",
            api_key_id="key_admin",
            operation=operation,
            logical_model=mapping.logical_model,
            normalized_params_json=dumps({"prompt": "media2api provider contract test", "n": 1, "duration": 1, "quality": "standard"}),
            input_asset_ids_json=dumps([]),
            output_asset_ids_json=dumps([]),
            provider_id=provider_id,
            provider_model=provider_model or mapping.provider_model,
            account_id=account.id,
            status="contract_test",
            cost_estimate=0,
        )
        db.add(job)
        db.flush()
        ctx = ProviderContext(provider_id=provider_id, provider_model=provider_model or mapping.provider_model, account=account, user_id=job.user_id)
        result = adapter.submit(db, ctx, job)
        asset_ids = [asset.id for asset in result.assets]
        job.provider_task_id = result.provider_task_id
        job.output_asset_ids_json = dumps(asset_ids)
        job.status = "completed"
        self._check(checks, "submit_result_shape", bool(result.provider_task_id), "Submit result must include provider_task_id.", {"provider_task_id": result.provider_task_id})
        self._check(checks, "submit_assets", bool(asset_ids), "Submit result must include stored platform assets.", {"asset_ids": asset_ids})
        for asset in result.assets:
            self._check(checks, f"asset_stored:{asset.id}", bool(asset.storage_key and asset.source == "provider_result"), "Provider asset must be stored in platform asset store.", {"asset_id": asset.id, "source": asset.source})

    def _compatible_account(self, accounts: list[models.AccountResource], mapping: models.ProviderModelMapping, operation: str) -> models.AccountResource | None:
        for account in accounts:
            if operation not in loads(account.supported_operations_json, []):
                continue
            if mapping.provider_model not in loads(account.supported_provider_models_json, []):
                continue
            return account
        return None

    def _check(self, checks: list[dict[str, Any]], name: str, passed: bool, message: str, detail: Any) -> None:
        checks.append({"name": name, "status": "passed" if passed else "failed", "message": message, "detail": detail})
