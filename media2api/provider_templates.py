from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MappingTemplate:
    logical_model: str
    provider_model: str
    operations: list[str]
    priority: int = 50
    cost_score: float = 0.5
    speed_score: float = 0.5
    quality_score: float = 0.5
    reliability_score: float = 0.5


@dataclass(frozen=True)
class ProviderTemplate:
    id: str
    name: str
    adapter_type: str
    models: list[str]
    operations: list[str]
    default_config: dict[str, Any]
    mappings: list[MappingTemplate]
    notes: str


OPS = {
    "t2i": "text_to_image",
    "i2i": "image_to_image",
    "edit": "image_edit",
    "t2v": "text_to_video",
    "i2v": "image_to_video",
    "extend": "video_extend",
}


PROVIDER_TEMPLATES: dict[str, ProviderTemplate] = {
    "openai_image": ProviderTemplate(
        id="openai_image",
        name="OpenAI / ChatGPT / Codex image connector",
        adapter_type="http_adapter",
        models=["gpt-image-2", "codex-gpt-image-2"],
        operations=[OPS["t2i"], OPS["i2i"], OPS["edit"]],
        default_config={
            "base_url": "http://127.0.0.1:18090",
            "health_endpoint": "/health",
            "endpoints": {
                OPS["t2i"]: "/v1/images/generations",
                OPS["edit"]: "/v1/images/edits",
                OPS["i2i"]: "/v1/images/edits",
            },
        },
        mappings=[
            MappingTemplate("t2i-pro", "gpt-image-2", [OPS["t2i"]], priority=10, quality_score=0.9, reliability_score=0.7),
            MappingTemplate("image-edit", "gpt-image-2", [OPS["edit"], OPS["i2i"]], priority=10, quality_score=0.9, reliability_score=0.7),
        ],
        notes="Configure this with an already-authorized image connector base_url.",
    ),
    "gemini": ProviderTemplate(
        id="gemini",
        name="Gemini / AI Studio connector",
        adapter_type="http_adapter",
        models=["veo-3.1", "nano-banana", "nano-banana-pro", "imagen-4"],
        operations=[OPS["t2i"], OPS["i2i"], OPS["edit"], OPS["t2v"], OPS["i2v"]],
        default_config={
            "base_url": "http://127.0.0.1:18091",
            "health_endpoint": "/health",
            "endpoints": {
                OPS["t2i"]: "/v1/images/generations",
                OPS["edit"]: "/v1/images/edits",
                OPS["i2i"]: "/v1/images/edits",
                OPS["t2v"]: "/v1/videos/generations",
                OPS["i2v"]: "/v1/videos/generations",
            },
            "poll_timeout_seconds": 900,
        },
        mappings=[
            MappingTemplate("t2i-pro", "nano-banana-pro", [OPS["t2i"]], priority=20, quality_score=0.85, reliability_score=0.65),
            MappingTemplate("image-edit", "nano-banana-pro", [OPS["edit"], OPS["i2i"]], priority=20, quality_score=0.85, reliability_score=0.65),
            MappingTemplate("i2v-pro", "veo-3.1", [OPS["i2v"]], priority=30, quality_score=0.9, reliability_score=0.55),
            MappingTemplate("t2v-general", "veo-3.1", [OPS["t2v"]], priority=30, quality_score=0.9, reliability_score=0.55),
        ],
        notes="Use for Gemini/Nano Banana/Veo sidecars. Video requires long polling.",
    ),
    "grok": ProviderTemplate(
        id="grok",
        name="Grok Imagine connector",
        adapter_type="http_adapter",
        models=["grok-imagine-image", "grok-imagine-video"],
        operations=[OPS["t2i"], OPS["i2i"], OPS["t2v"], OPS["i2v"]],
        default_config={
            "base_url": "http://127.0.0.1:18092",
            "health_endpoint": "/health",
            "poll_timeout_seconds": 600,
        },
        mappings=[
            MappingTemplate("t2i-pro", "grok-imagine-image", [OPS["t2i"]], priority=20, quality_score=0.8, reliability_score=0.65),
            MappingTemplate("i2v-fast", "grok-imagine-video", [OPS["i2v"]], priority=20, speed_score=0.75, quality_score=0.7),
            MappingTemplate("t2v-general", "grok-imagine-video", [OPS["t2v"]], priority=10, speed_score=0.75, quality_score=0.7),
        ],
        notes="Use for Grok image/video connectors.",
    ),
    "qwen": ProviderTemplate(
        id="qwen",
        name="Qwen / Tongyi connector",
        adapter_type="http_adapter",
        models=["qwen-image", "qwen-image-edit", "qwen-video", "wan-video"],
        operations=[OPS["t2i"], OPS["i2i"], OPS["edit"], OPS["t2v"], OPS["i2v"]],
        default_config={
            "base_url": "http://127.0.0.1:18093",
            "health_endpoint": "/health",
            "poll_timeout_seconds": 600,
        },
        mappings=[
            MappingTemplate("t2i-fast", "qwen-image", [OPS["t2i"]], priority=20, speed_score=0.8, cost_score=0.8),
            MappingTemplate("image-edit", "qwen-image-edit", [OPS["edit"], OPS["i2i"]], priority=30, speed_score=0.7),
            MappingTemplate("i2v-fast", "qwen-video", [OPS["i2v"]], priority=30, speed_score=0.65),
            MappingTemplate("t2v-general", "qwen-video", [OPS["t2v"]], priority=40, speed_score=0.65),
        ],
        notes="Use for Qwen image/video compatible sidecars.",
    ),
    "jimeng": ProviderTemplate(
        id="jimeng",
        name="Jimeng / Dreamina / Seedream / Seedance connector",
        adapter_type="http_adapter",
        models=["seedream", "seededit", "seedance-i2v", "seedance-t2v"],
        operations=[OPS["t2i"], OPS["i2i"], OPS["edit"], OPS["t2v"], OPS["i2v"]],
        default_config={
            "base_url": "http://127.0.0.1:18094",
            "health_endpoint": "/health",
            "poll_timeout_seconds": 600,
        },
        mappings=[
            MappingTemplate("t2i-fast", "seedream", [OPS["t2i"]], priority=10, speed_score=0.85, cost_score=0.8),
            MappingTemplate("image-edit", "seededit", [OPS["edit"], OPS["i2i"]], priority=30, speed_score=0.75),
            MappingTemplate("i2v-fast", "seedance-i2v", [OPS["i2v"]], priority=10, speed_score=0.85, cost_score=0.75),
            MappingTemplate("i2v-pro", "seedance-i2v", [OPS["i2v"]], priority=20, quality_score=0.75),
            MappingTemplate("t2v-general", "seedance-t2v", [OPS["t2v"]], priority=20, speed_score=0.75),
        ],
        notes="Recommended first real mixed media connector when a lawful account-sidecar is available.",
    ),
    "kling": ProviderTemplate(
        id="kling",
        name="Kling video connector",
        adapter_type="http_adapter",
        models=["kling-i2v-standard", "kling-i2v-hq", "kling-t2v", "kling-extend"],
        operations=[OPS["t2v"], OPS["i2v"], OPS["extend"]],
        default_config={"base_url": "http://127.0.0.1:18095", "health_endpoint": "/health", "poll_timeout_seconds": 1200},
        mappings=[
            MappingTemplate("i2v-pro", "kling-i2v-hq", [OPS["i2v"]], priority=10, quality_score=0.9, reliability_score=0.6),
            MappingTemplate("t2v-general", "kling-t2v", [OPS["t2v"]], priority=35, quality_score=0.8),
            MappingTemplate("video-extend", "kling-extend", [OPS["extend"]], priority=25, quality_score=0.8),
        ],
        notes="High-quality video connector template.",
    ),
    "luma": ProviderTemplate(
        id="luma",
        name="Luma Dream Machine connector",
        adapter_type="http_adapter",
        models=["luma-dream-machine", "luma-extend"],
        operations=[OPS["t2v"], OPS["i2v"], OPS["extend"]],
        default_config={"base_url": "http://127.0.0.1:18096", "health_endpoint": "/health", "poll_timeout_seconds": 1200},
        mappings=[
            MappingTemplate("i2v-pro", "luma-dream-machine", [OPS["i2v"]], priority=30, quality_score=0.85),
            MappingTemplate("t2v-general", "luma-dream-machine", [OPS["t2v"]], priority=25, quality_score=0.85),
            MappingTemplate("video-extend", "luma-extend", [OPS["extend"]], priority=10, quality_score=0.85),
        ],
        notes="Video generation and extension connector template.",
    ),
    "runway": ProviderTemplate(
        id="runway",
        name="Runway video connector",
        adapter_type="http_adapter",
        models=["runway-gen3", "runway-gen4", "runway-extend"],
        operations=[OPS["t2v"], OPS["i2v"], OPS["extend"]],
        default_config={"base_url": "http://127.0.0.1:18097", "health_endpoint": "/health", "poll_timeout_seconds": 1200},
        mappings=[
            MappingTemplate("i2v-pro", "runway-gen4", [OPS["i2v"]], priority=40, quality_score=0.85),
            MappingTemplate("t2v-general", "runway-gen4", [OPS["t2v"]], priority=40, quality_score=0.85),
            MappingTemplate("video-extend", "runway-extend", [OPS["extend"]], priority=20, quality_score=0.8),
        ],
        notes="Late-stage video connector template.",
    ),
    "midjourney": ProviderTemplate(
        id="midjourney",
        name="Midjourney connector",
        adapter_type="http_adapter",
        models=["mj-v6", "mj-v7", "niji"],
        operations=[OPS["t2i"], OPS["i2i"]],
        default_config={"base_url": "http://127.0.0.1:18098", "health_endpoint": "/health", "poll_timeout_seconds": 1200},
        mappings=[
            MappingTemplate("image-variation", "mj-v7", [OPS["i2i"]], priority=10, quality_score=0.9),
            MappingTemplate("t2i-pro", "mj-v7", [OPS["t2i"]], priority=50, quality_score=0.9),
        ],
        notes="Late-stage image/design connector template; use strict concurrency limits.",
    ),
    "pollinations": ProviderTemplate(
        id="pollinations",
        name="Pollinations direct aggregator",
        adapter_type="aggregator_adapter",
        models=["gpt-image-2", "nanobanana", "seedream", "qwen-image", "grok-imagine", "veo", "seedance", "wan"],
        operations=[OPS["t2i"], OPS["i2i"], OPS["t2v"], OPS["i2v"]],
        default_config={"base_url": "https://gen.pollinations.ai", "api_key_ref": "env://POLLINATIONS_KEY", "health_timeout_seconds": 10, "timeout_seconds": 300, "max_reference_assets": 2},
        mappings=[
            MappingTemplate("t2i-fast", "seedream", [OPS["t2i"]], priority=60, cost_score=0.7),
            MappingTemplate("t2i-pro", "gpt-image-2", [OPS["t2i"]], priority=60, quality_score=0.75),
            MappingTemplate("i2v-fast", "seedance", [OPS["i2v"]], priority=60, speed_score=0.7),
            MappingTemplate("t2v-general", "veo", [OPS["t2v"]], priority=60, quality_score=0.75),
        ],
        notes="Direct third-party aggregator adapter. Generation endpoints require a Pollinations API key via env://POLLINATIONS_KEY or a secret-backed account credential.",
    ),
    "openrouter_image": ProviderTemplate(
        id="openrouter_image",
        name="OpenRouter image aggregator connector",
        adapter_type="http_adapter",
        models=["gpt-image", "nano-banana", "seedream", "recraft", "flux", "qwen-image"],
        operations=[OPS["t2i"], OPS["i2i"]],
        default_config={"base_url": "http://127.0.0.1:18100", "health_endpoint": "/health", "poll_timeout_seconds": 600},
        mappings=[
            MappingTemplate("t2i-pro", "gpt-image", [OPS["t2i"]], priority=70, quality_score=0.8, reliability_score=0.65),
            MappingTemplate("t2i-fast", "qwen-image", [OPS["t2i"]], priority=70, speed_score=0.75, cost_score=0.65),
            MappingTemplate("image-variation", "seedream", [OPS["i2i"]], priority=70, quality_score=0.7),
        ],
        notes="Commercial image-model fallback template; configure with a third-party aggregator endpoint.",
    ),
    "fal_replicate": ProviderTemplate(
        id="fal_replicate",
        name="fal / Replicate marketplace connector",
        adapter_type="http_adapter",
        models=["nano-banana", "qwen-image", "seedream", "flux", "recraft", "wan-video"],
        operations=[OPS["t2i"], OPS["i2i"], OPS["t2v"], OPS["i2v"]],
        default_config={"base_url": "http://127.0.0.1:18101", "health_endpoint": "/health", "poll_timeout_seconds": 1200},
        mappings=[
            MappingTemplate("t2i-fast", "qwen-image", [OPS["t2i"]], priority=80, cost_score=0.65),
            MappingTemplate("t2i-pro", "flux", [OPS["t2i"]], priority=80, quality_score=0.8),
            MappingTemplate("image-variation", "seedream", [OPS["i2i"]], priority=80, quality_score=0.7),
            MappingTemplate("i2v-fast", "wan-video", [OPS["i2v"]], priority=80, speed_score=0.65),
            MappingTemplate("t2v-general", "wan-video", [OPS["t2v"]], priority=80, speed_score=0.65),
        ],
        notes="Commercial marketplace fallback template; map each upstream model to a logical model before enabling.",
    ),
    "seedream_proxy": ProviderTemplate(
        id="seedream_proxy",
        name="Seedream third-party proxy connector",
        adapter_type="http_adapter",
        models=["seedream-3", "seedream-4", "seedream-5", "seededit"],
        operations=[OPS["t2i"], OPS["i2i"], OPS["edit"]],
        default_config={"base_url": "http://127.0.0.1:18102", "health_endpoint": "/health", "poll_timeout_seconds": 600},
        mappings=[
            MappingTemplate("t2i-fast", "seedream-4", [OPS["t2i"]], priority=65, speed_score=0.75, cost_score=0.7),
            MappingTemplate("t2i-pro", "seedream-5", [OPS["t2i"]], priority=65, quality_score=0.8),
            MappingTemplate("image-edit", "seededit", [OPS["edit"], OPS["i2i"]], priority=65, quality_score=0.75),
        ],
        notes="Seedream/Seededit fallback connector template for third-party proxy resources.",
    ),
    "amux_qwen": ProviderTemplate(
        id="amux_qwen",
        name="AMUX / Qwen image connector",
        adapter_type="http_adapter",
        models=["qwen-image", "qwen-image-edit", "wan-image"],
        operations=[OPS["t2i"], OPS["i2i"]],
        default_config={"base_url": "http://127.0.0.1:18103", "health_endpoint": "/health", "poll_timeout_seconds": 600},
        mappings=[
            MappingTemplate("t2i-fast", "qwen-image", [OPS["t2i"]], priority=75, speed_score=0.8, cost_score=0.7),
            MappingTemplate("t2i-pro", "qwen-image", [OPS["t2i"]], priority=75, quality_score=0.75),
            MappingTemplate("image-variation", "wan-image", [OPS["i2i"]], priority=75, quality_score=0.7),
        ],
        notes="Qwen image fallback template for third-party image connector resources.",
    ),
    "flux_stability": ProviderTemplate(
        id="flux_stability",
        name="Flux / Stable Image connector",
        adapter_type="http_adapter",
        models=["flux", "sdxl", "stable-image", "controlnet"],
        operations=[OPS["t2i"], OPS["i2i"], OPS["edit"]],
        default_config={"base_url": "http://127.0.0.1:18104", "health_endpoint": "/health", "poll_timeout_seconds": 600},
        mappings=[
            MappingTemplate("t2i-fast", "flux", [OPS["t2i"]], priority=90, cost_score=0.75),
            MappingTemplate("t2i-pro", "stable-image", [OPS["t2i"]], priority=90, quality_score=0.75),
            MappingTemplate("image-edit", "controlnet", [OPS["edit"], OPS["i2i"]], priority=90, quality_score=0.7),
        ],
        notes="Cost-optimized self-hosted or third-party image fallback template.",
    ),
}


def template_as_dict(template: ProviderTemplate) -> dict[str, Any]:
    return {
        "id": template.id,
        "name": template.name,
        "adapter_type": template.adapter_type,
        "models": template.models,
        "operations": template.operations,
        "default_config": template.default_config,
        "mappings": [
            {
                "logical_model": item.logical_model,
                "provider_model": item.provider_model,
                "operations": item.operations,
                "priority": item.priority,
                "cost_score": item.cost_score,
                "speed_score": item.speed_score,
                "quality_score": item.quality_score,
                "reliability_score": item.reliability_score,
            }
            for item in template.mappings
        ],
        "notes": template.notes,
    }
