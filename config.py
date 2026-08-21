"""Configuration and composition root.

This module is the single place in the system permitted to read
Environment Variables / Streamlit Secrets (per
03_SOFTWARE_ARCHITECTURE.md §Security and ADR-001), and the single
place that decides how provider clients are constructed and cached
(per ADR-001 and 08_IMPLEMENTATION_SPEC.md §11-12).

No other module may read secrets directly, and no provider
implementation may construct its own client — providers receive an
already-constructed client through the factory functions defined
here.

Provider implementation modules are imported lazily, inside the
factory functions, rather than at module load time. This avoids a
Python-level circular import (config.py needs the provider classes;
the provider classes need config.py's constants) without changing
which module owns configuration or client composition — this is an
implementation technique only, not an architecture change
(08_IMPLEMENTATION_SPEC.md — Pre-Implementation Check, Risk
Register).

This module contains no business logic beyond ADR-001's Type A / B
resolution and no UI code.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

import streamlit as st
from dotenv import load_dotenv

# Load key=value pairs from a local .env file (if present) into
# os.environ before anything below reads it. This does not add a
# second place that reads secrets — .env values land in the exact
# same os.environ that _read_env_key() below reads from; it only
# changes where a value can originate (shell export OR a .env file).
# override=False: real shell/OS environment variables always win
# over .env, so .env is a convenience default, not a silent override.
load_dotenv(override=False)

# ---------------------------------------------------------------------------
# TMDb configuration (06_TMDB_INTEGRATION.md §3 Configuration Contract)
# ---------------------------------------------------------------------------

TMDB_DEFAULT_REGION: str = "TH"
TMDB_ALLOWED_LANGUAGES: list[str] = ["en", "th", "ja", "ko"]
TMDB_INCLUDE_ADULT: bool = False

HIDDEN_GEM_VOTE_AVERAGE_MIN: float = 7.0
HIDDEN_GEM_VOTE_COUNT_MIN: int = 100
HIDDEN_GEM_VOTE_COUNT_MAX: int = 3000
HIDDEN_GEM_RUNTIME_MIN: int = 70

TMDB_CACHE_TTL: Dict[str, int] = {
    "genres": 86400,
    "movie_details": 43200,
    "videos": 86400,
    "watch_providers": 21600,
    "configuration": 604800,
}

TMDB_RETRY_MAX_ATTEMPTS: int = 5
TMDB_RETRY_BASE_DELAY_SECONDS: int = 1

TMDB_CONFIG_VERSION: str = "v1"

# Request timeout in seconds for TMDb HTTP calls. Added via Post-Batch
# Governance Patch (Configuration Gap Resolution) after Batch 6's
# Pre-Generation Verification found 03_SOFTWARE_ARCHITECTURE.md
# §Error Handling requires a timeout but no exact value anywhere in
# the Frozen Bible. This is a resolved configuration gap, not a new
# architecture decision.
TMDB_REQUEST_TIMEOUT_SECONDS: int = 10

RANDOM_DISCOVERY_MAX_RETRIES: int = 5
HIDDEN_GEM_MAX_RETRIES: int = 8

# ---------------------------------------------------------------------------
# AI configuration (07_AI_INTEGRATION.md Part 2 §2 Model Configuration)
# ---------------------------------------------------------------------------

AI_PROVIDER: str = "gemini"
AI_MODEL_NAME: str = "gemini-3.6-flash"
# Increased from 1024 as a safety margin — even with thinking
# disabled (see thinking_config in gemini_provider.py), some
# reasoning-enabled models have been reported to not fully honor
# thinking_budget=0 in all cases. A larger ceiling avoids truncation
# without materially changing cost for a short script response.
AI_MAX_OUTPUT_TOKENS: int = 2048
AI_TEMPERATURE: float = 0.9
AI_TOP_P: float = 0.95

AI_RETRY_MAX_ATTEMPTS: int = 3
AI_RETRY_BASE_DELAY_SECONDS: int = 2

AI_SUPPORTED_SCHEMA_VERSION: str = "1.0"
AI_CONFIG_VERSION: str = "v1"

# Request timeout in seconds for AI provider SDK calls. Originally
# 30s (see Batch 6 governance patch); increased to 60s after a real
# ReadTimeout was observed in production use with gemini-3.6-flash —
# consistent with reported time-to-first-token figures for this
# model generation being 15-20s+ even before output generation
# completes. Same Post-Batch Governance Patch category as before
# (Configuration Gap Resolution / tuning), not a new architecture
# decision.
AI_REQUEST_TIMEOUT_SECONDS: int = 60

# ---------------------------------------------------------------------------
# ADR-001 — API Key & Client Lifecycle
# ---------------------------------------------------------------------------

_TMDB_ENV_KEY = "TMDB_API_KEY"
_AI_ENV_KEY = "GEMINI_API_KEY"

# Process-level cache for Type A clients (created once, live for the
# lifetime of the process). Populated lazily on first use.
_type_a_client_cache: Dict[str, Any] = {}


def _read_env_key(env_var_name: str) -> Optional[str]:
    """Read an API key from the environment, or Streamlit Secrets.

    This is the ONLY function in the system permitted to read
    Environment Variables / Streamlit Secrets for API keys (ADR-001,
    03_SOFTWARE_ARCHITECTURE.md §Security).

    Checks os.environ first (covers shell export and .env, since
    python-dotenv loads .env values into os.environ at startup), then
    falls back to st.secrets. This fallback matters specifically for
    Streamlit Cloud: it has no persistent local disk to hold a .env
    file, and does not automatically copy Secrets-UI values into
    os.environ — they're only reachable via st.secrets.
    """
    value = os.environ.get(env_var_name)
    if value:
        return value
    try:
        return st.secrets.get(env_var_name)
    except Exception:
        # No secrets.toml / Secrets UI configured at all (e.g. local
        # dev without Streamlit secrets) — not an error, just means
        # this source has nothing to offer.
        return None


def resolve_key_source(env_var_name: str, session_key: Optional[str]) -> tuple[str, str]:
    """Determine which ADR-001 client lifecycle type applies.

    Args:
        env_var_name: Name of the environment variable that would
            hold the key for Type A (Secrets/Environment) deployment.
        session_key: A key value supplied by the user for this
            session, if any (Type B). Callers pass ``None`` when no
            session-provided key exists yet.

    Returns:
        A tuple of ``(client_type, api_key)`` where ``client_type``
        is either ``"A"`` or ``"B"``.

    Raises:
        ValueError: If neither an environment key nor a session key
            is available.
    """
    env_key = _read_env_key(env_var_name)
    if env_key:
        return "A", env_key
    if session_key:
        return "B", session_key
    raise ValueError(
        f"No API key available: environment variable '{env_var_name}' is not "
        "set and no session-provided key was supplied."
    )


def get_movie_provider_client(session_key: Optional[str] = None) -> Any:
    """Return a TMDb provider client, following ADR-001 lifecycle rules.

    Type A clients are cached at process level (created once per
    process). Type B clients must be cached by the caller at session
    level (per 08_IMPLEMENTATION_SPEC.md §5/§11) — this function does
    not perform session-level caching itself, since it has no access
    to Streamlit session state.

    Args:
        session_key: A user-provided TMDb API key for this session,
            if applicable (Type B). Pass ``None`` for Type A
            deployments.

    Returns:
        A configured provider client instance.
    """
    # Lazy import to avoid a module-level circular import between
    # config.py and the provider implementation.
    from services.movie_provider.tmdb_provider import TMDbProvider

    client_type, api_key = resolve_key_source(_TMDB_ENV_KEY, session_key)

    if client_type == "A":
        cache_key = "tmdb_type_a"
        if cache_key not in _type_a_client_cache:
            _type_a_client_cache[cache_key] = TMDbProvider(api_key=api_key)
        return _type_a_client_cache[cache_key]

    # Type B: always construct fresh; session-level caching is the
    # caller's responsibility.
    return TMDbProvider(api_key=api_key)


def get_ai_provider_client(session_key: Optional[str] = None) -> Any:
    """Return an AI provider client, following ADR-001 lifecycle rules.

    See :func:`get_movie_provider_client` for the Type A/B caching
    contract; the same rules apply here.

    Args:
        session_key: A user-provided AI provider API key for this
            session, if applicable (Type B). Pass ``None`` for Type A
            deployments.

    Returns:
        A configured provider client instance implementing
        ``AIProviderBase``.
    """
    # Lazy import to avoid a module-level circular import between
    # config.py and the provider implementation.
    from services.ai_provider.gemini_provider import GeminiProvider

    client_type, api_key = resolve_key_source(_AI_ENV_KEY, session_key)

    if client_type == "A":
        cache_key = "ai_type_a"
        if cache_key not in _type_a_client_cache:
            _type_a_client_cache[cache_key] = GeminiProvider(api_key=api_key)
        return _type_a_client_cache[cache_key]

    # Type B: always construct fresh; session-level caching is the
    # caller's responsibility.
    return GeminiProvider(api_key=api_key)


def is_type_b_deployment() -> bool:
    """Return True if this deployment relies on user-supplied session keys.

    Used by the UI layer to decide whether the API Key Setup gate
    (04_UI_UX_SPEC.md Part 1 Patch 2) should ever be shown. Type A
    deployments must never show that gate.
    """
    return not bool(_read_env_key(_TMDB_ENV_KEY)) or not bool(_read_env_key(_AI_ENV_KEY))


# ---------------------------------------------------------------------------
# Google Sheets history logging (optional feature)
#
# This is a lightweight "what have I already viewed" log, NOT the
# full Content Vault schema/workflow from 05_DATABASE_SCHEMA.md
# (status enum, dedup enforcement, script fields, CRUD editing) —
# that remains deferred. This is a separate, simpler feature: one
# row appended per movie viewed, best-effort, never blocking the
# main discovery/generation flow if unconfigured or unreachable.
# ---------------------------------------------------------------------------

_GOOGLE_SERVICE_ACCOUNT_JSON_PATH_ENV = "GOOGLE_SERVICE_ACCOUNT_JSON_PATH"
_GOOGLE_SERVICE_ACCOUNT_JSON_ENV = "GOOGLE_SERVICE_ACCOUNT_JSON"
_GOOGLE_SHEET_ID_ENV = "GOOGLE_SHEET_ID"

HISTORY_WORKSHEET_NAME: str = "History"
HISTORY_HEADER_ROW = [
    "timestamp", "tmdb_id", "title", "release_year",
    "genre_names", "watch_provider", "tmdb_rating", "is_hidden_gem",
]


def get_google_sheets_config() -> Optional[Dict[str, str]]:
    """Return Google Sheets history-logging config, or None if unset.

    Reads GOOGLE_SHEET_ID plus EITHER
    GOOGLE_SERVICE_ACCOUNT_JSON_PATH (a file path — works for local
    dev, where a credentials file can sit on disk) OR
    GOOGLE_SERVICE_ACCOUNT_JSON (the credentials file's raw JSON
    content as a string — required on Streamlit Cloud, which has no
    persistent disk for a credentials file; set via the Secrets UI
    instead). Both env/secrets lookups go through _read_env_key, the
    same single credential-reading path used everywhere else in this
    module (ADR-001).

    If a JSON *path* is configured, it takes priority (checked
    first) since that's the simpler local-dev case; inline JSON
    content is the fallback for environments (like Streamlit Cloud)
    where no path is usable.

    If neither credential form is present, or GOOGLE_SHEET_ID is
    missing, the feature is simply unavailable — callers must treat
    this as "skip logging", not an error.

    Returns:
        A dict with "sheet_id" plus exactly one of "credentials_path"
        or "credentials_json", or None if not configured.
    """
    sheet_id = _read_env_key(_GOOGLE_SHEET_ID_ENV)
    if not sheet_id:
        return None

    creds_path = _read_env_key(_GOOGLE_SERVICE_ACCOUNT_JSON_PATH_ENV)
    if creds_path:
        return {"credentials_path": creds_path, "sheet_id": sheet_id}

    creds_json = _read_env_key(_GOOGLE_SERVICE_ACCOUNT_JSON_ENV)
    if creds_json:
        return {"credentials_json": creds_json, "sheet_id": sheet_id}

    return None
