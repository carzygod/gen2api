from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from . import models
from .utils import DomainError, loads


class ModelRegistryService:
    def normalize_and_validate(self, db: Session, logical_model: str, operation: str, params: dict[str, Any]) -> tuple[models.LogicalModel, dict[str, Any]]:
        model = db.get(models.LogicalModel, logical_model)
        if not model:
            raise DomainError("LOGICAL_MODEL_NOT_FOUND", f"Logical model {logical_model} was not found.", status_code=404)
        if not model.enabled:
            raise DomainError("LOGICAL_MODEL_DISABLED", f"Logical model {logical_model} is disabled.", status_code=403)
        operations = loads(model.operations_json, [])
        if operation not in operations:
            raise DomainError("OPERATION_NOT_SUPPORTED", f"Model {logical_model} does not support {operation}.", status_code=400)

        normalized = dict(loads(model.default_params_json, {}))
        normalized.update(params or {})
        self._validate_constraints(model, operation, normalized)
        return model, normalized

    def _validate_constraints(self, model: models.LogicalModel, operation: str, params: dict[str, Any]) -> None:
        constraints = loads(model.constraints_json, {})
        prompt = str(params.get("prompt") or "")
        max_prompt_length = constraints.get("max_prompt_length")
        if max_prompt_length is not None and len(prompt) > int(max_prompt_length):
            raise DomainError("INVALID_INPUT", f"Prompt exceeds max_prompt_length={max_prompt_length}.", status_code=400)

        n = params.get("n")
        if n is not None:
            self._range("n", int(n), constraints.get("min_n"), constraints.get("max_n"))

        duration = params.get("duration")
        if duration is not None and operation in {"text_to_video", "image_to_video", "video_extend"}:
            self._range("duration", int(duration), constraints.get("min_duration"), constraints.get("max_duration"))

        self._allowed("quality", params.get("quality"), constraints.get("allowed_quality"))
        self._allowed("size", params.get("size"), constraints.get("allowed_sizes"))
        self._allowed("aspect_ratio", params.get("aspect_ratio"), constraints.get("allowed_aspect_ratios"))

        max_input_assets = constraints.get("max_input_assets")
        if max_input_assets is not None and self._input_asset_count(params) > int(max_input_assets):
            raise DomainError("INVALID_INPUT", f"Input asset count exceeds max_input_assets={max_input_assets}.", status_code=400)

    def _range(self, field: str, value: int, min_value: Any, max_value: Any) -> None:
        if min_value is not None and value < int(min_value):
            raise DomainError("INVALID_INPUT", f"{field} must be >= {min_value}.", status_code=400)
        if max_value is not None and value > int(max_value):
            raise DomainError("INVALID_INPUT", f"{field} must be <= {max_value}.", status_code=400)

    def _allowed(self, field: str, value: Any, allowed: Any) -> None:
        if value is None or not allowed:
            return
        if str(value) not in [str(item) for item in allowed]:
            raise DomainError("INVALID_INPUT", f"{field} must be one of {allowed}.", status_code=400)

    def _input_asset_count(self, params: dict[str, Any]) -> int:
        count = 0
        for key in ["image", "images", "assets", "first_frame", "last_frame", "mask", "video", "videos"]:
            value = params.get(key)
            if isinstance(value, list):
                count += len(value)
            elif value:
                count += 1
        return count
