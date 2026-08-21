"""Abstract interface for movie data providers.

Per 06_TMDB_INTEGRATION.md §7 (Future Compatibility) and
08_IMPLEMENTATION_SPEC.md §10, all movie data access goes through
this interface so that a future provider (OMDb, Trakt, Letterboxd)
could be substituted without changing the UI or orchestration layer.

TMDb is the only concrete implementation in v1
(services/movie_provider/tmdb_provider.py).

This module contains no implementation logic, no API calls, and no
configuration/secrets access.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from models.movie import Movie


class MovieProviderBase(ABC):
    """Abstract contract for a movie data provider.

    Concrete implementations must raise only the exception hierarchy
    defined in 06_TMDB_INTEGRATION.md §5 (TMDbError and its
    subclasses) — this base class does not define exceptions itself,
    since exception ownership belongs to 06_TMDB_INTEGRATION.md, not
    to this interface module.
    """

    @abstractmethod
    def discover_random(self) -> Movie:
        """Return a single movie via the Random Discovery algorithm.

        Implements 06_TMDB_INTEGRATION.md §Random Discovery Algorithm.

        Returns:
            A fully populated :class:`models.movie.Movie` with
            ``is_hidden_gem`` set to False.
        """
        raise NotImplementedError

    @abstractmethod
    def discover_hidden_gem(self) -> Movie:
        """Return a single movie via the Hidden Gem algorithm.

        Implements 06_TMDB_INTEGRATION.md §Hidden Gem Algorithm.

        Returns:
            A fully populated :class:`models.movie.Movie` with
            ``is_hidden_gem`` set to True.
        """
        raise NotImplementedError

    @abstractmethod
    def get_movie_details(self, tmdb_id: int) -> Movie:
        """Return full details for a specific movie by TMDb ID.

        Implements the ``/movie/{id}`` endpoint contract from
        06_TMDB_INTEGRATION.md §Endpoint Matrix, including trailer
        and watch provider resolution.

        Args:
            tmdb_id: The TMDb identifier of the movie to retrieve.

        Returns:
            A fully populated :class:`models.movie.Movie`.
        """
        raise NotImplementedError
