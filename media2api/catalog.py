from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import models
from .config import settings
from .security import hash_api_key
from .utils import dumps


OPERATIONS = {
    "t2i": "text_to_image",
    "i2i": "image_to_image",
    "edit": "image_edit",
    "t2v": "text_to_video",
    "i2v": "image_to_video",
    "extend": "video_extend",
}


LOGICAL_MODELS = [
    ("t2i-fast", "T2I Fast", [OPERATIONS["t2i"]], "image_fast"),
    ("t2i-pro", "T2I Pro", [OPERATIONS["t2i"]], "image_pro"),
    ("image-edit", "Image Edit", [OPERATIONS["edit"], OPERATIONS["i2i"]], "image_edit"),
    ("image-variation", "Image Variation", [OPERATIONS["i2i"]], "image_variation"),
    ("i2v-fast", "I2V Fast", [OPERATIONS["i2v"]], "video_fast"),
    ("i2v-pro", "I2V Pro", [OPERATIONS["i2v"]], "video_pro"),
    ("t2v-general", "T2V General", [OPERATIONS["t2v"]], "video_general"),
    ("video-extend", "Video Extend", [OPERATIONS["extend"]], "video_extend"),
]


PROVIDERS = [
    ("mock", "Mock Provider", "mock", "active", "Local deterministic T2I/I2I/T2V/I2V provider for validation."),
    ("openai_image", "OpenAI / ChatGPT / Codex image resources", "sidecar_adapter", "disabled", "Targets gpt-image-2 and codex-gpt-image-2 via a connector."),
    ("openai_web_session", "OpenAI / ChatGPT Web session image resources", "sidecar_adapter", "disabled", "Selected OAI-WEB-01; targets ChatGPT Web gpt-image-2 resources."),
    ("openai_codex", "OpenAI Codex GPT Image resources", "sidecar_adapter", "disabled", "Selected OAI-CODEX-04; targets Codex GPT Image 2 resources."),
    ("gemini", "Gemini / AI Studio resources", "sidecar_adapter", "disabled", "Targets veo-3.1, Nano Banana, Imagen families via connector."),
    ("gemini_cli_oauth", "Gemini CLI OAuth image/video resources", "sidecar_adapter", "disabled", "Selected GEM-CLI-02; targets Gemini CLI OAuth Nano Banana and Veo resources."),
    ("gemini_web_session", "Gemini Web session image/video resources", "sidecar_adapter", "disabled", "Selected GEM-WEB-01; targets Gemini Web image/video resources."),
    ("antigravity", "Antigravity agent resources", "sidecar_adapter", "disabled", "Selected AG-01; keeps Antigravity separate from Gemini CLI/Web."),
    ("grok", "Grok Imagine resources", "http_adapter", "disabled", "Targets Grok Imagine image and video resources."),
    ("qwen", "Qwen / Tongyi resources", "http_adapter", "disabled", "Targets Qwen Image and Qwen video resources."),
    ("qwen_ai_web_session", "Qwen.ai Web session resources", "http_adapter", "disabled", "Selected QWEN-AI-01; targets qwen.ai/chat.qwen.ai image and video resources."),
    ("qianwen_web_session", "Qianwen.com Web session resources", "http_adapter", "disabled", "Selected QIANWEN-WEB-01; keeps qianwen.com separate from qwen.ai."),
    ("jimeng", "Jimeng / Dreamina / Seedream / Seedance resources", "http_adapter", "disabled", "Targets Seedream and Seedance media resources."),
    ("jimeng_web_session", "Jimeng / Dreamina Web session resources", "http_adapter", "disabled", "Selected JM-01; targets Jimeng/Dreamina image resources."),
    ("doubao_web_session", "Doubao Web session resources", "http_adapter", "disabled", "Selected DOUBAO-WEB-01; keeps Doubao daily quotas separate from Jimeng."),
    ("kling", "Kling resources", "library_adapter", "disabled", "Targets Kling T2V/I2V/extend resources."),
    ("kling_web_session", "Kling Web session resources", "library_adapter", "disabled", "Selected KLING-WEB-01; targets Kling Web video resources."),
    ("luma", "Luma Dream Machine resources", "library_adapter", "disabled", "Targets Dream Machine video generation resources."),
    ("luma_web_session", "Luma Web session resources", "library_adapter", "disabled", "Selected LUMA-WEB-01; targets Luma Web video resources."),
    ("runway", "Runway resources", "library_adapter", "disabled", "Targets Gen-3/Gen-4 video resources."),
    ("midjourney", "Midjourney resources", "task_channel_adapter", "disabled", "Targets V6/V7/Niji image tasks."),
    ("midjourney_discord_session", "Midjourney Discord/session resources", "task_channel_adapter", "disabled", "Selected MID-01; targets Discord/MJ task-channel image resources."),
    ("pollinations", "Pollinations aggregator", "aggregator_adapter", "disabled", "Aggregator fallback for image and video models."),
    ("openrouter_image", "OpenRouter image model aggregator", "aggregator_adapter", "disabled", "Commercial image-model fallback aggregator."),
    ("fal_replicate", "fal / Replicate model marketplace", "aggregator_adapter", "disabled", "Commercial model marketplace fallback for image and video models."),
    ("seedream_proxy", "Seedream third-party proxy", "http_adapter", "disabled", "Seedream/Seededit reseller or connector fallback."),
    ("amux_qwen", "AMUX / Qwen third-party image resources", "http_adapter", "disabled", "Qwen image fallback connector."),
    ("flux_stability", "Flux / Stable Image resources", "aggregator_adapter", "disabled", "Self-hosted or third-party Flux/Stable Image fallback."),
]


