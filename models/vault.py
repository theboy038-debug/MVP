"""Persisted Vault entry model.

This module mirrors the Google Sheets "Vault" worksheet schema
defined in 05_DATABASE_SCHEMA.md v1.2, field for field. Any new field
must be added to that document first; this module is a reflection of
it, never the other way around.

Per ADR-002 (naming convention), this file owns ONLY the data class
(``VaultEntry``) and the ``VaultStatus`` enum. Rendering functions
for the Vault live separately in ``ui/vault.py``.

This module contains no I/O, no API calls, and no business logic
(e.g. no dedup enforcement — that belongs to services/sheet_service.py
per 05_DATABASE_SCHEMA.md §Dedup Key Rule).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class VaultStatus(str, Enum):
    """Vault entry workflow status.

    Values are defined exactly as specified in
    05_DATABASE_SCHEMA.md §status Enum. This is the single source of
    truth for these values; no other value may be used anywhere in
    the system.
    """

    DRAFT = "draft"
    SCRIPTED = "scripted"
    EDITED = "edited"
    PUBLISHED = "published"
    ARCHIVED = "archived"


@dataclass
class VaultEntry:
    """A single row of the Vault worksheet (05_DATABASE_SCHEMA.md v1.2).

    Field order and required/optional status mirror the frozen schema
    table exactly.

    Attributes:
        id: Internal primary key (UUID4 string).
        tmdb_id: TMDb identifier; the Vault dedup key.
        title: Movie title.
        release_year: Year of release.
        genre_ids: Pipe-separated TMDb genre IDs.
        genre_names: Pipe-separated genre names (presentation only).
        watch_provider: Pipe-separated watch provider names. Optional.
        watch_provider_region: ISO 3166-1 alpha-2 region code paired
            with watch_provider. Optional.
        is_hidden_gem: Whether this entry originated from Hidden Gem
            discovery mode.
        script_version: Increments on each successful (re)generation.
            Optional; absent if no script has ever been generated.
        script_model: AI model name used for the current script.
            Optional.
        script_prompt_version: Prompt template/version used for the
            current script, e.g. "default_1". Optional.
        script_text: Serialized AI script output. Optional.
        poster_url: Snapshot poster URL at time of save. Optional.
        backdrop_url: Snapshot backdrop URL at time of save. Optional.
        trailer_url: Snapshot trailer URL at time of save. Optional.
        tmdb_rating: Snapshot TMDb rating at time of save. Optional.
        vote_count: Snapshot TMDb vote count at time of save. Optional.
        notes: Free-text user notes. Optional.
        status: Current workflow status.
        created_at: ISO 8601 UTC timestamp of creation.
        updated_at: ISO 8601 UTC timestamp of last update.
    """

    id: str
    tmdb_id: int
    title: str
    release_year: int
    genre_ids: str
    genre_names: str
    is_hidden_gem: bool
    status: VaultStatus
    created_at: str
    updated_at: str
    watch_provider: Optional[str] = None
    watch_provider_region: Optional[str] = None
    script_version: Optional[int] = None
    script_model: Optional[str] = None
    script_prompt_version: Optional[str] = None
    script_text: Optional[str] = None
    poster_url: Optional[str] = None
    backdrop_url: Optional[str] = None
    trailer_url: Optional[str] = None
    tmdb_rating: Optional[float] = None
    vote_count: Optional[int] = None
    notes: Optional[str] = None
