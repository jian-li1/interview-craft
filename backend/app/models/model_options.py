"""Response model for `GET /api/models` — backs the dashboard/composer chip options.

No Firestore doc mirrored here; this is a pure computed response over
`app.services.llm.factory` / `app.services.search.factory`.
"""

from __future__ import annotations

from app.models.common import ApiModel


class ModelOption(ApiModel):
    """One selectable LLM model, as offered by the model chip.

    Attributes:
        id (str): The model id (e.g. "gpt-4o").
        provider (str): The backing provider for this model: "openai" or "gemini".
    """

    id: str
    provider: str


class ModelOptionsResponse(ApiModel):
    """Response body for `GET /api/models`.

    Attributes:
        models (list[ModelOption]): Every model the chip may offer, in display order
            (mirrors `available_models`).
        default_model (str): The server default model id, used to preselect the chip
            before the user has made a choice.
        search_providers (list[str]): Every search provider name the chip may offer
            (mirrors `available_search_providers`).
        default_search_provider (str): The default search provider name
            (`DEFAULT_SEARCH_PROVIDER`), used to preselect the chip.
    """

    models: list[ModelOption]
    default_model: str
    search_providers: list[str]
    default_search_provider: str