TARGET_MODEL_TABLE = [
    ("openai_image", ["gpt-image-2", "codex-gpt-image-2", "ChatGPT Images"], ["text_to_image", "image_to_image", "image_edit"], "P0"),
    ("openai_web_session", ["gpt-image-2", "ChatGPT Images"], ["text_to_image", "image_to_image", "image_edit"], "P0"),
    ("openai_codex", ["gpt-image-2", "codex-gpt-image-2", "Codex Images"], ["text_to_image", "image_to_image", "image_edit"], "P0"),
    ("gemini", ["veo-3.1", "Veo 3.x", "Nano Banana", "Nano Banana Pro", "Gemini Flash Image", "Gemini Pro Image", "Imagen 4"], ["text_to_image", "image_to_image", "image_edit", "text_to_video", "image_to_video"], "P0/P1"),
    ("gemini_cli_oauth", ["veo-3.1", "Nano Banana", "Nano Banana Pro", "Imagen 4"], ["text_to_image", "image_to_image", "image_edit", "text_to_video", "image_to_video"], "P0/P1"),
    ("gemini_web_session", ["veo-3.1", "Nano Banana", "Nano Banana Pro", "Imagen 4"], ["text_to_image", "image_to_image", "image_edit", "text_to_video", "image_to_video"], "P0"),
    ("antigravity", ["Antigravity Agent media bridge"], ["text_to_image", "image_to_image", "image_edit", "text_to_video", "image_to_video"], "P1"),
    ("grok", ["Grok Imagine Image", "Grok Imagine Image Quality", "Grok Imagine Video"], ["text_to_image", "image_to_image", "text_to_video", "image_to_video"], "P0"),
    ("qwen", ["Qwen Image", "Qwen Image Edit", "Qwen Chat Image", "Qwen Video", "Wan related video"], ["text_to_image", "image_to_image", "image_edit", "text_to_video", "image_to_video"], "P0/P1"),
    ("qwen_ai_web_session", ["Qwen Image", "Qwen Image Edit", "Qwen Video"], ["text_to_image", "image_to_image", "image_edit", "text_to_video", "image_to_video"], "P0"),
    ("qianwen_web_session", ["Tongyi Qianwen Web image/video candidates"], ["text_to_image", "image_to_image", "image_edit", "text_to_video", "image_to_video"], "P1"),
    ("jimeng", ["Jimeng 3.x/5.x", "Dreamina", "Seedream 3/4/5", "Seededit", "Seedance Video"], ["text_to_image", "image_to_image", "image_edit", "text_to_video", "image_to_video"], "P0"),
    ("jimeng_web_session", ["Jimeng", "Dreamina"], ["text_to_image", "image_to_image", "image_edit"], "P0"),
    ("doubao_web_session", ["Doubao Image", "Doubao Video"], ["text_to_image", "image_to_image", "image_edit", "text_to_video", "image_to_video"], "P0"),
    ("kling", ["Kling Standard", "Kling HQ", "Kling I2V", "Kling T2V", "Kling Extend"], ["text_to_video", "image_to_video", "video_extend"], "P1"),
    ("kling_web_session", ["Kling Standard", "Kling HQ", "Kling I2V", "Kling T2V", "Kling Extend"], ["text_to_video", "image_to_video", "video_extend"], "P1"),
    ("luma", ["Luma Dream Machine", "Luma Ray", "Video Extend"], ["text_to_video", "image_to_video", "video_extend"], "P1"),
    ("luma_web_session", ["Luma Dream Machine", "Luma Ray", "Video Extend"], ["text_to_video", "image_to_video", "video_extend"], "P1"),
    ("runway", ["Runway Gen-3", "Runway Gen-4", "Image to Video", "Video Extend"], ["text_to_video", "image_to_video", "video_extend"], "P2"),
    ("midjourney", ["Midjourney V6", "Midjourney V7", "Niji", "Describe", "Blend", "Variation"], ["text_to_image", "image_to_image"], "P2"),
    ("midjourney_discord_session", ["Midjourney V6", "Midjourney V7", "Niji", "Describe", "Blend", "Variation"], ["text_to_image", "image_to_image"], "P2"),
    ("pollinations", ["gpt-image-2", "nanobanana", "seedream", "qwen-image", "grok-imagine", "veo", "seedance", "wan"], ["text_to_image", "image_to_image", "text_to_video", "image_to_video"], "P1/P2"),
    ("openrouter_image", ["GPT Image", "Nano Banana", "Seedream", "Recraft", "Flux", "Qwen Image"], ["text_to_image", "image_to_image"], "P2"),
    ("fal_replicate", ["Nano Banana", "Qwen Image", "Seedream", "Flux", "Recraft", "Wan", "video models"], ["text_to_image", "image_to_image", "text_to_video", "image_to_video"], "P2"),
    ("seedream_proxy", ["Seedream 3", "Seedream 4", "Seedream 5", "Seededit"], ["text_to_image", "image_to_image", "image_edit"], "P2"),
    ("amux_qwen", ["Qwen Image", "Wan / Qwen image capabilities"], ["text_to_image", "image_to_image"], "P2"),
    ("flux_stability", ["Flux", "SDXL", "Stable Image", "ControlNet-like image editing"], ["text_to_image", "image_to_image", "image_edit"], "P2"),
]


