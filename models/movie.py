"""Transient representation of a movie retrieved from TMDb.

This model holds the fields produced by the TMDb discovery/detail
pipeline (06_TMDB_INTEGRATION.md), before any decision has been made
to persist it into the Vault. It is not itself persisted; when the
user chooses to save, a :class:`models.vault.VaultEntry` is built
from this data (plus workflow metadata such as status/notes).

Field formats mirror the persisted snapshot format already defined
in 05_DATABASE_SCHEMA.md v1.2 (pipe-separated strings for
multi-valued fields), so that no new in-memory shape is invented
between discovery and persistence.

This module contains no I/O, no API calls, and no business logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class Movie:
    """A single movie as returned by the TMDb discovery/detail flow.

    Attributes:
        tmdb_id: TMDb's unique identifier for this movie. Used as the
            Vault dedup key (05_DATABASE_SCHEMA.md §Dedup Key Rule).
        title: Movie title.
        release_year: Year of release.
        genre_ids: Pipe-separated TMDb genre IDs, e.g. "18|53|80".
        genre_names: Pipe-separated genre names, e.g.
            "Drama|Thriller|Crime". Presentation only; never used for
            filtering (05_DATABASE_SCHEMA.md).
        overview: Plot summary text from TMDb.
        is_hidden_gem: Whether this movie was surfaced via the Hidden
            Gem discovery algorithm rather than Random Discovery
            (06_TMDB_INTEGRATION.md).
        watch_provider: Pipe-separated watch provider names, ordered
            by priority (Flatrate > Ads > Rent > Buy). Optional; may
            be empty if no provider data exists for the region.
        watch_provider_region: ISO 3166-1 alpha-2 region code the
            watch_provider data was resolved against (e.g. "TH").
            Optional.
        poster_url: Full poster image URL. Optional.
        backdrop_url: Full backdrop image URL. Optional.
        trailer_url: YouTube URL of the highest-priority trailer
            found (Official Trailer > Trailer > Teaser > Clip).
            Optional; empty if none found.
        tmdb_rating: TMDb vote_average at time of retrieval. Optional.
        vote_count: TMDb vote_count at time of retrieval. Optional.
    """

    tmdb_id: int
    title: str
    release_year: int
    genre_ids: str
    genre_names: str
    overview: str
    is_hidden_gem: bool
    watch_provider: Optional[str] = None
    watch_provider_region: Optional[str] = None
    poster_url: Optional[str] = None
    backdrop_url: Optional[str] = None
    trailer_url: Optional[str] = None
    tmdb_rating: Optional[float] = None
    vote_count: Optional[int] = None
