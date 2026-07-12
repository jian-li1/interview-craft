"""Application configuration via pydantic-settings.

All environment variables described in docs/specs/01-architecture-and-contracts.md §4
are surfaced here. Settings is a singleton accessed through `get_settings()` so the
rest of the app never re-parses the environment.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Strongly-typed application settings, sourced from environment / .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Core app ---
    app_env: Literal["development", "production"] = "development"
    port: int = 8000
    frontend_origin: str = "http://localhost:3000"

    # --- Auth / session ---
    session_jwt_secret: str = Field(..., description="Random 64 hex secret for signing session JWTs")
    session_jwt_expires_min: int = 10080  # 7 days
    google_oauth_client_id: str = Field(..., description="Google OAuth client id for ID token verification")

    # --- Firestore ---
    firebase_project_id: str = "interview-blueprint-dev"
    google_application_credentials: str | None = None
    firestore_emulator_host: str | None = None

    # --- LLM ---
    # openai_model/gemini_model are RAW comma-separated model lists (env var names
    # unchanged) — use the `openai_models`/`gemini_models` properties below to get the
    # parsed list. "openai" also serves any OpenAI-compatible endpoint via
    # openai_base_url. There is no more server-wide default provider: model selection
    # is per-conversation (see the composer chips / app/services/llm/factory.py).
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o"
    openai_base_url: str | None = None
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.5-pro"

    # --- Search ---
    # No more server-wide default provider name — selection is per-conversation
    # (see app/services/search/factory.py's DEFAULT_SEARCH_PROVIDER constant).
    google_cse_api_key: str | None = None
    google_cse_engine_id: str | None = None
    tavily_api_key: str | None = None

    # --- Agent behavior ---
    agent_max_iterations: int = 60
    context_token_limit: int = 100_000

    # --- LLM request shape / resilience ---
    # Hard cap on generated tokens per LLM call. Without this, a misbehaving
    # local/OpenAI-compatible endpoint can generate indefinitely — this is
    # a defense-in-depth bound independent of any provider-side default.
    llm_max_output_tokens: int = 8192
    # Timeout (seconds) applied to the `read` leg of LLM HTTP requests — for streaming
    # this is the max gap allowed *between* chunks, not the whole request. A healthy
    # stream sends chunks continuously, so a gap this long means the server is stuck.
    llm_request_timeout_seconds: float = 120.0

    @property
    def is_production(self) -> bool:
        """Report whether the app is running in the production environment.

        Returns:
            bool: True if `app_env` is "production", False otherwise (e.g. "development").
        """
        return self.app_env == "production"

    @property
    def openai_models(self) -> list[str]:
        """Parse `openai_model` (raw comma-separated string) into an ordered model list.

        Returns:
            list[str]: Model ids in the order listed, stripped of whitespace, with empty
                entries dropped (e.g. a trailing comma never produces a blank id).
        """
        return [m.strip() for m in self.openai_model.split(",") if m.strip()]

    @property
    def gemini_models(self) -> list[str]:
        """Parse `gemini_model` (raw comma-separated string) into an ordered model list.

        Returns:
            list[str]: Model ids in the order listed, stripped of whitespace, with empty
                entries dropped.
        """
        return [m.strip() for m in self.gemini_model.split(",") if m.strip()]

    @property
    def default_model(self) -> str:
        """The server-wide default model: the first OPENAI_MODEL entry.

        Used both as the composer's default model-chip selection and as the model for
        one-shot server-side generations (onboarding profile synthesis) that have no
        conversation to inherit a selection from. Falls back to the first Gemini model
        in the unlikely case the OpenAI list is empty.

        Returns:
            str: The default model id.

        Raises:
            ValueError: If both `openai_models` and `gemini_models` are empty (no model
                configured at all).
        """
        if self.openai_models:
            return self.openai_models[0]
        if self.gemini_models:
            return self.gemini_models[0]
        raise ValueError("No models configured: OPENAI_MODEL and GEMINI_MODEL are both empty")


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide cached Settings instance.

    `lru_cache` ensures the environment is parsed into a `Settings` instance exactly once
    per process; all callers (including FastAPI `Depends(get_settings)`) share the same
    object. Because `session_jwt_secret` and `google_oauth_client_id` have no default,
    the first call (typically at import time of `app.main`) raises a pydantic
    `ValidationError` immediately if either is unset — a deliberate fail-fast so missing
    secrets are never silently defaulted.

    Returns:
        Settings: The singleton settings instance sourced from environment / `.env` file.

    Raises:
        pydantic.ValidationError: If a required setting (e.g. `session_jwt_secret`,
            `google_oauth_client_id`) is missing from the environment.
    """
    return Settings()  # type: ignore[call-arg]
