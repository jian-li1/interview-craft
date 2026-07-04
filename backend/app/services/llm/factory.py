"""Factory for constructing the active LLMProvider.

Resolution order for the provider name: per-user settings override (if set) then the
server-wide `LLM_PROVIDER` env default. Provider instances are cached per (provider name)
since they are stateless aside from their configured client.
"""

from __future__ import annotations

from functools import lru_cache

from app.core.config import Settings, get_settings
from app.services.llm.base import LLMProvider


@lru_cache
def _build_provider(name: str) -> LLMProvider:
    """Construct (and cache) the LLMProvider instance for a given provider name.

    Cached via `lru_cache` keyed on `name` since providers are stateless aside from
    their configured client, avoiding repeated client construction across requests.

    Args:
        name (str): The provider identifier: "openai", "llamacpp", or "gemini".

    Returns:
        LLMProvider: The constructed provider instance.

    Raises:
        ValueError: If `name` is not a recognized provider, or if required
            provider-specific settings (e.g. `OPENAI_BASE_URL` for llamacpp) are missing.
    """
    settings = get_settings()
    if name == "openai":
        from app.services.llm.openai_provider import OpenAIProvider

        return OpenAIProvider(
            api_key=settings.openai_api_key,
            model=settings.openai_model,
            small_model=settings.openai_small_model,
            base_url=settings.openai_base_url,
            max_output_tokens=settings.llm_max_output_tokens,
            request_timeout_seconds=settings.llm_request_timeout_seconds,
        )
    if name == "llamacpp":
        from app.services.llm.openai_provider import OpenAIProvider

        if not settings.openai_base_url:
            raise ValueError("OPENAI_BASE_URL must be set to use the llamacpp provider")
        return OpenAIProvider(
            api_key=settings.openai_api_key,
            model=settings.openai_model,
            small_model=settings.openai_small_model,
            base_url=settings.openai_base_url,
            max_output_tokens=settings.llm_max_output_tokens,
            request_timeout_seconds=settings.llm_request_timeout_seconds,
        )
    if name == "gemini":
        from app.services.llm.gemini_provider import GeminiProvider

        return GeminiProvider(
            api_key=settings.gemini_api_key or "",
            model=settings.gemini_model,
            small_model=settings.gemini_small_model,
            max_output_tokens=settings.llm_max_output_tokens,
            request_timeout_seconds=settings.llm_request_timeout_seconds,
        )
    raise ValueError(f"Unknown LLM provider: {name}")


def get_llm_provider(user_override: str | None = None, settings: Settings | None = None) -> LLMProvider:
    """Return the LLMProvider to use, honoring a per-user override if provided.

    Args:
        user_override (str | None): A per-user provider preference (from
            `users/{uid}.settings.llm_provider`), which wins over the server default
            when set.
        settings (Settings | None): The settings instance to read the server-wide
            default from; defaults to the process-wide cached settings.

    Returns:
        LLMProvider: The resolved (and cached) provider instance to use for this call.
    """
    settings = settings or get_settings()
    name = user_override or settings.llm_provider
    return _build_provider(name)
