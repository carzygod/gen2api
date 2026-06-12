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
        notes="Configure this with an authorized Web Cookie or Codex Agent resource; runner base_url is optional.",
    ),
    "openai_web_session": ProviderTemplate(
        id="openai_web_session",
        name="OpenAI / ChatGPT Web session image connector",
        adapter_type="http_adapter",
        models=["gpt-image-2", "chatgpt-image"],
        operations=[OPS["t2i"], OPS["i2i"], OPS["edit"]],
        default_config={
            "health_endpoint": "/health",
            "endpoints": {
                OPS["t2i"]: "/v1/images/generations",
                OPS["edit"]: "/v1/images/edits",
                OPS["i2i"]: "/v1/images/edits",
            },
            "kernel_selection": "OAI-WEB-01",
        },
        mappings=[
            MappingTemplate("t2i-pro", "gpt-image-2", [OPS["t2i"]], priority=10, quality_score=0.9, reliability_score=0.72),
            MappingTemplate("image-edit", "gpt-image-2", [OPS["edit"], OPS["i2i"]], priority=10, quality_score=0.9, reliability_score=0.72),
        ],
        notes="Selected kernel OAI-WEB-01. Use only ChatGPT Web cookie/session material; do not mix with Codex accounts.",
    ),
    "openai_codex": ProviderTemplate(
        id="openai_codex",
        name="OpenAI Codex GPT Image connector",
        adapter_type="http_adapter",
        models=["gpt-image-2", "codex-gpt-image-2"],
        operations=[OPS["t2i"], OPS["i2i"], OPS["edit"]],
        default_config={
            "health_endpoint": "/health",
            "endpoints": {
                OPS["t2i"]: "/v1/images/generations",
                OPS["edit"]: "/v1/images/edits",
                OPS["i2i"]: "/v1/images/edits",
            },
            "kernel_selection": "OAI-CODEX-04",
        },
        mappings=[
            MappingTemplate("t2i-pro", "gpt-image-2", [OPS["t2i"]], priority=12, quality_score=0.9, reliability_score=0.7),
            MappingTemplate("image-edit", "gpt-image-2", [OPS["edit"], OPS["i2i"]], priority=12, quality_score=0.88, reliability_score=0.68),
        ],
        notes="Selected kernel OAI-CODEX-04. Use Codex OAuth/profile/account export material; do not mix with ChatGPT Web cookies.",
    ),
    "gemini": ProviderTemplate(
        id="gemini",
        name="Gemini / AI Studio connector",
        adapter_type="http_adapter",
        models=["veo-3.1", "nano-banana", "nano-banana-pro", "imagen-4"],
        operations=[OPS["t2i"], OPS["i2i"], OPS["edit"], OPS["t2v"], OPS["i2v"]],
        default_config={
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
    "gemini_cli_oauth": ProviderTemplate(
        id="gemini_cli_oauth",
        name="Gemini CLI OAuth image/video connector",
        adapter_type="http_adapter",
        models=["nano-banana", "nano-banana-pro", "veo-3.1", "imagen-4"],
        operations=[OPS["t2i"], OPS["i2i"], OPS["edit"], OPS["t2v"], OPS["i2v"]],
        default_config={
            "health_endpoint": "/v1/models",
            "poll_timeout_seconds": 900,
            "endpoints": {
                OPS["t2i"]: "/v1/images/generations",
                OPS["edit"]: "/v1/images/edits",
                OPS["i2i"]: "/v1/images/edits",
                OPS["t2v"]: "/v1/videos/generations",
                OPS["i2v"]: "/v1/videos/generations",
            },
            "kernel_selection": "GEM-CLI-02",
        },
        mappings=[
            MappingTemplate("t2i-pro", "nano-banana-pro", [OPS["t2i"]], priority=22, quality_score=0.85, reliability_score=0.65),
            MappingTemplate("image-edit", "nano-banana-pro", [OPS["edit"], OPS["i2i"]], priority=22, quality_score=0.85, reliability_score=0.65),
            MappingTemplate("i2v-pro", "veo-3.1", [OPS["i2v"]], priority=32, quality_score=0.9, reliability_score=0.55),
            MappingTemplate("t2v-general", "veo-3.1", [OPS["t2v"]], priority=32, quality_score=0.9, reliability_score=0.55),
        ],
        notes="Selected kernel GEM-CLI-02. Use only Gemini CLI OAuth/profile material; do not mix with Gemini Web sessions.",
    ),
    "gemini_web_session": ProviderTemplate(
        id="gemini_web_session",
        name="Gemini Web session image/video connector",
        adapter_type="http_adapter",
        models=["nano-banana", "nano-banana-pro", "veo-3.1", "imagen-4"],
        operations=[OPS["t2i"], OPS["i2i"], OPS["edit"], OPS["t2v"], OPS["i2v"]],
        default_config={
            "health_endpoint": "/health",
            "poll_timeout_seconds": 900,
            "endpoints": {
                OPS["t2i"]: "/v1/images/generations",
                OPS["edit"]: "/v1/images/edits",
                OPS["i2i"]: "/v1/images/edits",
                OPS["t2v"]: "/v1/videos/generations",
                OPS["i2v"]: "/v1/videos/generations",
            },
            "kernel_selection": "GEM-WEB-01",
        },
        mappings=[
            MappingTemplate("t2i-pro", "nano-banana-pro", [OPS["t2i"]], priority=21, quality_score=0.86, reliability_score=0.66),
            MappingTemplate("image-edit", "nano-banana-pro", [OPS["edit"], OPS["i2i"]], priority=21, quality_score=0.86, reliability_score=0.66),
            MappingTemplate("i2v-pro", "veo-3.1", [OPS["i2v"]], priority=31, quality_score=0.9, reliability_score=0.56),
            MappingTemplate("t2v-general", "veo-3.1", [OPS["t2v"]], priority=31, quality_score=0.9, reliability_score=0.56),
        ],
        notes="Selected kernel GEM-WEB-01. Use only Gemini Web cookie/session material; do not mix with CLI OAuth profiles.",
    ),
    "antigravity": ProviderTemplate(
        id="antigravity",
        name="Antigravity Agent connector",
        adapter_type="http_adapter",
        models=["antigravity-agent"],
        operations=[OPS["t2i"], OPS["i2i"], OPS["edit"], OPS["t2v"], OPS["i2v"]],
        default_config={"health_endpoint": "/health", "poll_timeout_seconds": 900, "kernel_selection": "AG-01"},
        mappings=[
            MappingTemplate("t2i-pro", "antigravity-agent", [OPS["t2i"]], priority=45, quality_score=0.7, reliability_score=0.5),
            MappingTemplate("image-edit", "antigravity-agent", [OPS["edit"], OPS["i2i"]], priority=45, quality_score=0.7, reliability_score=0.5),
            MappingTemplate("t2v-general", "antigravity-agent", [OPS["t2v"]], priority=55, quality_score=0.7, reliability_score=0.5),
            MappingTemplate("i2v-pro", "antigravity-agent", [OPS["i2v"]], priority=55, quality_score=0.7, reliability_score=0.5),
        ],
        notes="Selected kernel AG-01. Keep Antigravity OAuth/profile resources separate from Gemini CLI and Gemini Web.",
    ),
    "grok": ProviderTemplate(
        id="grok",
        name="Grok Imagine connector",
        adapter_type="http_adapter",
        models=["grok-imagine-image", "grok-imagine-video"],
        operations=[OPS["t2i"], OPS["i2i"], OPS["t2v"], OPS["i2v"]],
        default_config={
            "health_endpoint": "/health",
            "poll_timeout_seconds": 600,
            "endpoints": {
                OPS["t2i"]: "/v1/images/generations",
                OPS["i2i"]: "/v1/images/edits",
                OPS["t2v"]: "/v1/videos/generations",
                OPS["i2v"]: "/v1/videos/generations",
            },
        },
        mappings=[
            MappingTemplate("t2i-pro", "grok-imagine-image", [OPS["t2i"]], priority=20, quality_score=0.8, reliability_score=0.65),
            MappingTemplate("image-edit", "grok-imagine-image", [OPS["i2i"]], priority=25, quality_score=0.78, reliability_score=0.6),
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
    "qwen_ai_web_session": ProviderTemplate(
        id="qwen_ai_web_session",
        name="Qwen.ai Web session image/video connector",
        adapter_type="http_adapter",
        models=["qwen-image", "qwen-image-edit", "qwen-video"],
        operations=[OPS["t2i"], OPS["i2i"], OPS["edit"], OPS["t2v"], OPS["i2v"]],
        default_config={"health_endpoint": "/health", "poll_timeout_seconds": 900, "kernel_selection": "QWEN-AI-01"},
        mappings=[
            MappingTemplate("t2i-fast", "qwen-image", [OPS["t2i"]], priority=18, speed_score=0.8, cost_score=0.75),
            MappingTemplate("image-edit", "qwen-image-edit", [OPS["edit"], OPS["i2i"]], priority=25, speed_score=0.75),
            MappingTemplate("t2v-general", "qwen-video", [OPS["t2v"]], priority=35, speed_score=0.68),
            MappingTemplate("i2v-fast", "qwen-video", [OPS["i2v"]], priority=35, speed_score=0.68),
        ],
        notes="Selected kernel QWEN-AI-01 for qwen.ai/chat.qwen.ai/portal.qwen.ai. Do not share accounts with qianwen.com.",
    ),
    "qianwen_web_session": ProviderTemplate(
        id="qianwen_web_session",
        name="Qianwen.com Web session connector",
        adapter_type="http_adapter",
        models=["qianwen-image", "qianwen-video"],
        operations=[OPS["t2i"], OPS["i2i"], OPS["edit"], OPS["t2v"], OPS["i2v"]],
        default_config={"health_endpoint": "/health", "poll_timeout_seconds": 900, "kernel_selection": "QIANWEN-WEB-01"},
        mappings=[
            MappingTemplate("t2i-fast", "qianwen-image", [OPS["t2i"]], priority=45, speed_score=0.65, cost_score=0.65),
            MappingTemplate("image-edit", "qianwen-image", [OPS["edit"], OPS["i2i"]], priority=50, speed_score=0.6),
            MappingTemplate("t2v-general", "qianwen-video", [OPS["t2v"]], priority=60, speed_score=0.55),
            MappingTemplate("i2v-fast", "qianwen-video", [OPS["i2v"]], priority=60, speed_score=0.55),
        ],
        notes="Selected kernel QIANWEN-WEB-01 for qianwen.com/Tongyi Qianwen Web. Media endpoints require live validation before enabling for production traffic.",
    ),
    "jimeng": ProviderTemplate(
        id="jimeng",
        name="Jimeng / Dreamina / Seedream / Seedance connector",
        adapter_type="http_adapter",
        models=["seedream", "seededit", "seedance-i2v", "seedance-t2v"],
        operations=[OPS["t2i"], OPS["i2i"], OPS["edit"], OPS["t2v"], OPS["i2v"]],
        default_config={
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
    "jimeng_web_session": ProviderTemplate(
        id="jimeng_web_session",
        name="Jimeng / Dreamina Web session image connector",
        adapter_type="http_adapter",
        models=["jimeng-image", "dreamina-image"],
        operations=[OPS["t2i"], OPS["i2i"], OPS["edit"]],
        default_config={"health_endpoint": "/health", "poll_timeout_seconds": 600, "kernel_selection": "JM-01"},
        mappings=[
            MappingTemplate("t2i-fast", "jimeng-image", [OPS["t2i"]], priority=10, speed_score=0.85, cost_score=0.8),
            MappingTemplate("image-edit", "jimeng-image", [OPS["edit"], OPS["i2i"]], priority=30, speed_score=0.75),
        ],
        notes="Selected kernel JM-01. Keep Jimeng/Dreamina accounts separate from Doubao daily quota pools.",
    ),
    "doubao_web_session": ProviderTemplate(
        id="doubao_web_session",
        name="Doubao Web session image/video connector",
        adapter_type="http_adapter",
        models=["doubao-image", "doubao-video"],
        operations=[OPS["t2i"], OPS["i2i"], OPS["edit"], OPS["t2v"], OPS["i2v"]],
        default_config={"health_endpoint": "/health", "poll_timeout_seconds": 900, "kernel_selection": "DOUBAO-WEB-01"},
        mappings=[
            MappingTemplate("t2i-fast", "doubao-image", [OPS["t2i"]], priority=15, speed_score=0.82, cost_score=0.75),
            MappingTemplate("image-edit", "doubao-image", [OPS["edit"], OPS["i2i"]], priority=30, speed_score=0.75),
            MappingTemplate("t2v-general", "doubao-video", [OPS["t2v"]], priority=25, speed_score=0.72, quality_score=0.72),
            MappingTemplate("i2v-fast", "doubao-video", [OPS["i2v"]], priority=25, speed_score=0.72, quality_score=0.72),
        ],
        notes="Selected kernel DOUBAO-WEB-01. Doubao account pools and daily quotas must stay separate from Jimeng/Dreamina.",
    ),
    "kling": ProviderTemplate(
        id="kling",
        name="Kling video connector",
        adapter_type="http_adapter",
        models=["kling-i2v-standard", "kling-i2v-hq", "kling-t2v", "kling-extend"],
        operations=[OPS["t2v"], OPS["i2v"], OPS["extend"]],
        default_config={"health_endpoint": "/health", "poll_timeout_seconds": 1200},
        mappings=[
            MappingTemplate("i2v-pro", "kling-i2v-hq", [OPS["i2v"]], priority=10, quality_score=0.9, reliability_score=0.6),
            MappingTemplate("t2v-general", "kling-t2v", [OPS["t2v"]], priority=35, quality_score=0.8),
            MappingTemplate("video-extend", "kling-extend", [OPS["extend"]], priority=25, quality_score=0.8),
        ],
        notes="High-quality video connector template.",
    ),
    "kling_web_session": ProviderTemplate(
        id="kling_web_session",
        name="Kling Web session video connector",
        adapter_type="http_adapter",
        models=["kling-i2v-standard", "kling-i2v-hq", "kling-t2v", "kling-extend"],
        operations=[OPS["t2v"], OPS["i2v"], OPS["extend"]],
        default_config={"health_endpoint": "/health", "poll_timeout_seconds": 1200, "kernel_selection": "KLING-WEB-01"},
        mappings=[
            MappingTemplate("i2v-pro", "kling-i2v-hq", [OPS["i2v"]], priority=10, quality_score=0.9, reliability_score=0.6),
            MappingTemplate("t2v-general", "kling-t2v", [OPS["t2v"]], priority=35, quality_score=0.8),
            MappingTemplate("video-extend", "kling-extend", [OPS["extend"]], priority=25, quality_score=0.8),
        ],
        notes="Selected kernel KLING-WEB-01. Use Kling Web/session material instead of official API keys for this phase.",
    ),
    "luma": ProviderTemplate(
        id="luma",
        name="Luma Dream Machine connector",
        adapter_type="http_adapter",
        models=["luma-dream-machine", "luma-extend"],
        operations=[OPS["t2v"], OPS["i2v"], OPS["extend"]],
        default_config={"health_endpoint": "/health", "poll_timeout_seconds": 1200},
        mappings=[
            MappingTemplate("i2v-pro", "luma-dream-machine", [OPS["i2v"]], priority=30, quality_score=0.85),
            MappingTemplate("t2v-general", "luma-dream-machine", [OPS["t2v"]], priority=25, quality_score=0.85),
            MappingTemplate("video-extend", "luma-extend", [OPS["extend"]], priority=10, quality_score=0.85),
        ],
        notes="Video generation and extension connector template.",
    ),
    "luma_web_session": ProviderTemplate(
        id="luma_web_session",
        name="Luma Web session video connector",
        adapter_type="http_adapter",
        models=["luma-dream-machine", "luma-extend"],
        operations=[OPS["t2v"], OPS["i2v"], OPS["extend"]],
        default_config={"health_endpoint": "/health", "poll_timeout_seconds": 1200, "kernel_selection": "LUMA-WEB-01"},
        mappings=[
            MappingTemplate("i2v-pro", "luma-dream-machine", [OPS["i2v"]], priority=30, quality_score=0.85),
            MappingTemplate("t2v-general", "luma-dream-machine", [OPS["t2v"]], priority=25, quality_score=0.85),
            MappingTemplate("video-extend", "luma-extend", [OPS["extend"]], priority=10, quality_score=0.85),
        ],
        notes="Selected kernel LUMA-WEB-01. Use Luma Web cookie/session material; official SDK/API-key routes are excluded.",
    ),
    "runway": ProviderTemplate(
        id="runway",
        name="Runway video connector",
        adapter_type="http_adapter",
        models=["runway-gen3", "runway-gen4", "runway-extend"],
        operations=[OPS["t2v"], OPS["i2v"], OPS["extend"]],
        default_config={"health_endpoint": "/health", "poll_timeout_seconds": 1200},
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
        default_config={"health_endpoint": "/health", "poll_timeout_seconds": 1200},
        mappings=[
            MappingTemplate("image-variation", "mj-v7", [OPS["i2i"]], priority=10, quality_score=0.9),
            MappingTemplate("t2i-pro", "mj-v7", [OPS["t2i"]], priority=50, quality_score=0.9),
        ],
        notes="Late-stage image/design connector template; use strict concurrency limits.",
    ),
    "midjourney_discord_session": ProviderTemplate(
        id="midjourney_discord_session",
        name="Midjourney Discord/session task connector",
        adapter_type="http_adapter",
        models=["mj-v6", "mj-v7", "niji"],
        operations=[OPS["t2i"], OPS["i2i"]],
        default_config={"health_endpoint": "/health", "poll_timeout_seconds": 1200, "kernel_selection": "MID-01"},
        mappings=[
            MappingTemplate("image-variation", "mj-v7", [OPS["i2i"]], priority=10, quality_score=0.9),
            MappingTemplate("t2i-pro", "mj-v7", [OPS["t2i"]], priority=50, quality_score=0.9),
        ],
        notes="Selected kernel MID-01. Use Discord/Midjourney session and channel resources with strict concurrency limits.",
    ),
    "pollinations": ProviderTemplate(
        id="pollinations",
        name="Pollinations third-party aggregator connector",
        adapter_type="aggregator_adapter",
        models=["gpt-image-2", "nanobanana", "seedream", "qwen-image", "grok-imagine", "veo", "seedance", "wan"],
        operations=[OPS["t2i"], OPS["i2i"], OPS["t2v"], OPS["i2v"]],
        default_config={"base_url": "https://gen.pollinations.ai", "credential_ref": "agent://providers/pollinations/acct_01", "health_timeout_seconds": 10, "timeout_seconds": 300, "max_reference_assets": 2},
        mappings=[
            MappingTemplate("t2i-fast", "seedream", [OPS["t2i"]], priority=60, cost_score=0.7),
            MappingTemplate("t2i-pro", "gpt-image-2", [OPS["t2i"]], priority=60, quality_score=0.75),
            MappingTemplate("i2v-fast", "seedance", [OPS["i2v"]], priority=60, speed_score=0.7),
            MappingTemplate("t2v-general", "veo", [OPS["t2v"]], priority=60, quality_score=0.75),
        ],
        notes="Third-party aggregator connector template. Store access material as an Agent Provider credential reference or secret-backed Web Cookie/session when the matched runner supports it.",
    ),
    "openrouter_image": ProviderTemplate(
        id="openrouter_image",
        name="OpenRouter image aggregator connector",
        adapter_type="http_adapter",
        models=["gpt-image", "nano-banana", "seedream", "recraft", "flux", "qwen-image"],
        operations=[OPS["t2i"], OPS["i2i"]],
        default_config={"health_endpoint": "/health", "poll_timeout_seconds": 600},
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
        default_config={"health_endpoint": "/health", "poll_timeout_seconds": 1200},
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
        default_config={"health_endpoint": "/health", "poll_timeout_seconds": 600},
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
        default_config={"health_endpoint": "/health", "poll_timeout_seconds": 600},
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
        default_config={"health_endpoint": "/health", "poll_timeout_seconds": 600},
        mappings=[
            MappingTemplate("t2i-fast", "flux", [OPS["t2i"]], priority=90, cost_score=0.75),
            MappingTemplate("t2i-pro", "stable-image", [OPS["t2i"]], priority=90, quality_score=0.75),
            MappingTemplate("image-edit", "controlnet", [OPS["edit"], OPS["i2i"]], priority=90, quality_score=0.7),
        ],
        notes="Cost-optimized self-hosted or third-party image fallback template.",
    ),
}


FINALIZED_PROVIDER_IDS = [
    "openai_web_session",
    "openai_codex",
    "gemini_cli_oauth",
    "gemini_web_session",
    "antigravity",
    "grok",
    "jimeng_web_session",
    "doubao_web_session",
    "kling_web_session",
    "luma_web_session",
    "midjourney_discord_session",
    "qwen_ai_web_session",
    "qianwen_web_session",
]


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
