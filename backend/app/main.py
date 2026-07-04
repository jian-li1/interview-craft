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
    """Build and configure the FastAPI application instance.

    Wires up structured logging, CORS (restricted to the configured frontend origin so
    the session cookie can be sent cross-origin with credentials), and mounts every REST
    router plus the WebSocket chat router.

    Returns:
        FastAPI: A fully configured application instance, ready to be served by uvicorn.
    """
    settings = get_settings()
    # Verbose logging in development, quieter structured logs in production (Cloud Run).
    configure_logging("DEBUG" if settings.app_env == "development" else "INFO")

    app = FastAPI(
        title="InterviewCraft API",
        version="0.1.0",
        description="Backend for InterviewCraft: an agentic AI interview-prep curriculum platform.",
    )

    # allow_credentials=True is required so the browser sends the httpOnly `ic_session`
    # cookie on cross-origin requests from the Next.js frontend; this only works because
    # allow_origins is a specific origin (a wildcard "*" is rejected by browsers when
    # credentials are allowed).
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
        """Log a single structured line once the app finishes booting.

        Useful for confirming which environment and LLM provider a deployed instance is
        actually running with, without needing to inspect env vars directly.

        Returns:
            None: This function only has the side effect of emitting a log line.
        """
        logger.info(
            "InterviewCraft backend starting up",
            extra={"extra_fields": {"app_env": settings.app_env, "llm_provider": settings.llm_provider}},
        )

    return app


# Module-level singleton instantiated at import time; this is the ASGI callable that
# uvicorn/gunicorn point at (e.g. `uvicorn app.main:app`).
app = create_app()