MOCK_MAPPINGS = [
    ("t2i-fast", "mock", "mock-image-fast", [OPERATIONS["t2i"]], 1, 0.95, 0.95, 0.5),
    ("t2i-pro", "mock", "mock-image-pro", [OPERATIONS["t2i"]], 1, 0.7, 0.9, 0.8),
    ("image-edit", "mock", "mock-image-edit", [OPERATIONS["edit"], OPERATIONS["i2i"]], 1, 0.8, 0.85, 0.7),
    ("image-variation", "mock", "mock-image-variation", [OPERATIONS["i2i"]], 1, 0.8, 0.85, 0.7),
    ("i2v-fast", "mock", "mock-video-fast", [OPERATIONS["i2v"]], 1, 0.85, 0.9, 0.6),
    ("i2v-pro", "mock", "mock-video-pro", [OPERATIONS["i2v"]], 1, 0.6, 0.7, 0.85),
    ("t2v-general", "mock", "mock-video-general", [OPERATIONS["t2v"]], 1, 0.75, 0.8, 0.7),
    ("video-extend", "mock", "mock-video-extend", [OPERATIONS["extend"]], 1, 0.7, 0.75, 0.7),
]


PRICING_RULES = [
    ("price_t2i_fast", "T2I Fast default", "t2i-fast", "image_fast", OPERATIONS["t2i"], "image", 0, 10, 0, 0, 2, 0),
    ("price_t2i_pro", "T2I Pro default", "t2i-pro", "image_pro", OPERATIONS["t2i"], "image", 0, 10, 0, 0, 3, 0),
    ("price_image_edit", "Image Edit default", "image-edit", "image_edit", OPERATIONS["edit"], "image", 0, 10, 2, 0, 3, 1),
    ("price_image_variation", "Image Variation default", "image-variation", "image_variation", OPERATIONS["i2i"], "image", 0, 10, 2, 0, 3, 1),
    ("price_i2v_fast", "I2V Fast default", "i2v-fast", "video_fast", OPERATIONS["i2v"], "second", 0, 80, 5, 0, 25, 2),
    ("price_i2v_pro", "I2V Pro default", "i2v-pro", "video_pro", OPERATIONS["i2v"], "second", 0, 80, 5, 0, 35, 2),
    ("price_t2v_general", "T2V General default", "t2v-general", "video_general", OPERATIONS["t2v"], "second", 0, 80, 0, 0, 25, 0),
    ("price_video_extend", "Video Extend default", "video-extend", "video_extend", OPERATIONS["extend"], "second", 0, 60, 0, 0, 20, 0),
]


