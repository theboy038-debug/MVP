"""Normalized movie context passed to the prompt system.

Per 07_AI_INTEGRATION.md Part 1 (Revision 1 — MovieContext Ownership),
the Prompt Loader/Renderer must never read TMDb data or
``models.movie.Movie`` / ``models.vault.VaultEntry`` directly. This
dataclass is the single boundary object between "movie data" and
"prompt variables": every field here corresponds 1:1 to a prompt
placeholder defined in 07_AI_INTEGRATION.md Part 1 §4.

All fields are strings, because prompt templates only accept string
substitution (07_AI_INTEGRATION.md Part 1 §4 — "ตัวแปรทั้งหมดต้อง
เป็น string ก่อน inject เสมอ"). Converting typed values (e.g. bool,
float, pipe-separated lists) into these display strings is the
responsibility of the MovieContext Builder (services layer), not of
this module.

This module contains no I/O, no API calls, and no business logic.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MovieContext:
    """Prompt-ready, provider-agnostic view of a single movie.

    Attributes:
        movie_title: Maps to the ``{movie_title}`` placeholder.
        release_year: Maps to the ``{release_year}`` placeholder.
        genre_names: Maps to the ``{genre_names}`` placeholder
            (comma-separated, already converted from the pipe-
            separated storage format).
        overview: Maps to the ``{overview}`` placeholder.
        watch_provider: Maps to the ``{watch_provider}`` placeholder
            (comma-separated).
        tmdb_rating: Maps to the ``{tmdb_rating}`` placeholder.
        is_hidden_gem: Maps to the ``{is_hidden_gem}`` placeholder
            (the literal string "true" or "false").
        target_platform: Maps to the ``{target_platform}`` placeholder.
            Fixed to "TikTok" for v1.
    """

    movie_title: str
    release_year: str
    genre_names: str
    overview: str
    watch_provider: str
    tmdb_rating: str
    is_hidden_gem: str
    target_platform: str
