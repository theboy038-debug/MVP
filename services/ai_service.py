"""MVP orchestration for AI script generation.

This is a minimal, MVP-scoped version of the orchestration role that
07_AI_INTEGRATION.md Part 2 Revision 1 assigns to ai_service.py:
MovieContext -> Prompt -> AIProviderBase -> result.

Full responsibilities deferred to a later batch:
    - services/response_validator.py schema validation
      (07_AI_INTEGRATION.md Part 2 Revision 2)
    - script_version / script_model / script_prompt_version
      assignment for persistence (07_AI_INTEGRATION.md Part 2 §9)
    - Vault persistence (services/sheet_service.py — not yet built)

For the MVP vertical slice, this module returns the raw text the AI
provider produced, so the UI has something real to display. It does
not parse or validate the six-field JSON output schema — that
remains outside GeminiProvider's responsibility per
07_AI_INTEGRATION.md Part 2 §1, and is not yet implemented here
either (deferred, not silently skipped).
"""

from __future__ import annotations

from models.movie import Movie
from services.ai_provider.base import AIProviderBase
from services.movie_context_builder import build_movie_context
from utils.helpers import load_prompt, render_prompt


def generate_script_raw(movie: Movie, ai_provider: AIProviderBase, language: str = "English") -> str:
    """Run the MVP generation pipeline and return raw AI output text.

    Args:
        movie: The movie to generate a script for.
        ai_provider: A constructed AIProviderBase implementation
            (supplied by the caller via config.py's composition root,
            per ADR-001 — this function never constructs a provider
            itself).
        language: The output language for the script, e.g. "English"
            or "Thai". This is a user/workflow preference, not movie
            data, so it is passed separately from MovieContext (whose
            field list is fixed by 07_AI_INTEGRATION.md Part 1
            Revision 1) directly into the template variables.

    Returns:
        The raw text returned by the AI provider (unparsed).
    """
    context = build_movie_context(movie)
    template = load_prompt("default")
    rendered = render_prompt(
        template,
        {
            "movie_title": context.movie_title,
            "release_year": context.release_year,
            "genre_names": context.genre_names,
            "overview": context.overview,
            "watch_provider": context.watch_provider,
            "tmdb_rating": context.tmdb_rating,
            "is_hidden_gem": context.is_hidden_gem,
            "target_platform": context.target_platform,
            "target_language": language,
        },
    )
    response = ai_provider.generate(
        system_instruction=rendered.system_instruction,
        user_prompt=rendered.rendered_text,
    )
    return response.text
