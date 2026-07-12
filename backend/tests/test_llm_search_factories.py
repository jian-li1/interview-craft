"""Model/search-provider resolution: Settings list-parsing + default_model, and the
per-conversation resolution helpers (`resolve_model`, `available_models`,
`resolve_search_provider`, `available_search_providers`) that back the composer chips.

No real network/credentials — these are pure functions over `Settings`.
"""

from __future__ import annotations

from app.services.llm.factory import available_models, resolve_model
from app.services.search.factory import (
    DEFAULT_SEARCH_PROVIDER,
    available_search_providers,
    resolve_search_provider,
)


# --------------------------------------------------------------------------------------
# Settings: comma-separated model list parsing + default_model
# --------------------------------------------------------------------------------------


def test_openai_models_parses_comma_separated_list_with_whitespace_stripped(settings, monkeypatch):
    """Verify `openai_models` splits on comma, strips whitespace, and drops empty entries."""
    monkeypatch.setattr(settings, "openai_model", " gpt-4o , gpt-4o-mini ,, ")
    assert settings.openai_models == ["gpt-4o", "gpt-4o-mini"]


def test_gemini_models_parses_comma_separated_list(settings, monkeypatch):
    """Verify `gemini_models` parses the same way as `openai_models`."""
    monkeypatch.setattr(settings, "gemini_model", "gemini-2.5-pro,gemini-2.5-flash")
    assert settings.gemini_models == ["gemini-2.5-pro", "gemini-2.5-flash"]


def test_default_model_is_first_openai_entry(settings):
    """Verify `default_model` is the first entry of `OPENAI_MODEL` (conftest sets
    "gpt-4o,gpt-4o-mini")."""
    assert settings.default_model == "gpt-4o"


def test_default_model_falls_back_to_gemini_when_openai_list_empty(settings, monkeypatch):
    """Verify `default_model` falls back to the first Gemini model if OPENAI_MODEL is empty."""
    monkeypatch.setattr(settings, "openai_model", "")
    monkeypatch.setattr(settings, "gemini_model", "gemini-2.5-pro")
    assert settings.default_model == "gemini-2.5-pro"


# --------------------------------------------------------------------------------------
# resolve_model
# --------------------------------------------------------------------------------------


def test_resolve_model_openai_hit(settings):
    """A requested model present in OPENAI_MODEL resolves to ("openai", model)."""
    assert resolve_model("gpt-4o-mini", settings) == ("openai", "gpt-4o-mini")


def test_resolve_model_gemini_hit_with_key(settings, monkeypatch):
    """A requested Gemini model resolves to ("gemini", model) when GEMINI_API_KEY is set."""
    monkeypatch.setattr(settings, "gemini_api_key", "test-gemini-key")
    monkeypatch.setattr(settings, "gemini_model", "gemini-2.5-pro")
    assert resolve_model("gemini-2.5-pro", settings) == ("gemini", "gemini-2.5-pro")


def test_resolve_model_gemini_without_key_falls_back_to_default(settings, monkeypatch):
    """A Gemini model id is unusable without GEMINI_API_KEY, so it falls back to default."""
    monkeypatch.setattr(settings, "gemini_api_key", None)
    monkeypatch.setattr(settings, "gemini_model", "gemini-2.5-pro")
    assert resolve_model("gemini-2.5-pro", settings) == ("openai", settings.default_model)


def test_resolve_model_unknown_falls_back_to_default(settings):
    """An unrecognized model id falls back to (provider-of-default, default_model)."""
    assert resolve_model("not-a-real-model", settings) == ("openai", settings.default_model)


def test_resolve_model_none_falls_back_to_default(settings):
    """A None model request (no selection made yet) resolves to the server default."""
    assert resolve_model(None, settings) == ("openai", settings.default_model)


# --------------------------------------------------------------------------------------
# available_models
# --------------------------------------------------------------------------------------


def test_available_models_lists_openai_only_without_gemini_key(settings, monkeypatch):
    """Without GEMINI_API_KEY, Gemini models are excluded even if GEMINI_MODEL is set."""
    monkeypatch.setattr(settings, "gemini_api_key", None)
    monkeypatch.setattr(settings, "gemini_model", "gemini-2.5-pro")
    models = available_models(settings)
    assert models == [{"id": "gpt-4o", "provider": "openai"}, {"id": "gpt-4o-mini", "provider": "openai"}]


def test_available_models_includes_gemini_when_key_set(settings, monkeypatch):
    """With GEMINI_API_KEY set, Gemini models are appended after all OpenAI models."""
    monkeypatch.setattr(settings, "gemini_api_key", "test-gemini-key")
    monkeypatch.setattr(settings, "gemini_model", "gemini-2.5-pro,gemini-2.5-flash")
    models = available_models(settings)
    assert models == [
        {"id": "gpt-4o", "provider": "openai"},
        {"id": "gpt-4o-mini", "provider": "openai"},
        {"id": "gemini-2.5-pro", "provider": "gemini"},
        {"id": "gemini-2.5-flash", "provider": "gemini"},
    ]


def test_available_models_dedupes_id_present_in_both_lists(settings, monkeypatch):
    """An id listed in both OPENAI_MODEL and GEMINI_MODEL appears once, as "openai"."""
    monkeypatch.setattr(settings, "gemini_api_key", "test-gemini-key")
    monkeypatch.setattr(settings, "gemini_model", "gpt-4o,gemini-2.5-flash")
    models = available_models(settings)
    ids = [m["id"] for m in models]
    assert ids.count("gpt-4o") == 1
    assert {"id": "gpt-4o", "provider": "gemini"} not in models


# --------------------------------------------------------------------------------------
# available_search_providers / resolve_search_provider
# --------------------------------------------------------------------------------------


def test_available_search_providers_duckduckgo_only_by_default(settings):
    """Without any search API keys configured, only duckduckgo is offered."""
    assert available_search_providers(settings) == ["duckduckgo"]


def test_available_search_providers_includes_google_when_both_keys_set(settings, monkeypatch):
    """google is offered only when BOTH the CSE api key and engine id are set."""
    monkeypatch.setattr(settings, "google_cse_api_key", "key")
    monkeypatch.setattr(settings, "google_cse_engine_id", None)
    assert "google" not in available_search_providers(settings)

    monkeypatch.setattr(settings, "google_cse_engine_id", "engine")
    assert "google" in available_search_providers(settings)


def test_available_search_providers_includes_tavily_when_key_set(settings, monkeypatch):
    """tavily is offered once TAVILY_API_KEY is set."""
    monkeypatch.setattr(settings, "tavily_api_key", "tavily-key")
    assert "tavily" in available_search_providers(settings)


def test_resolve_search_provider_none_falls_back_to_default(settings):
    """A None request (no selection made yet) resolves to DEFAULT_SEARCH_PROVIDER."""
    assert resolve_search_provider(None, settings) == DEFAULT_SEARCH_PROVIDER


def test_resolve_search_provider_unavailable_falls_back_to_default(settings, monkeypatch):
    """Requesting "google" without its keys configured falls back to duckduckgo."""
    monkeypatch.setattr(settings, "google_cse_api_key", None)
    monkeypatch.setattr(settings, "google_cse_engine_id", None)
    assert resolve_search_provider("google", settings) == DEFAULT_SEARCH_PROVIDER


def test_resolve_search_provider_available_passes_through(settings, monkeypatch):
    """Requesting a configured, available provider returns it unchanged."""
    monkeypatch.setattr(settings, "tavily_api_key", "tavily-key")
    assert resolve_search_provider("tavily", settings) == "tavily"