ALERT_RULES = [
    ("alert_account_rate_limited", "Account rate limited", "account_status", "warning", {"statuses": ["rate_limited"]}),
    ("alert_account_auth_required", "Account auth required", "account_status", "critical", {"statuses": ["auth_required"]}),
    ("alert_account_quota_exhausted", "Account quota exhausted", "account_status", "warning", {"statuses": ["quota_exhausted"]}),
    ("alert_account_cooldown", "Account cooldown", "account_status", "warning", {"statuses": ["cooldown"]}),
    ("alert_job_failed", "Media job failed", "job_failed", "error", {"error_codes": ["PROVIDER_FAILED", "PROVIDER_CONFIG_INVALID", "UNSUPPORTED_MODEL_OPERATION"]}),
    ("alert_provider_health_failed", "Provider health failed", "provider_health", "warning", {"statuses": ["failed", "cooldown", "disabled"]}),
    ("alert_high_cost_job", "High cost job", "high_cost_job", "warning", {"min_amount": 500}),
    ("alert_safety_rejected", "Safety policy rejected", "safety_rejected", "warning", {}),
    ("alert_circuit_open", "Circuit breaker opened", "circuit_open", "warning", {}),
    ("alert_usage_anomaly", "Usage anomaly detected", "usage_anomaly", "warning", {}),
]


SAFETY_POLICIES = [
    (
        "safety_block_smoke_marker",
        "Smoke-test safety rejection marker",
        "global",
        "",
        "",
        "reject",
        "warning",
        ["media2api_forbidden_test"],
        {},
        "Narrow default marker used to validate safety hooks; replace or extend in production.",
    ),
]


USER_LIMIT_POLICIES = [
    (
        "limit_default",
        "Default platform usage limits",
        "",
        "",
        600,
        10000,
        100,
        [],
        ["i2v-pro", "video-extend"],
        True,
        "Default limits for API rate, daily media jobs, concurrent jobs, and high-cost model allowlisting.",
    ),
]


