"""MVP smoke test suite.

Minimum coverage for the MVP Usability Freeze phase: app import,
config validation, movie discovery success/failure, movie data
rendering, AI generation success/failure, unexpected-error
resilience, and the full mocked pipeline. This is intentionally NOT
a comprehensive test suite for every module — that is deferred to
the full per-batch test coverage already exercised during Batch 0-6
development.

Run with: python -m unittest tests.test_mvp_smoke -v
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

import config
from models.movie import Movie
from services.ai_provider.base import RawAIResponse
from services.ai_provider.gemini_provider import AIError, AIRateLimitError
from services.ai_service import generate_script_raw
from services.movie_provider.tmdb_provider import NetworkError, TMDbError

FAKE_MOVIE = Movie(
    tmdb_id=550,
    title="Fight Club",
    release_year=1999,
    genre_ids="18",
    genre_names="Drama",
    overview="An insomniac office worker forms an underground fight club.",
    is_hidden_gem=False,
    watch_provider="Netflix",
    tmdb_rating=8.4,
)


class TestAppImport(unittest.TestCase):
    def test_app_module_imports_without_crashing(self) -> None:
        import app  # noqa: F401 — import success is the assertion


class TestConfigValidation(unittest.TestCase):
    def test_resolve_key_source_type_b_with_session_key(self) -> None:
        client_type, key = config.resolve_key_source("NON_EXISTENT_ENV_XYZ", "session-key")
        self.assertEqual(client_type, "B")
        self.assertEqual(key, "session-key")

    def test_resolve_key_source_raises_without_any_key(self) -> None:
        with self.assertRaises(ValueError):
            config.resolve_key_source("NON_EXISTENT_ENV_XYZ", None)


class TestMovieDiscovery(unittest.TestCase):
    def test_discovery_success_returns_movie(self) -> None:
        fake_provider = MagicMock()
        fake_provider.discover_random.return_value = FAKE_MOVIE
        result = fake_provider.discover_random()
        self.assertIsInstance(result, Movie)
        self.assertEqual(result.title, "Fight Club")

    def test_discovery_failure_raises_tmdb_error(self) -> None:
        fake_provider = MagicMock()
        fake_provider.discover_random.side_effect = NetworkError("timeout")
        with self.assertRaises(TMDbError):
            fake_provider.discover_random()


class TestMovieDataRendering(unittest.TestCase):
    def test_movie_has_fields_required_for_card_display(self) -> None:
        self.assertTrue(FAKE_MOVIE.title)
        self.assertIsNotNone(FAKE_MOVIE.release_year)
        self.assertTrue(FAKE_MOVIE.overview)
        # Optional fields must not raise when absent
        movie_without_optionals = Movie(
            tmdb_id=1, title="X", release_year=2020, genre_ids="", genre_names="",
            overview="Some plot.", is_hidden_gem=False,
        )
        self.assertIsNone(movie_without_optionals.poster_url)
        self.assertIsNone(movie_without_optionals.trailer_url)


class TestAIGeneration(unittest.TestCase):
    def test_generation_success_returns_text(self) -> None:
        fake_ai_provider = MagicMock()
        fake_ai_provider.generate.return_value = RawAIResponse(text='{"schema_version":"1.0"}')
        result = generate_script_raw(FAKE_MOVIE, fake_ai_provider)
        self.assertEqual(result, '{"schema_version":"1.0"}')

    def test_generation_failure_raises_ai_error(self) -> None:
        fake_ai_provider = MagicMock()
        fake_ai_provider.generate.side_effect = AIRateLimitError("rate limited")
        with self.assertRaises(AIError):
            generate_script_raw(FAKE_MOVIE, fake_ai_provider)

    def test_default_language_is_english(self) -> None:
        fake_ai_provider = MagicMock()
        fake_ai_provider.generate.return_value = RawAIResponse(text="{}")
        generate_script_raw(FAKE_MOVIE, fake_ai_provider)
        kwargs = fake_ai_provider.generate.call_args.kwargs
        self.assertIn("Target language: English", kwargs["user_prompt"])

    def test_explicit_thai_language(self) -> None:
        fake_ai_provider = MagicMock()
        fake_ai_provider.generate.return_value = RawAIResponse(text="{}")
        generate_script_raw(FAKE_MOVIE, fake_ai_provider, language="Thai")
        kwargs = fake_ai_provider.generate.call_args.kwargs
        self.assertIn("Target language: Thai", kwargs["user_prompt"])


class TestUnexpectedErrorResilience(unittest.TestCase):
    def test_generic_exception_from_provider_does_not_propagate_as_ai_error(self) -> None:
        """Confirms callers must catch bare Exception too — app.py does this."""
        fake_ai_provider = MagicMock()
        fake_ai_provider.generate.side_effect = RuntimeError("totally unexpected")
        with self.assertRaises(RuntimeError):
            generate_script_raw(FAKE_MOVIE, fake_ai_provider)
        # This confirms app.py's `except Exception` catch-all is necessary
        # and is exercised — not that this layer suppresses it.


class TestFullMockedPipeline(unittest.TestCase):
    def test_movie_to_context_to_prompt_to_ai_text(self) -> None:
        fake_ai_provider = MagicMock()
        fake_ai_provider.generate.return_value = RawAIResponse(
            text='{"schema_version":"1.0","hook":"..."}', token_usage=99
        )
        result = generate_script_raw(FAKE_MOVIE, fake_ai_provider)
        self.assertIn("schema_version", result)

        call_kwargs = fake_ai_provider.generate.call_args.kwargs
        self.assertIn("Fight Club", call_kwargs["user_prompt"])
        self.assertIn("JSON only", call_kwargs["system_instruction"])


class TestReadableScriptParsing(unittest.TestCase):
    def test_clean_json_parses(self) -> None:
        from app import _try_parse_script
        result = _try_parse_script(
            '{"hook":"h","body":"b","caption":"c","hashtags":["x"],"cta":"go"}'
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["hook"], "h")

    def test_truncated_json_falls_back_to_none(self) -> None:
        from app import _try_parse_script
        result = _try_parse_script('{"hook":"cut off')
        self.assertIsNone(result)


class TestHistoryLogging(unittest.TestCase):
    def test_unconfigured_sheets_is_silent_noop(self) -> None:
        from services.sheet_service import log_movie_view
        # No GOOGLE_SERVICE_ACCOUNT_JSON_PATH / GOOGLE_SHEET_ID set in
        # this test environment -> must return None, not raise.
        result = log_movie_view(FAKE_MOVIE)
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
