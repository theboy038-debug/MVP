"""Abstract interface for AI text-generation providers.

Per 07_AI_INTEGRATION.md Part 2 §1 (AI Provider Abstraction) and §3
(Provider Capability — Revision 3), all AI generation calls go
through this interface so that a future provider (Claude, GPT) could
be substituted without changing business logic or UI.

Gemini is the only concrete implementation in v1
(services/ai_provider/gemini_provider.py).

This module contains no implementation logic, no API calls, and no
configuration/secrets access.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class RawAIResponse:
    """Unparsed text response from an AI provider.

    This is the return type of :meth:`AIProviderBase.generate`. It
    intentionally holds raw text only — JSON parsing and schema
    validation happen later, in services/response_validator.py
    (07_AI_INTEGRATION.md Part 2 §7 / Revision 2), not here.

    Attributes:
        text: The raw text returned by the provider, before any
            markdown-fence stripping or JSON parsing.
        token_usage: Token usage reported by the provider, if
            available. Optional, since not every provider reports
            this (07_AI_INTEGRATION.md Part 2 Revision 5).
    """

    text: str
    token_usage: Optional[int] = None


class AIProviderBase(ABC):
    """Abstract contract for an AI text-generation provider.

    Concrete implementations must:

    - Declare all four capability flags below as class attributes.
    - Raise only the exception hierarchy defined in
      07_AI_INTEGRATION.md Part 2 §6 (AIError and its subclasses) —
      this base class does not define exceptions itself.

    Capability flags (07_AI_INTEGRATION.md Part 2 Revision 3):
        supports_json_mode: Whether the provider can be instructed to
            return JSON-only output.
        supports_streaming: Whether the provider supports streaming
            responses. Not used by any business logic in v1
            (07_AI_INTEGRATION.md Part 2 §12 — synchronous only).
        supports_system_prompt: Whether the provider accepts a
            separate system instruction.
        supports_images: Whether the provider accepts image input.
            Not used in v1.
    """

    supports_json_mode: bool
    supports_streaming: bool
    supports_system_prompt: bool
    supports_images: bool

    @abstractmethod
    def generate(self, system_instruction: str, user_prompt: str) -> RawAIResponse:
        """Generate a raw text response from the AI provider.

        Implements a single, stateless, synchronous generation call
        (07_AI_INTEGRATION.md Part 2 §10 — Token Optimization
        Strategy: no conversation history is sent).

        Args:
            system_instruction: The final system instruction text
                (from a rendered prompt).
            user_prompt: The final user prompt text (from a rendered
                prompt).

        Returns:
            A :class:`RawAIResponse` containing the unparsed provider
            output.
        """
        raise NotImplementedError
