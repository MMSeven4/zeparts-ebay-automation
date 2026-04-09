"""Structured JSON logging helpers."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from src.core.config import get_settings

_HANDLER_CONFIGURED = False
_SHARED_HANDLER: logging.Handler | None = None
_STANDARD_LOG_RECORD_FIELDS = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "module",
    "msecs",
    "message",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "thread",
    "threadName",
    "taskName",
}


class JsonFormatter(logging.Formatter):
    """Serialize log records as JSON."""

    def format(self, record: logging.LogRecord) -> str:
        """Format a log record into a structured JSON string."""

        payload: dict[str, object] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        extras = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _STANDARD_LOG_RECORD_FIELDS and not key.startswith("_")
        }
        payload.update(extras)

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


def _build_handler() -> logging.Handler:
    """Create the shared stream handler for application loggers."""

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    return handler


def get_logger(name: str) -> logging.Logger:
    """Return a configured logger with JSON formatting."""

    global _HANDLER_CONFIGURED, _SHARED_HANDLER

    if not _HANDLER_CONFIGURED:
        _SHARED_HANDLER = _build_handler()
        _HANDLER_CONFIGURED = True

    logger = logging.getLogger(name)
    logger.setLevel(get_settings().log_level.upper())
    logger.propagate = False

    if _SHARED_HANDLER is not None and _SHARED_HANDLER not in logger.handlers:
        logger.addHandler(_SHARED_HANDLER)

    return logger
