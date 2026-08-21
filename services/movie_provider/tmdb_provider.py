"""TMDb movie provider implementation.

Implements ``MovieProviderBase`` (services/movie_provider/base.py)
against The Movie Database (TMDb) API v3, following the complete
domain contract in 06_TMDB_INTEGRATION.md v1.1:

    - Endpoint Matrix
    - Random Discovery Algorithm
    - Hidden Gem Algorithm (including the backdrop_path / status
      "Released" validation added in the v1.1 patch)
    - Watch Provider Priority (Flatrate > Ads > Rent > Buy)
    - Trailer Priority (Official Trailer > Trailer > Teaser > Clip)
    - Cache Policy (via utils/cache.py, versioned keys)
    - Retry Policy (429 only, exponential backoff)
    - Error Mapping / Exception Hierarchy

This module is an Integration Layer only. It does not perform
business orchestration, does not call ai_service.py,
sheet_service.py, response_validator.py, or any UI module, and does
not read Environment Variables directly (all configuration comes
from config.py, per ADR-001).

Authentication note: the credential resolved by config.py under the
name TMDB_API_KEY is used as a TMDb API v3 query-parameter key
(?api_key=...), matching the naming convention already established
in config.py's ADR-001 implementation (Batch 2, approved) rather than
a v4 Bearer read-access token.
"""

from __future__ import annotations

import random
import time
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

import requests

import config
from models.movie import Movie
from services.movie_provider.base import MovieProviderBase
from utils import cache
from utils.logger import get_logger, log_event

logger = get_logger(__name__)

_BASE_URL = "https://api.themoviedb.org/3"
_IMAGE_BASE_URL_FALLBACK = "https://image.tmdb.org/t/p/original"
_MAX_TMDB_PAGE = 500


# ---------------------------------------------------------------------------
# Exception hierarchy (06_TMDB_INTEGRATION.md §5, patch v1.1)
# ---------------------------------------------------------------------------


class TMDbError(Exception):
    """Base exception. UI layers must catch only this class."""


class InvalidAPIKeyError(TMDbError):
    """401 — invalid or missing API key. Never retried."""


class RateLimitError(TMDbError):
    """429 — rate limit exceeded, raised after retries are exhausted."""


class NetworkError(TMDbError):
    """Timeout or connection failure. Never retried automatically."""


class MovieNotFoundError(TMDbError):
    """404 — requested movie does not exist."""


class ConfigurationError(TMDbError):
    """500 or a malformed/unexpected response shape. Never retried."""


class DiscoveryExhaustedError(TMDbError):
    """Random/Hidden Gem discovery exceeded its retry budget without a valid candidate."""


# ---------------------------------------------------------------------------
# Module-level cached fetch functions.
#
# These MUST be defined once at module load time, not redefined inside
# an instance method on every call — Streamlit's st.cache_data (used
# via utils.cache.cached_data) identifies a cached function primarily
# by its source location, so a function object recreated on every
# call does not reliably distinguish calls by argument value.
#
# The provider instance is passed as `_provider` (leading underscore)
# so Streamlit excludes it from argument hashing (it is not
# hashable); only api_key / tmdb_id / version_key participate in the
# cache key, with version_key carrying the config-version suffix from
# utils.cache.tmdb_cache_key (06_TMDB_INTEGRATION.md §4).
# ---------------------------------------------------------------------------


@cache.cached_data(ttl_seconds=cache.get_tmdb_cache_ttl("movie_details"))
def _fetch_movie_details_raw(
    _provider: "TMDbProvider", api_key: str, tmdb_id: int, version_key: str
) -> Dict[str, Any]:
    return _provider._request("GET", f"/movie/{tmdb_id}", api_key=api_key)


@cache.cached_data(ttl_seconds=cache.get_tmdb_cache_ttl("videos"))
def _fetch_videos_raw(
    _provider: "TMDbProvider", api_key: str, tmdb_id: int, version_key: str
) -> Dict[str, Any]:
    return _provider._request("GET", f"/movie/{tmdb_id}/videos", api_key=api_key)


