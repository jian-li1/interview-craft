"""Model/search-provider options route — backs the dashboard prompt box's chips.

The studio composer gets its chip options from the WS `session_ready` event (hydrated
against a specific conversation doc); the dashboard has no WS connection yet at the
point the prompt box renders, so it fetches the same option lists over REST instead.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.config import Settings, get_settings
from app.core.deps import CurrentUser, get_current_user
from app.models.model_options import ModelOption, ModelOptionsResponse
from app.services.llm.factory import available_models
from app.services.search.factory import DEFAULT_SEARCH_PROVIDER, available_search_providers

router = APIRouter(prefix="/api/models", tags=["models"])


@router.get("", response_model=ModelOptionsResponse)
async def get_model_options(
    user: CurrentUser = Depends(get_current_user), settings: Settings = Depends(get_settings)
) -> ModelOptionsResponse:
    """Return the model/search-provider options and defaults for the composer chips.

    Read-only (no CSRF dependency needed, unlike mutating routes) but still requires
    auth since it's only meaningful to a signed-in user starting a new conversation.

    Args:
        user (CurrentUser): The authenticated caller, resolved via
            `Depends(get_current_user)`. Unused beyond gating access.
        settings (Settings): Application settings supplying the configured model lists
            and provider credentials.

    Returns:
        ModelOptionsResponse: Every offerable model + search provider, plus each
            option list's default (preselected) value.
    """
    return ModelOptionsResponse(
        models=[ModelOption(**m) for m in available_models(settings)],
        default_model=settings.default_model,
        search_providers=available_search_providers(settings),
        default_search_provider=DEFAULT_SEARCH_PROVIDER,
    )
