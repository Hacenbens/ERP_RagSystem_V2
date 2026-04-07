"""
structured_logger — JSON structured logging with trace_id / user_id propagation.

Usage::

    from src.observability.structured_logger import get_logger, set_trace_context

    logger = get_logger(__name__)

    # Set context at request boundary (middleware)
    set_trace_context(trace_id="abc-123", user_id="user-42")

    # Log anywhere downstream — trace_id / user_id injected automatically
    logger.info("sql_validator.start", sql_preview="SELECT * FROM ...")
    logger.error("sql_validator.error", error="tenant_id missing")

Every log line is a single-line JSON object. Required fields guaranteed on every line:
    timestamp   — ISO-8601 UTC
    level       — DEBUG | INFO | WARNING | ERROR | CRITICAL
    logger      — dotted module name passed to get_logger()
    event       — first positional argument (the message)
    trace_id    — from ContextVar; empty string if not set
    user_id     — from ContextVar; empty string if not set
"""
from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

# ---------------------------------------------------------------------------
# Context variables — propagate automatically across async boundaries
# ---------------------------------------------------------------------------

_trace_id: ContextVar[str] = ContextVar("trace_id", default="")
_user_id: ContextVar[str] = ContextVar("user_id", default="")


def set_trace_context(*, trace_id: str, user_id: str = "") -> None:
    """Set trace_id and user_id for the current async context.

    Call this once per request at the middleware boundary.
    """
    _trace_id.set(trace_id)
    _user_id.set(user_id)


def get_trace_id() -> str:
    """Return the trace_id bound to the current async context."""
    return _trace_id.get()


def get_user_id() -> str:
    """Return the user_id bound to the current async context."""
    return _user_id.get()


# ---------------------------------------------------------------------------
# JSON formatter
# ---------------------------------------------------------------------------

class _JSONFormatter(logging.Formatter):
    """Format every log record as a single-line JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
            "trace_id": _trace_id.get(),
            "user_id": _user_id.get(),
        }

        # Merge any extra keyword fields passed via logger.info(..., key=val)
        extras: dict[str, Any] = getattr(record, "_extra_fields", {})
        payload.update(extras)

        # Attach exception info if present
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False, default=str)


# ---------------------------------------------------------------------------
# Structured logger wrapper
# ---------------------------------------------------------------------------

class StructuredLogger:
    """Thin wrapper around stdlib Logger that accepts keyword fields.

    Instead of::

        logging.info("msg %s", value)   # positional interpolation

    Use::

        logger.info("event_name", field1=val1, field2=val2)
    """

    def __init__(self, name: str) -> None:
        self._logger = logging.getLogger(name)

    # ------------------------------------------------------------------
    # Internal helper
    # ------------------------------------------------------------------

    def _log(self, level: int, event: str, **fields: Any) -> None:
        if self._logger.isEnabledFor(level):
            record = self._logger.makeRecord(
                name=self._logger.name,
                level=level,
                fn="",
                lno=0,
                msg=event,
                args=(),
                exc_info=fields.pop("exc_info", None),
            )
            record._extra_fields = fields  # type: ignore[attr-defined]
            self._logger.handle(record)

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    def debug(self, event: str, **fields: Any) -> None:
        """Emit a DEBUG-level structured log line."""
        self._log(logging.DEBUG, event, **fields)

    def info(self, event: str, **fields: Any) -> None:
        """Emit an INFO-level structured log line."""
        self._log(logging.INFO, event, **fields)

    def warning(self, event: str, **fields: Any) -> None:
        """Emit a WARNING-level structured log line."""
        self._log(logging.WARNING, event, **fields)

    def error(self, event: str, **fields: Any) -> None:
        """Emit an ERROR-level structured log line."""
        self._log(logging.ERROR, event, **fields)

    def critical(self, event: str, **fields: Any) -> None:
        """Emit a CRITICAL-level structured log line."""
        self._log(logging.CRITICAL, event, **fields)


# ---------------------------------------------------------------------------
# Module-level setup — runs once when first imported
# ---------------------------------------------------------------------------

def _configure_root_handler() -> None:
    """Attach a JSON handler to the root logger if none is configured."""
    root = logging.getLogger()
    if not any(isinstance(h, logging.StreamHandler) and
               isinstance(h.formatter, _JSONFormatter)
               for h in root.handlers):
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(_JSONFormatter())
        root.addHandler(handler)
        root.setLevel(logging.INFO)


_configure_root_handler()


# ---------------------------------------------------------------------------
# Public factory
# ---------------------------------------------------------------------------

_loggers: dict[str, StructuredLogger] = {}


def get_logger(name: str) -> StructuredLogger:
    """Return a StructuredLogger for *name* (module __name__ recommended).

    Instances are cached — calling get_logger with the same name always
    returns the same object.
    """
    if name not in _loggers:
        _loggers[name] = StructuredLogger(name)
    return _loggers[name]


__all__ = [
    "get_logger",
    "set_trace_context",
    "get_trace_id",
    "get_user_id",
    "StructuredLogger",
]
