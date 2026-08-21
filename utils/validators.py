"""Generic, reusable validation helpers.

This module owns ONLY generic, domain-agnostic validation checks
(string emptiness, URL shape, numeric bounds, required-key presence).

It must NEVER contain business rules belonging to another document,
for example:
    - Hidden Gem thresholds (owned by 06_TMDB_INTEGRATION.md)
    - Vault status enum values (owned by 05_DATABASE_SCHEMA.md)
    - AI output schema requirements (owned by 07_AI_INTEGRATION.md)

Those domain-specific checks belong in the service layer that owns
the corresponding business rule, and may be built using the generic
helpers defined here.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional
from urllib.parse import urlparse


def is_blank(value: Optional[str]) -> bool:
    """Return True if ``value`` is None, empty, or whitespace-only."""
    return value is None or value.strip() == ""


def require_non_empty(value: Optional[str], field_name: str) -> str:
    """Return ``value`` if it is a non-blank string, otherwise raise.

    Args:
        value: The candidate string.
        field_name: Human-readable name of the field, used only in the
            error message.

    Returns:
        The original ``value``, unchanged.

    Raises:
        ValueError: If ``value`` is None, empty, or whitespace-only.
    """
    if is_blank(value):
        raise ValueError(f"{field_name} must not be empty")
    return value  # type: ignore[return-value]


def is_valid_url(value: Optional[str]) -> bool:
    """Return True if ``value`` is a syntactically valid http(s) URL.

    This performs a structural check only (scheme and network
    location present). It does not verify reachability.
    """
    if is_blank(value):
        return False
    parsed = urlparse(value)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def is_positive_number(value: Any) -> bool:
    """Return True if ``value`` is an int or float strictly greater than zero."""
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def is_non_negative_number(value: Any) -> bool:
    """Return True if ``value`` is an int or float greater than or equal to zero."""
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0


def require_keys(data: Mapping[str, Any], required_keys: Iterable[str]) -> None:
    """Raise if any key in ``required_keys`` is missing from ``data``.

    Args:
        data: The mapping to check.
        required_keys: Keys that must be present in ``data``.

    Raises:
        ValueError: If one or more required keys are missing. The
            error message lists all missing keys.
    """
    missing = [key for key in required_keys if key not in data]
    if missing:
        raise ValueError(f"Missing required keys: {', '.join(missing)}")
