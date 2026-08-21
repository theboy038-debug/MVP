"""Gemini AI provider implementation.

Implements ``AIProviderBase`` (services/ai_provider/base.py) against
Google's ``google-genai`` SDK, following
07_AI_INTEGRATION.md Part 2 v1.1:

    - AI Provider Abstraction (§1)
    - Model Configuration (§2)
    - Generation Parameters (§3)
    - Retry Policy (§4)
    - Custom Exception Hierarchy (§6)

This module is an Integration Layer only. It performs a single,
stateless, synchronous generation call and returns an unparsed
``RawAIResponse``. It does not parse or validate the business Script
schema (that is services/response_validator.py, Batch 7), does not
render or load prompts (that is utils/helpers.py, Batch 5), and does
not orchestrate any workflow (that is services/ai_service.py,
Batch 8). It does not read Environment Variables directly — the
api_key is supplied by config.py's composition/factory functions
(ADR-001).

SDK usage verified against the actually-installed ``google-genai``
package (not assumed): ``genai.Client(api_key=...)``,
``client.models.generate_content(model=..., contents=..., config=...)``,
and ``types.GenerateContentConfig`` fields
(system_instruction, temperature, top_p, max_output_tokens,
response_mime_type, safety_settings).
"""

from __future__ import annotations

import time
from typing import Optional

import httpx

from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types

import config
from services.ai_provider.base import AIProviderBase, RawAIResponse
from utils.logger import get_logger, log_event

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Exception hierarchy (07_AI_INTEGRATION.md Part 2 §6)
# ---------------------------------------------------------------------------


class AIError(Exception):
    """Base exception. UI layers must catch only this class."""


class AIInvalidAPIKeyError(AIError):
    """Authentication failure. Never retried."""


class AIRateLimitError(AIError):
    """Rate limit exceeded, raised after retries are exhausted."""


class AINetworkError(AIError):
    """Timeout or connection failure."""


class AISchemaValidationError(AIError):
    """Reserved for the response-validation layer (Batch 7).

    Not raised by this module — GeminiProvider never parses or
    validates the business output schema
    (07_AI_INTEGRATION.md Part 2 §1: "ไม่ parse business schema เอง").
    """


class AIContentBlockedError(AIError):
    """Response was blocked by the provider's safety filter. Never retried."""


class AIConfigurationError(AIError):
    """Invalid configuration (e.g. bad model name) or an unexpected server error."""


