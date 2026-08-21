"""Centralized cache key versioning and TTL configuration lookup.

Per 06_TMDB_INTEGRATION.md §4 (Cache Versioning) and
08_IMPLEMENTATION_SPEC.md §17 (Cache Strategy), every cache key in
the system must be suffixed with a config version so that changing a
configuration value automatically invalidates stale cached data,
without a manual cache clear or app restart. This module is the ONE
place that implements that versioning pattern — provider
implementations must not build their own version-suffix logic
(06_TMDB_INTEGRATION.md §4).

This module reads configuration exclusively through ``config.py``
(TTL tables and version strings); it never reads Environment
Variables or Streamlit Secrets directly (that remains config.py's
exclusive responsibility per ADR-001 and
03_SOFTWARE_ARCHITECTURE.md §Security).

Resources that the Frozen Bible explicitly does NOT cache — TMDb's
``/discover/movie`` random endpoint and AI generation calls
(06_TMDB_INTEGRATION.md §Cache Policy;
07_AI_INTEGRATION.md Part 2 §10) — have no entry in
``config.TMDB_CACHE_TTL`` and no AI cache TTL table exists in
config.py at all. This module does not add caching behavior for
those workflows; requesting a TTL for a non-cacheable resource fails
fast with ``KeyError`` rather than silently permitting it.

Client-instance caching (ADR-001 Type A/B) is a separate concern
owned by config.py, not by this module (08_IMPLEMENTATION_SPEC.md
§17 — "Client caching: แยกจาก data caching").
"""

from __future__ import annotations

from typing import Callable, TypeVar

import streamlit as st

import config

F = TypeVar("F", bound=Callable)


def versioned_cache_key(base_name: str, config_version: str) -> str:
    """Build a version-suffixed cache key.

    Implements the generic pattern from 06_TMDB_INTEGRATION.md §4:
    ``"{base_name}_{config_version}"``.

    Args:
        base_name: Logical name of the cached resource, e.g.
            "genres" or "movie_details".
        config_version: The configuration version string to suffix
            with, e.g. ``config.TMDB_CONFIG_VERSION``.

    Returns:
        The versioned cache key, e.g. "genres_v1".
    """
    return f"{base_name}_{config_version}"


def tmdb_cache_key(base_name: str) -> str:
    """Build a versioned cache key for TMDb data.

    Uses ``config.TMDB_CONFIG_VERSION`` as the version suffix
    (06_TMDB_INTEGRATION.md §4).

    Args:
        base_name: Logical name of the cached TMDb resource, e.g.
            "genres", "movie_details", "videos", "watch_providers",
            or "configuration".

    Returns:
        The versioned cache key, e.g. "genres_v1".
    """
    return versioned_cache_key(base_name, config.TMDB_CONFIG_VERSION)


def ai_cache_key(base_name: str) -> str:
    """Build a versioned cache key for AI/prompt asset data.

    Uses ``config.AI_CONFIG_VERSION`` as the version suffix, following
    the same pattern as :func:`tmdb_cache_key`
    (07_AI_INTEGRATION.md Part 1 §3 — "Cache key ต้องรวม config
    version (ตาม pattern เดียวกับ ADR cache versioning ใน 06)").

    Args:
        base_name: Logical name of the cached AI/prompt resource,
            e.g. "prompt_default".

    Returns:
        The versioned cache key, e.g. "prompt_default_v1".
    """
    return versioned_cache_key(base_name, config.AI_CONFIG_VERSION)


def get_tmdb_cache_ttl(resource_name: str) -> int:
    """Look up the configured TTL, in seconds, for a TMDb resource type.

    Only resources listed in ``config.TMDB_CACHE_TTL`` are cacheable
    (06_TMDB_INTEGRATION.md §Cache Policy). The random discovery
    endpoint (``/discover/movie``) is intentionally absent from that
    table and therefore has no TTL — it must never be cached.

    Args:
        resource_name: One of "genres", "movie_details", "videos",
            "watch_providers", or "configuration".

    Returns:
        TTL in seconds.

    Raises:
        KeyError: If ``resource_name`` is not a cacheable resource
            (including, intentionally, "discover").
    """
    return config.TMDB_CACHE_TTL[resource_name]


def cached_data(ttl_seconds: int) -> Callable[[F], F]:
    """Return a ``st.cache_data`` decorator configured with a TTL.

    Centralizes the decorator so callers never construct their own
    ``st.cache_data`` calls with ad-hoc TTL values
    (08_IMPLEMENTATION_SPEC.md §17). TTL values must come from
    :func:`get_tmdb_cache_ttl` or an equivalent config-backed lookup,
    never a literal.

    Args:
        ttl_seconds: Cache lifetime in seconds.

    Returns:
        A decorator equivalent to ``st.cache_data(ttl=ttl_seconds)``.
    """
    return st.cache_data(ttl=ttl_seconds)


def cached_resource() -> Callable[[F], F]:
    """Return a ``st.cache_resource`` decorator for client instances.

    Per ADR-001, this is used only for Type A (process-level) client
    caching, which is composed inside config.py — this function
    exists so that composition logic never calls the Streamlit API
    directly with inconsistent usage patterns.

    Returns:
        The ``st.cache_resource`` decorator.
    """
    return st.cache_resource
