"""Transient AI-generated script output.

Fields mirror the JSON Output Schema defined in
07_AI_INTEGRATION.md Part 1 §8 (including ``schema_version``, per
Revision 2), plus the versioning metadata that
07_AI_INTEGRATION.md Part 2 §9 (Script Version Management) requires
the orchestration layer to attach before a script can be written to
a :class:`models.vault.VaultEntry` (script_version, script_model,
script_prompt_version).

This object exists only in memory between AI generation and the
moment the user chooses to save; it is never itself persisted, and
it is not the source of truth for the Vault's ``status`` or
``notes`` fields.

This module contains no I/O, no API calls, and no business logic
(e.g. no JSON parsing or schema validation — that belongs to
services/response_validator.py per 07_AI_INTEGRATION.md Part 2
Revision 2).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass
class Script:
    """A single AI-generated script, validated and version-tagged.

    Attributes:
        schema_version: Output schema version reported by the AI
            provider, e.g. "1.0".
        hook: Opening line intended for the first ~3 seconds.
        body: Main script content.
        caption: Post caption text.
        hashtags: List of hashtag strings, without the leading "#".
        cta: Closing call-to-action text.
        script_version: Version number for this VaultEntry's script;
            increments on each successful (re)generation
            (07_AI_INTEGRATION.md Part 2 §9).
        script_model: Name of the AI model that produced this script.
        script_prompt_version: Identifier of the prompt
            template/version used, e.g. "default_1".
    """

    schema_version: str
    hook: str
    body: str
    caption: str
    cta: str
    script_version: int
    script_model: str
    script_prompt_version: str
    hashtags: List[str] = field(default_factory=list)
