"""FastAPI application factory: CORS, routers, WebSocket, structured logging."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, conversations, curricula, health, onboarding, settings as settings_routes
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.ws import chat as ws_chat

logger = get_logger(__name__)


def create_app() -> FastAPI:
    """Build and configure the FastAPI application instance."""
    settings = get_settings()
    configure_logging("DEBUG" if settings.app_env == "development" else "INFO")

    app = FastAPI(
        title="InterviewCraft API",
        version="0.1.0",
        description="Backend for InterviewCraft: an agentic AI interview-prep curriculum platform.",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(onboarding.router)
    app.include_router(curricula.router)
    app.include_router(conversations.router)
    app.include_router(settings_routes.router)
    app.include_router(ws_chat.router)

    @app.on_event("startup")
    async def _on_startup() -> None:
        logger.info(
            "InterviewCraft backend starting up",
            extra={"extra_fields": {"app_env": settings.app_env, "llm_provider": settings.llm_provider}},
        )

    return app


app = create_app()
