"""MovieContext boundary object builder.

Implements 07_AI_INTEGRATION.md Part 1 Revision 1 (MovieContext
Ownership): converts a models.movie.Movie into a
models.movie_context.MovieContext, performing the string conversions
the Prompt Renderer requires (07 Part 1 §4).

Per 07 Part 1 §4: if overview (the field the Frozen spec names as its
explicit example) is blank, generation must fail fast rather than
send an empty value to the AI. Other optional fields (watch_provider,
tmdb_rating, genre_names) substitute a clear "not specified" string
instead of failing outright, since their absence does not undermine
script quality the way a missing plot summary would. This is an
implementation-detail interpretation of the same "never inject a
blank value" principle, not a new architecture decision.
"""

from __future__ import annotations

from models.movie import Movie
from models.movie_context import MovieContext

_TARGET_PLATFORM = "TikTok"
_NOT_SPECIFIED = "Not specified"


class MovieContextBuildError(Exception):
    """Raised when a Movie lacks data essential to script generation."""


def build_movie_context(movie: Movie) -> MovieContext:
    """Build a MovieContext from a Movie, ready for prompt rendering.

    Args:
        movie: The source movie.

    Returns:
        A fully populated MovieContext.

    Raises:
        MovieContextBuildError: If ``movie.overview`` is blank.
    """
    if not movie.overview or not movie.overview.strip():
        raise MovieContextBuildError(
            f"Movie '{movie.title}' has no overview; cannot generate a script "
            "without a plot summary (07_AI_INTEGRATION.md Part 1 §4)."
        )

    genre_names = movie.genre_names.replace("|", ", ") if movie.genre_names else _NOT_SPECIFIED
    watch_provider = movie.watch_provider.replace("|", ", ") if movie.watch_provider else _NOT_SPECIFIED
    tmdb_rating = f"{movie.tmdb_rating:.1f}" if movie.tmdb_rating is not None else _NOT_SPECIFIED

    return MovieContext(
        movie_title=movie.title,
        release_year=str(movie.release_year),
        genre_names=genre_names,
        overview=movie.overview,
        watch_provider=watch_provider,
        tmdb_rating=tmdb_rating,
        is_hidden_gem="true" if movie.is_hidden_gem else "false",
        target_platform=_TARGET_PLATFORM,
    )
