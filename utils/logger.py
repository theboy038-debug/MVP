"""Generic logging utilities.

This module owns ONLY the mechanics of producing log output:
- creating a configured logger
- emitting structured log events with consistent fields

It contains no business logic and no knowledge of any specific
service, provider, or domain concept (TMDb, AI, Vault, etc.).
Callers decide what to log and at what level; this module never
decides *when* to log based on business rules.

Log level convention (per 03_SOFTWARE_ARCHITECTURE.md §Logging):
    INFO    -> external API success, successful operations
    WARNING -> retries, recoverable failures
    ERROR   -> external failures, unrecoverable errors

Forbidden content in any log call made through this module's callers:
    API keys, secrets, credential JSON, full prompt text, or any
    content blocked by a safety filter. This module does not inspect
    log content for such values; enforcing that is the responsibility
    of the caller (per 03 §Security and 07 Part 2 §11).
"""

from __future__ import annotations

import logging
import sys
from typing import Any, Mapping, Optional

_DEFAULT_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
_DEFAULT_DATEFMT = "%Y-%m-%dT%H:%M:%SZ"


def get_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    """Return a configured logger instance for the given module name.

    The logger writes to stdout using a consistent format. Calling
    this function multiple times with the same name returns a logger
    that will not accumulate duplicate handlers.

    Args:
        name: Logical name of the logger, typically ``__name__`` of
            the calling module.
        level: Minimum log level to emit. Defaults to ``logging.INFO``.

    Returns:
        A configured ``logging.Logger`` instance.
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    if not logger.handlers:
        handler = logging.StreamHandler(stream=sys.stdout)
        formatter = logging.Formatter(fmt=_DEFAULT_FORMAT, datefmt=_DEFAULT_DATEFMT)
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.propagate = False

    return logger


def log_event(
    logger: logging.Logger,
    event_name: str,
    level: int = logging.INFO,
    fields: Optional[Mapping[str, Any]] = None,
) -> None:
    """Emit a single structured log event.

    This produces one log line per call, combining ``event_name`` with
    a flat set of key-value fields. It does not add, remove, or
    transform fields based on domain knowledge; callers are
    responsible for supplying only fields that are safe to log.

    Args:
        logger: Logger instance obtained from :func:`get_logger`.
        event_name: Short identifier for the event being logged
            (e.g. ``"ai_generation_event"``, ``"tmdb_request"``).
        level: Log level for this event. Defaults to ``logging.INFO``.
        fields: Optional mapping of additional key-value pairs to
            include in the log line.

    Returns:
        None.
    """
    field_items = fields or {}
    rendered_fields = " ".join(f"{key}={value!r}" for key, value in field_items.items())
    message = f"{event_name} {rendered_fields}".strip()
    logger.log(level, message)