class GeminiProvider(AIProviderBase):
    """Concrete ``AIProviderBase`` implementation backed by Gemini."""

    supports_json_mode = True
    supports_streaming = True
    supports_system_prompt = True
    supports_images = False

    def __init__(self, api_key: str) -> None:
        """Construct a provider bound to a resolved API key.

        The api_key is supplied by config.py's composition/factory
        functions (ADR-001); this class never reads Environment
        Variables or Secrets itself.
        """
        self._client = genai.Client(
            api_key=api_key,
            http_options=genai_types.HttpOptions(
                timeout=config.AI_REQUEST_TIMEOUT_SECONDS * 1000,  # SDK expects milliseconds
            ),
        )

    def generate(self, system_instruction: str, user_prompt: str) -> RawAIResponse:
        """Generate a single, stateless response from Gemini.

        Retry policy (07_AI_INTEGRATION.md Part 2 §4): only rate-limit
        and network failures are retried, with exponential backoff,
        up to config.AI_RETRY_MAX_ATTEMPTS attempts.
        AIInvalidAPIKeyError and AIContentBlockedError are never
        retried.
        """
        generation_config = genai_types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=config.AI_TEMPERATURE,
            top_p=config.AI_TOP_P,
            max_output_tokens=config.AI_MAX_OUTPUT_TOKENS,
            response_mime_type="application/json",
            # BUGFIX: thinking_budget (used previously) is a
            # Gemini-2.5-only parameter. Gemini 3.x models (including
            # gemini-3.6-flash) replaced it with thinking_level, a
            # string enum (MINIMAL/LOW/MEDIUM/HIGH). Sending
            # thinking_budget to a 3.x model returns
            # 400 INVALID_ARGUMENT. Using LOW rather than MINIMAL:
            # MINIMAL has an additional thought-signature requirement
            # on some models that doesn't apply to our stateless,
            # single-turn, non-tool-calling generation flow, but LOW
            # avoids that edge case entirely while still keeping
            # latency/cost low for this simple text-generation task.
            thinking_config=genai_types.ThinkingConfig(
                thinking_level=genai_types.ThinkingLevel.LOW
            ),
        )

        attempt = 0
        while True:
            attempt += 1
            start = time.monotonic()
            try:
                response = self._client.models.generate_content(
                    model=config.AI_MODEL_NAME,
                    contents=user_prompt,
                    config=generation_config,
                )
            except genai_errors.ClientError as exc:
                status_code = getattr(exc, "code", None)

                if status_code in (401, 403):
                    log_event(logger, "ai_invalid_api_key", level=40, fields={"model": config.AI_MODEL_NAME})
                    raise AIInvalidAPIKeyError("Gemini API key is invalid.") from exc

                if status_code == 429:
                    if attempt >= config.AI_RETRY_MAX_ATTEMPTS:
                        log_event(
                            logger,
                            "ai_rate_limit_exhausted",
                            level=40,
                            fields={"model": config.AI_MODEL_NAME, "attempts": attempt},
                        )
                        raise AIRateLimitError("Gemini rate limit exceeded; retries exhausted.") from exc
                    delay = config.AI_RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1))
                    log_event(
                        logger,
                        "ai_rate_limit_retry",
                        level=30,
                        fields={"model": config.AI_MODEL_NAME, "attempt": attempt, "delay_seconds": delay},
                    )
                    time.sleep(delay)
                    continue

                log_event(
                    logger,
                    "ai_client_error",
                    level=40,
                    fields={"model": config.AI_MODEL_NAME, "status_code": status_code, "error": str(exc)},
                )
                raise AIConfigurationError(f"Gemini client error (status {status_code}): {exc}") from exc

            except genai_errors.ServerError as exc:
                log_event(
                    logger,
                    "ai_server_error",
                    level=40,
                    fields={"model": config.AI_MODEL_NAME, "error": str(exc)},
                )
                raise AIConfigurationError(f"Gemini server error: {exc}") from exc

            except (httpx.TimeoutException, httpx.TransportError) as exc:
                # BUGFIX: google-genai's underlying HTTP client is httpx,
                # which raises httpx.TimeoutException / httpx.TransportError
                # (NOT Python's builtin TimeoutError / ConnectionError,
                # which are never subclasses of these). The previous
                # `except (TimeoutError, ConnectionError)` clause could
                # structurally never match a real network timeout,
                # letting it fall through uncaught. Confirmed via
                # introspection: httpx.ReadTimeout / httpx.ConnectError
                # do not inherit from the builtin exceptions.
                event_name = "ai_request_timeout" if isinstance(exc, httpx.TimeoutException) else "ai_network_error"
                if attempt >= config.AI_RETRY_MAX_ATTEMPTS:
                    log_event(
                        logger,
                        f"{event_name}_exhausted",
                        level=40,
                        fields={"model": config.AI_MODEL_NAME, "attempts": attempt},
                    )
                    raise AINetworkError(f"Gemini request failed after {attempt} attempts: {exc}") from exc
                delay = config.AI_RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1))
                log_event(
                    logger,
                    event_name,
                    level=30,
                    fields={"model": config.AI_MODEL_NAME, "attempt": attempt, "delay_seconds": delay},
                )
                time.sleep(delay)
                continue

            elapsed_ms = int((time.monotonic() - start) * 1000)

            if self._is_blocked(response):
                log_event(
                    logger,
                    "ai_content_blocked",
                    level=30,
                    fields={"model": config.AI_MODEL_NAME},
                )
                raise AIContentBlockedError("Gemini blocked the response due to safety filtering.")

            text = self._extract_text(response)
            token_usage = self._extract_token_usage(response)

            log_event(
                logger,
                "ai_generation_event",
                fields={
                    "provider_name": "gemini",
                    "model_name": config.AI_MODEL_NAME,
                    "generation_time_ms": elapsed_ms,
                    "token_usage": token_usage,
                    "retry_count": attempt - 1,
                    "status": "success",
                },
            )
            return RawAIResponse(text=text, token_usage=token_usage)

    # -- Response parsing (raw only — no business schema logic) --------------

    def _is_blocked(self, response: "genai_types.GenerateContentResponse") -> bool:
        candidates = getattr(response, "candidates", None) or []
        if not candidates:
            return True
        finish_reason = getattr(candidates[0], "finish_reason", None)
        return str(finish_reason) in {"SAFETY", "FinishReason.SAFETY"}

    def _extract_text(self, response: "genai_types.GenerateContentResponse") -> str:
        text = getattr(response, "text", None)
        if text is None:
            raise AIConfigurationError("Gemini response contained no text content.")
        return text

    def _extract_token_usage(self, response: "genai_types.GenerateContentResponse") -> Optional[int]:
        usage = getattr(response, "usage_metadata", None)
        if usage is None:
            return None
        return getattr(usage, "total_token_count", None)