@cache.cached_data(ttl_seconds=cache.get_tmdb_cache_ttl("watch_providers"))
def _fetch_watch_providers_raw(
    _provider: "TMDbProvider", api_key: str, tmdb_id: int, version_key: str
) -> Dict[str, Any]:
    return _provider._request("GET", f"/movie/{tmdb_id}/watch/providers", api_key=api_key)


@cache.cached_data(ttl_seconds=cache.get_tmdb_cache_ttl("configuration"))
def _fetch_configuration_raw(
    _provider: "TMDbProvider", api_key: str, version_key: str
) -> Dict[str, Any]:
    return _provider._request("GET", "/configuration", api_key=api_key)


class TMDbProvider(MovieProviderBase):
    """Concrete ``MovieProviderBase`` implementation backed by TMDb."""

    def __init__(self, api_key: str) -> None:
        """Construct a provider bound to a resolved API key.

        The api_key is supplied by config.py's composition/factory
        functions (ADR-001); this class never reads Environment
        Variables or Secrets itself.
        """
        self._api_key = api_key
        self._session = requests.Session()

    # -- Public interface (MovieProviderBase) -------------------------------

    def discover_random(self) -> Movie:
        """Random Discovery Algorithm (06_TMDB_INTEGRATION.md).

        Never cached (Frozen Cache Policy explicitly excludes
        /discover/movie).
        """
        max_attempts = config.RANDOM_DISCOVERY_MAX_RETRIES
        attempt = 0
        last_page_results: List[Dict[str, Any]] = []

        while attempt < max_attempts:
            attempt += 1
            page = self._pick_random_discover_page(extra_params={})
            results = self._call_discover(page=page, extra_params={})
            last_page_results = results.get("results", [])

            if not last_page_results:
                continue

            candidate = random.choice(last_page_results)
            log_event(
                logger,
                "tmdb_random_discovery_attempt",
                fields={"attempt": attempt, "candidate_id": candidate.get("id")},
            )

            if self._passes_basic_validation(candidate):
                details = self.get_movie_details(candidate["id"])
                return Movie(
                    tmdb_id=details.tmdb_id,
                    title=details.title,
                    release_year=details.release_year,
                    genre_ids=details.genre_ids,
                    genre_names=details.genre_names,
                    overview=details.overview,
                    is_hidden_gem=False,
                    watch_provider=details.watch_provider,
                    watch_provider_region=details.watch_provider_region,
                    poster_url=details.poster_url,
                    backdrop_url=details.backdrop_url,
                    trailer_url=details.trailer_url,
                    tmdb_rating=details.tmdb_rating,
                    vote_count=details.vote_count,
                )

            log_event(
                logger,
                "tmdb_random_discovery_validation_failed",
                fields={"attempt": attempt, "candidate_id": candidate.get("id")},
            )

        raise DiscoveryExhaustedError(
            f"Random Discovery exhausted {max_attempts} attempts without a valid candidate."
        )

    def discover_hidden_gem(self) -> Movie:
        """Hidden Gem Algorithm (06_TMDB_INTEGRATION.md, patch v1.1).

        Applies vote_average/vote_count/adult/release_date filters at
        the query level, then validates poster/backdrop/overview/
        language client-side, then runtime/status via a detail fetch.
        Never cached.
        """
        max_attempts = config.HIDDEN_GEM_MAX_RETRIES
        attempt = 0
        rejected_in_round = 0

        extra_params = {
            "vote_average.gte": config.HIDDEN_GEM_VOTE_AVERAGE_MIN,
            "vote_count.gte": config.HIDDEN_GEM_VOTE_COUNT_MIN,
            "include_adult": str(config.TMDB_INCLUDE_ADULT).lower(),
            "primary_release_date.lte": date.today().isoformat(),
        }

        current_page_results: List[Dict[str, Any]] = []

        while attempt < max_attempts:
            attempt += 1

            if not current_page_results:
                page = self._pick_random_discover_page(extra_params=extra_params)
                response = self._call_discover(page=page, extra_params=extra_params)
                current_page_results = list(response.get("results", []))
                rejected_in_round = 0

            if not current_page_results:
                continue

            candidate = current_page_results.pop()

            if not self._passes_hidden_gem_client_filters(candidate):
                rejected_in_round += 1
                log_event(
                    logger,
                    "tmdb_hidden_gem_validation_failed",
                    fields={"attempt": attempt, "candidate_id": candidate.get("id"), "stage": "client_filter"},
                )
                self._warn_if_high_reject_rate(attempt, rejected_in_round)
                continue

            details = self.get_movie_details(candidate["id"])
            if not self._passes_hidden_gem_detail_filters(candidate):
                rejected_in_round += 1
                log_event(
                    logger,
                    "tmdb_hidden_gem_validation_failed",
                    fields={"attempt": attempt, "candidate_id": candidate.get("id"), "stage": "detail_filter"},
                )
                self._warn_if_high_reject_rate(attempt, rejected_in_round)
                continue

            log_event(
                logger,
                "tmdb_hidden_gem_discovery_success",
                fields={"attempt": attempt, "candidate_id": candidate.get("id")},
            )

            return Movie(
                tmdb_id=details.tmdb_id,
                title=details.title,
                release_year=details.release_year,
                genre_ids=details.genre_ids,
                genre_names=details.genre_names,
                overview=details.overview,
                is_hidden_gem=True,
                watch_provider=details.watch_provider,
                watch_provider_region=details.watch_provider_region,
                poster_url=details.poster_url,
                backdrop_url=details.backdrop_url,
                trailer_url=details.trailer_url,
                tmdb_rating=details.tmdb_rating,
                vote_count=details.vote_count,
            )

        raise DiscoveryExhaustedError(
            f"Hidden Gem discovery exhausted {max_attempts} attempts without a valid candidate."
        )

    def get_movie_details(self, tmdb_id: int) -> Movie:
        """Full movie detail resolution: details + genres + trailer + watch providers.

        Cached per 06_TMDB_INTEGRATION.md §Cache Policy
        (movie_details TTL), with versioned cache keys.
        """
        detail = self._get_movie_details_cached(self._api_key, tmdb_id)
        genre_names = self._resolve_genre_names(detail.get("genres", []))
        genre_ids = "|".join(str(g["id"]) for g in detail.get("genres", []))

        watch_provider, watch_provider_region = self._resolve_watch_provider(tmdb_id)
        trailer_url = self._resolve_trailer(tmdb_id)

        release_date = detail.get("release_date") or ""
        release_year = int(release_date[:4]) if release_date else 0

        poster_path = detail.get("poster_path")
        backdrop_path = detail.get("backdrop_path")
        image_base = self._get_image_base_url(self._api_key)

        return Movie(
            tmdb_id=detail["id"],
            title=detail.get("title", ""),
            release_year=release_year,
            genre_ids=genre_ids,
            genre_names=genre_names,
            overview=detail.get("overview", ""),
            is_hidden_gem=False,
            watch_provider=watch_provider,
            watch_provider_region=watch_provider_region,
            poster_url=f"{image_base}{poster_path}" if poster_path else None,
            backdrop_url=f"{image_base}{backdrop_path}" if backdrop_path else None,
            trailer_url=trailer_url,
            tmdb_rating=detail.get("vote_average"),
            vote_count=detail.get("vote_count"),
        )

    # -- Discovery helpers ----------------------------------------------------

    def _pick_random_discover_page(self, extra_params: Dict[str, Any]) -> int:
        """Fetch page 1 only to learn total_pages, then pick a random page.

        Implements 06_TMDB_INTEGRATION.md's rule against biasing
        toward page 1 by not using its results, only its
        total_pages count.
        """
        response = self._call_discover(page=1, extra_params=extra_params)
        total_pages = response.get("total_pages", 1)
        effective_max_page = min(total_pages, _MAX_TMDB_PAGE) or 1
        return random.randint(1, effective_max_page)

    def _passes_basic_validation(self, candidate: Dict[str, Any]) -> bool:
        """Random Discovery validation: poster, overview, adult=false."""
        return (
            bool(candidate.get("poster_path"))
            and bool(candidate.get("overview"))
            and candidate.get("adult") is False
        )

    def _passes_hidden_gem_client_filters(self, candidate: Dict[str, Any]) -> bool:
        """Client-side Hidden Gem checks not expressible as query params.

        vote_count upper bound, poster/backdrop/overview presence,
        and language allow-list.
        """
        vote_count = candidate.get("vote_count", 0)
        if not (config.HIDDEN_GEM_VOTE_COUNT_MIN <= vote_count <= config.HIDDEN_GEM_VOTE_COUNT_MAX):
            return False
        if not candidate.get("poster_path"):
            return False
        if not candidate.get("backdrop_path"):
            return False
        if not candidate.get("overview"):
            return False
        if candidate.get("original_language") not in config.TMDB_ALLOWED_LANGUAGES:
            return False
        return True

    def _passes_hidden_gem_detail_filters(self, candidate: Dict[str, Any]) -> bool:
        """Runtime and release status checks requiring a detail fetch."""
        detail = self._get_movie_details_cached(self._api_key, candidate["id"])
        runtime = detail.get("runtime") or 0
        status = detail.get("status")
        return runtime > config.HIDDEN_GEM_RUNTIME_MIN and status == "Released"

    def _warn_if_high_reject_rate(self, attempt: int, rejected_in_round: int) -> None:
        """Log a WARNING if over half of attempts so far were rejected.

        Per 06_TMDB_INTEGRATION.md's Hidden Gem patch note: a high
        reject rate signals the filter may be too narrow for the
        selected genre/region.
        """
        if attempt > 0 and (rejected_in_round / attempt) > 0.5:
            log_event(
                logger,
                "tmdb_hidden_gem_high_reject_rate",
                level=30,  # logging.WARNING
                fields={"attempt": attempt, "rejected_in_round": rejected_in_round},
            )

    # -- Watch Provider / Trailer resolution -----------------------------------

    def _resolve_watch_provider(self, tmdb_id: int) -> tuple[Optional[str], Optional[str]]:
        """Watch Provider Priority: Flatrate > Ads > Rent > Buy.

        Cached per watch_providers TTL. Returns (watch_provider,
        watch_provider_region); empty values if no data for the
        configured region (optional field, not an error).
        """
        response = self._get_watch_providers_cached(self._api_key, tmdb_id)
        region_data = response.get("results", {}).get(config.TMDB_DEFAULT_REGION)
        if not region_data:
            return None, None

        ordered_categories = ["flatrate", "ads", "rent", "buy"]
        names: List[str] = []
        for category in ordered_categories:
            for provider in region_data.get(category, []):
                name = provider.get("provider_name")
                if name and name not in names:
                    names.append(name)

        if not names:
            return None, None
        return "|".join(names), config.TMDB_DEFAULT_REGION

    def _resolve_trailer(self, tmdb_id: int) -> Optional[str]:
        """Trailer Priority: Official Trailer > Trailer > Teaser > Clip.

        Cached per videos TTL. Returns the YouTube URL of the
        highest-priority match, or None if none found.
        """
        response = self._get_videos_cached(self._api_key, tmdb_id)
        videos = [v for v in response.get("results", []) if v.get("site") == "YouTube"]

        def find(predicate) -> Optional[str]:
            for video in videos:
                if predicate(video):
                    return f"https://www.youtube.com/watch?v={video['key']}"
            return None

        return (
            find(lambda v: v.get("type") == "Trailer" and v.get("official") is True)
            or find(lambda v: v.get("type") == "Trailer")
            or find(lambda v: v.get("type") == "Teaser")
            or find(lambda v: v.get("type") == "Clip")
        )

    def _resolve_genre_names(self, embedded_genres: List[Dict[str, Any]]) -> str:
        """Genre names from the movie detail response's embedded genre list.

        /movie/{id} already embeds full genre objects (id + name), so
        no separate /genre/movie/list call is required for this path.
        """
        return "|".join(g["name"] for g in embedded_genres)

    def _get_image_base_url(self, api_key: str) -> str:
        """Resolve the image base URL via /configuration (cached)."""
        try:
            response = self._get_configuration_cached(api_key)
            return response.get("images", {}).get("secure_base_url", _IMAGE_BASE_URL_FALLBACK) + "original"
        except TMDbError:
            return _IMAGE_BASE_URL_FALLBACK

    # -- Cached fetch wrappers --------------------------------------------------
    # Thin instance-method wrappers around the module-level cached
    # functions defined above, supplying the versioned cache key.

    def _get_movie_details_cached(self, api_key: str, tmdb_id: int) -> Dict[str, Any]:
        return _fetch_movie_details_raw(self, api_key, tmdb_id, cache.tmdb_cache_key("movie_details"))

    def _get_videos_cached(self, api_key: str, tmdb_id: int) -> Dict[str, Any]:
        return _fetch_videos_raw(self, api_key, tmdb_id, cache.tmdb_cache_key("videos"))

    def _get_watch_providers_cached(self, api_key: str, tmdb_id: int) -> Dict[str, Any]:
        return _fetch_watch_providers_raw(self, api_key, tmdb_id, cache.tmdb_cache_key("watch_providers"))

    def _get_configuration_cached(self, api_key: str) -> Dict[str, Any]:
        return _fetch_configuration_raw(self, api_key, cache.tmdb_cache_key("configuration"))

    # -- Low-level request handling: retry + error mapping ----------------------

    def _call_discover(self, page: int, extra_params: Dict[str, Any]) -> Dict[str, Any]:
        """Uncached /discover/movie call — never cached per Frozen Cache Policy."""
        params = {
            "page": page,
            "include_adult": str(config.TMDB_INCLUDE_ADULT).lower(),
            **extra_params,
        }
        return self._request("GET", "/discover/movie", api_key=self._api_key, params=params)

    def _request(
        self,
        method: str,
        path: str,
        api_key: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Execute a single TMDb API call with retry-on-429 and error mapping.

        Retry policy (06_TMDB_INTEGRATION.md §Retry Policy): only
        429 is retried, with exponential backoff
        (base * 2^attempt_index), up to
        config.TMDB_RETRY_MAX_ATTEMPTS attempts. All other error
        codes are mapped and raised immediately without retry.
        """
        url = f"{_BASE_URL}{path}"
        query = {"api_key": api_key, **(params or {})}

        attempt = 0
        while True:
            attempt += 1
            start = time.monotonic()
            try:
                response = self._session.request(
                    method,
                    url,
                    params=query,
                    timeout=config.TMDB_REQUEST_TIMEOUT_SECONDS,
                )
            except requests.exceptions.Timeout as exc:
                log_event(logger, "tmdb_request_timeout", level=40, fields={"path": path})
                raise NetworkError(f"TMDb request to {path} timed out.") from exc
            except requests.exceptions.RequestException as exc:
                log_event(logger, "tmdb_network_error", level=40, fields={"path": path, "error": str(exc)})
                raise NetworkError(f"TMDb request to {path} failed: {exc}") from exc

            elapsed_ms = int((time.monotonic() - start) * 1000)

            if response.status_code == 200:
                log_event(
                    logger,
                    "tmdb_request_success",
                    fields={"path": path, "response_time_ms": elapsed_ms},
                )
                return response.json()

            if response.status_code == 401:
                log_event(logger, "tmdb_invalid_api_key", level=40, fields={"path": path})
                raise InvalidAPIKeyError("TMDb API key is invalid.")

            if response.status_code == 404:
                log_event(logger, "tmdb_not_found", level=30, fields={"path": path})
                raise MovieNotFoundError(f"TMDb resource not found: {path}")

            if response.status_code == 429:
                if attempt >= config.TMDB_RETRY_MAX_ATTEMPTS:
                    log_event(
                        logger,
                        "tmdb_rate_limit_exhausted",
                        level=40,
                        fields={"path": path, "attempts": attempt},
                    )
                    raise RateLimitError("TMDb rate limit exceeded; retries exhausted.")
                delay = config.TMDB_RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1))
                log_event(
                    logger,
                    "tmdb_rate_limit_retry",
                    level=30,
                    fields={"path": path, "attempt": attempt, "delay_seconds": delay},
                )
                time.sleep(delay)
                continue

            if response.status_code == 500:
                log_event(logger, "tmdb_server_error", level=40, fields={"path": path})
                raise ConfigurationError(f"TMDb server error on {path}.")

            log_event(
                logger,
                "tmdb_unexpected_status",
                level=40,
                fields={"path": path, "status_code": response.status_code},
            )
            raise ConfigurationError(
                f"Unexpected TMDb response status {response.status_code} on {path}."
            )
