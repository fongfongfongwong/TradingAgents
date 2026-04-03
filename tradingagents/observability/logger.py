"""Structured JSON logging with correlation context."""

from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import datetime, timezone


class CorrelationContext:
    """Thread-local storage for correlation IDs."""

    _local = threading.local()

    @classmethod
    def set_correlation_id(cls, correlation_id: str) -> None:
        cls._local.correlation_id = correlation_id

    @classmethod
    def get_correlation_id(cls) -> str | None:
        return getattr(cls._local, "correlation_id", None)

    @classmethod
    def new_correlation_id(cls) -> str:
        cid = uuid.uuid4().hex[:16]
        cls._local.correlation_id = cid
        return cid


class JSONFormatter(logging.Formatter):
    """Outputs log records as single-line JSON with context fields."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "name": record.name,
            "message": record.getMessage(),
            "correlation_id": CorrelationContext.get_correlation_id(),
        }

        # Include well-known optional fields if present
        for field in ("ticker", "agent_name", "analysis_id"):
            value = getattr(record, field, None)
            if value is not None:
                log_entry[field] = value

        # Include any extra fields passed via the `extra` kwarg
        if hasattr(record, "_extra_fields"):
            log_entry.update(record._extra_fields)

        return json.dumps(log_entry, default=str)


def setup_logger(name: str, level: str = "INFO") -> logging.Logger:
    """Create a logger that emits JSON-structured lines.

    Parameters
    ----------
    name:
        Logger name (typically ``__name__``).
    level:
        Logging level string, e.g. ``"DEBUG"``, ``"INFO"``.

    Returns
    -------
    logging.Logger
    """
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Avoid duplicate handlers when called multiple times
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JSONFormatter())
        logger.addHandler(handler)

    return logger
