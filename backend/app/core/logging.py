"""Structured logging configuration.

Uses stdlib logging with a JSON-ish formatter suitable for Cloud Run log ingestion.
Secrets (tokens, cookies, API keys, resume text) must NEVER be passed to these loggers —
callers are responsible for redacting before logging.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from typing import Any


class StructuredFormatter(logging.Formatter):
    """Formats log records as single-line JSON objects.

    Designed for Cloud Run log ingestion, which parses stdout lines as structured JSON
    when possible. Any caller-supplied `extra={"extra_fields": {...}}` dict is merged
    into the top-level payload, letting call sites attach structured context (e.g.
    conversation_id) without changing the log message string itself.
    """

    def format(self, record: logging.LogRecord) -> str:
        """Render a log record as a single-line JSON string.

        Args:
            record (logging.LogRecord): The log record emitted by a logger call.

        Returns:
            str: A JSON-encoded string containing timestamp, level, logger name,
                message, optional exception traceback, and any merged `extra_fields`.
        """
        payload: dict[str, Any] = {
            "ts": round(time.time(), 3),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        extra = getattr(record, "extra_fields", None)
        if isinstance(extra, dict):
            payload.update(extra)
        # default=str guards against non-JSON-serializable values (e.g. custom objects,
        # datetimes) sneaking into extra_fields, so logging itself never raises.
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO", app_level: str | None = None) -> None:
    """Configure the root logger once for the whole process.

    Installs a single stdout handler using `StructuredFormatter` and quiets a handful of
    noisy third-party loggers. Safe to call multiple times (e.g. across test re-imports
    of the app) — if a handler is already attached, only the log levels are updated
    rather than adding a duplicate handler.

    Args:
        level (str): Root logger level name (e.g. "DEBUG", "INFO"), inherited by every
            logger without an explicit level — including third-party libraries, whose
            DEBUG output is extremely noisy (openai dumps full request payloads; primp's
            Rust crates log per-frame HTTP/2 and DNS chatter). Defaults to "INFO".
        app_level (str | None): Optional level for this application's own `app.*`
            loggers, allowing verbose app logs (e.g. "DEBUG" in development) while the
            root `level` keeps third-party libraries quiet. Defaults to None (app
            loggers inherit the root level).

    Returns:
        None:
    """
    root = logging.getLogger()
    # Levels are (re)applied on every call; handler install below happens only once.
    root.setLevel(level)
    if app_level is not None:
        logging.getLogger("app").setLevel(app_level)
    if root.handlers:
        # Already configured (e.g. during tests re-importing the app).
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(StructuredFormatter())
    root.addHandler(handler)

    # Quiet noisy third-party loggers even further than the root level.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("google").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    # openai's DEBUG logs dump full request payloads (entire conversation + prompts);
    # cap at INFO so even a DEBUG root level can't leak them into the console.
    logging.getLogger("openai").setLevel(logging.INFO)


def get_logger(name: str) -> logging.Logger:
    """Return a standard library logger for the given name.

    Thin convenience wrapper around `logging.getLogger` so call sites import from
    `app.core.logging` rather than the stdlib module directly.

    Args:
        name (str): The logger name, conventionally `__name__` of the calling module.

    Returns:
        logging.Logger: The (possibly cached) logger instance for that name.
    """
    return logging.getLogger(name)