def seed_defaults(db: Session) -> None:
    user = db.get(models.User, "usr_admin")
    if not user:
        user = models.User(id="usr_admin", email=settings.default_user_email, tier="admin", wallet_balance=100000)
        db.add(user)
    else:
        user.tier = "admin"
        user.status = "active"

    key_hash = hash_api_key(settings.bootstrap_api_key)
    api_key = db.query(models.ApiKey).filter(models.ApiKey.key_hash == key_hash).first()
    if not api_key:
        db.add(models.ApiKey(id="key_admin", user_id="usr_admin", name="bootstrap", key_hash=key_hash))

    for model_id, display, operations, billing_class in LOGICAL_MODELS:
        item = db.get(models.LogicalModel, model_id)
        if not item:
            db.add(
                models.LogicalModel(
                    id=model_id,
                    display_name=display,
                    operations_json=dumps(operations),
                    constraints_json=dumps({"max_prompt_length": 8000, "supports_asset_ids": True}),
                    default_params_json=dumps({"quality": "standard"}),
                    billing_class=billing_class,
                    enabled=True,
                )
            )

    for provider_id, name, adapter_type, status, notes in PROVIDERS:
        item = db.get(models.Provider, provider_id)
        if not item:
            db.add(
                models.Provider(
                    id=provider_id,
                    name=name,
                    adapter_type=adapter_type,
                    status=status if provider_id == "mock" else "active",
                    base_config_json=dumps({}),
                    notes=notes,
                )
            )
        elif provider_id != "mock":
            item.status = "active"

    db.flush()

    for logical, provider, provider_model, operations, weight, speed, reliability, quality in MOCK_MAPPINGS:
        mapping_id = f"{logical}:{provider}:{provider_model}"
        item = db.get(models.ProviderModelMapping, mapping_id)
        if not item:
            db.add(
                models.ProviderModelMapping(
                    id=mapping_id,
                    logical_model=logical,
                    provider_id=provider,
                    provider_model=provider_model,
                    operations_json=dumps(operations),
                    priority=1,
                    weight=weight,
                    cost_score=0.9,
                    speed_score=speed,
                    reliability_score=reliability,
                    quality_score=quality,
                    enabled=True,
                )
            )

    account = db.get(models.AccountResource, "acct_mock_default")
    if not account:
        db.add(
            models.AccountResource(
                id="acct_mock_default",
                provider_id="mock",
                label="Mock Default Account",
                credential_ref="secret://mock/default",
                supported_operations_json=dumps(list(OPERATIONS.values())),
                supported_provider_models_json=dumps([m[2] for m in MOCK_MAPPINGS]),
                quota_buckets_json=dumps([{"type": "credits", "remaining_estimate": 999999, "confidence": 1.0}]),
                concurrency_limit=100,
                status="active",
                plan="mock",
            )
        )

    multipliers = dumps({"standard": 1, "high": 2, "pro": 2, "hd": 2})
    for rule_id, name, logical_model, billing_class, operation, unit, base, unit_amount, input_amount, provider_base, provider_unit, provider_input in PRICING_RULES:
        rule = db.get(models.PricingRule, rule_id)
        if not rule:
            db.add(
                models.PricingRule(
                    id=rule_id,
                    name=name,
                    logical_model=logical_model,
                    billing_class=billing_class,
                    operation=operation,
                    unit=unit,
                    base_amount=base,
                    unit_amount=unit_amount,
                    input_asset_amount=input_amount,
                    provider_cost_base=provider_base,
                    provider_cost_unit=provider_unit,
                    provider_cost_input_asset=provider_input,
                    quality_multipliers_json=multipliers,
                    currency="credits",
                    enabled=True,
                )
            )

    for rule_id, name, event_type, severity, condition in ALERT_RULES:
        rule = db.get(models.AlertRule, rule_id)
        if not rule:
            db.add(
                models.AlertRule(
                    id=rule_id,
                    name=name,
                    event_type=event_type,
                    severity=severity,
                    condition_json=dumps(condition),
                    enabled=True,
                )
            )

    for policy_id, name, scope, logical_model, operation, action, severity, terms, pattern, notes in SAFETY_POLICIES:
        policy = db.get(models.SafetyPolicy, policy_id)
        if not policy:
            db.add(
                models.SafetyPolicy(
                    id=policy_id,
                    name=name,
                    scope=scope,
                    logical_model=logical_model,
                    operation=operation,
                    action=action,
                    severity=severity,
                    match_type="term",
                    terms_json=dumps(terms),
                    pattern_json=dumps(pattern),
                    enabled=True,
                    notes=notes,
                )
            )

    for policy_id, name, user_id, tier, rpm, daily, concurrent, allowed_models, high_cost_models, high_cost_allowed, notes in USER_LIMIT_POLICIES:
        policy = db.get(models.UserLimitPolicy, policy_id)
        if not policy:
            db.add(
                models.UserLimitPolicy(
                    id=policy_id,
                    name=name,
                    user_id=user_id,
                    tier=tier,
                    requests_per_minute=rpm,
                    daily_job_limit=daily,
                    concurrent_job_limit=concurrent,
                    allowed_models_json=dumps(allowed_models),
                    high_cost_models_json=dumps(high_cost_models),
                    high_cost_allowed=high_cost_allowed,
                    enabled=True,
                    notes=notes,
                )
            )

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
