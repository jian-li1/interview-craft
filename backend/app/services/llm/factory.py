"""Factory for constructing/resolving the active LLMProvider.

Model selection is per-conversation (composer chips — see docs/specs/01 §7), not a
server-wide env default: `resolve_model` maps a requested model id to a
(provider_name, model_id) pair, falling back to the server default when the request is
missing/unknown/unavailable, and `get_llm_provider` builds (and caches) the provider
instance for that pair.
"""

from __future__ import annotations

from functools import lru_cache

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.services.llm.base import LLMProvider

logger = get_logger(__name__)


def resolve_model(model: str | None, settings: Settings) -> tuple[str, str]:
    """Resolve a requested model id to a `(provider_name, model_id)` pair.

    Search order: `settings.openai_models` first, then `settings.gemini_models` — a
    model id present in both lists resolves to "openai". A Gemini model only resolves
    to "gemini" if `settings.gemini_api_key` is configured (otherwise there's no
    working client for it). Any of {None, unknown id, unavailable Gemini id} falls back
    to `(provider-of-default, settings.default_model)`.

    Args:
        model (str | None): The requested model id (e.g. from a WS frame or the
            conversation doc's persisted `selected_model`), or None.
        settings (Settings): Application settings supplying the configured model lists
            and Gemini API key.

    Returns:
        tuple[str, str]: `(provider_name, model_id)`, where `provider_name` is
            "openai" or "gemini".
    """
    if model is not None:
        if model in settings.openai_models:
            return "openai", model
        if model in settings.gemini_models and settings.gemini_api_key:
            return "gemini", model
        # A non-None value that didn't resolve is worth a warning — likely a stale
        # client-sent id or a model removed from the env list.
        logger.warning("unknown or unavailable model requested; falling back to default", extra={"extra_fields": {"model": model}})

    default = settings.default_model
    provider = "openai" if default in settings.openai_models else "gemini"
    return provider, default


def available_models(settings: Settings) -> list[dict[str, str]]:
    """List every model the composer's model chip may offer, in a stable order.

    Args:
        settings (Settings): Application settings supplying the configured model lists
            and Gemini API key.

    Returns:
        list[dict[str, str]]: Ordered `[{"id": ..., "provider": "openai"|"gemini"}]` —
            all OpenAI models first, then Gemini models (only included when
            `gemini_api_key` is set, since an unconfigured Gemini model can't actually
            be used), deduped by id keeping the first occurrence (so an ambiguous id
            listed in both env vars only appears once, attributed to "openai").
    """
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for model_id in settings.openai_models:
        if model_id in seen:
            continue
        seen.add(model_id)
        out.append({"id": model_id, "provider": "openai"})
    if settings.gemini_api_key:
        for model_id in settings.gemini_models:
            if model_id in seen:
                continue
            seen.add(model_id)
            out.append({"id": model_id, "provider": "gemini"})
    return out


@lru_cache
def _build_provider(provider_name: str, model_id: str) -> LLMProvider:
    """Construct (and cache) the LLMProvider instance for a given (provider, model) pair.

    Cached via `lru_cache` keyed on `(provider_name, model_id)` — each distinct model
    now gets its own provider instance/client (no more single-instance-with-small-model-
    routing), so the cache key must include the model id.

    Args:
        provider_name (str): The provider identifier: "openai" or "gemini".
        model_id (str): The resolved model id this instance will serve exclusively.

    Returns:
        LLMProvider: The constructed provider instance.

    Raises:
        ValueError: If `provider_name` is not a recognized provider name.
    """
    settings = get_settings()
    if provider_name == "openai":
        from app.services.llm.openai_provider import OpenAIProvider

        return OpenAIProvider(
            api_key=settings.openai_api_key,
            model=model_id,
            base_url=settings.openai_base_url,
            max_output_tokens=settings.llm_max_output_tokens,
            request_timeout_seconds=settings.llm_request_timeout_seconds,
        )
    if provider_name == "gemini":
        from app.services.llm.gemini_provider import GeminiProvider

        return GeminiProvider(
            api_key=settings.gemini_api_key or "",
            model=model_id,
            max_output_tokens=settings.llm_max_output_tokens,
            request_timeout_seconds=settings.llm_request_timeout_seconds,
        )
    raise ValueError(f"Unknown LLM provider: {provider_name}")


def get_llm_provider(model: str | None = None, settings: Settings | None = None) -> LLMProvider:
    """Return the LLMProvider to use for a given requested model, resolved with fallback.

    Args:
        model (str | None): The requested model id (e.g. the conversation's selected
            model), resolved via `resolve_model`; None uses the server default.
        settings (Settings | None): The settings instance to resolve against; defaults
            to the process-wide cached settings.

    Returns:
        LLMProvider: The resolved (and cached) provider instance to use for this call.
    """
    settings = settings or get_settings()
    provider_name, model_id = resolve_model(model, settings)
    return _build_provider(provider_name, model_id)
