"""Prompt loading/rendering pipeline data objects.

Per 07_AI_INTEGRATION.md Part 2 (Revision 4 — Prompt Rendering), the
prompt pipeline is split into two immutable stages:

    PromptLoader   -> PromptTemplate   (raw, not yet injected)
    PromptRenderer -> RenderedPrompt   (final, ready for AIProviderBase)

The previously used ``PromptAsset`` object is deprecated and must
never be reintroduced (per the Post-Patch Consistency Audit on
07_AI_INTEGRATION.md). Only ``PromptTemplate`` and ``RenderedPrompt``
are valid representations of a prompt at any stage.

This module contains no I/O, no file reading, and no business logic
(manifest lookup, placeholder validation, and variable injection all
belong to services/utils, not to these data objects).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PromptTemplate:
    """A loaded, not-yet-rendered prompt template.

    Output of the Prompt Loader (07_AI_INTEGRATION.md Part 1 §3,
    Part 2 Revision 4). Still contains unresolved ``{placeholder}``
    markers in ``template_body``.

    Attributes:
        system_instruction: Raw system instruction text. Never
            contains placeholders (07_AI_INTEGRATION.md Part 1 §2).
        template_body: Raw template text, still containing
            ``{placeholder}`` markers.
        template_name: Name of the template, e.g. "default".
        version: Template version number, cross-checked against
            ``prompts/manifest.json`` (07_AI_INTEGRATION.md Part 1
            Revision 3).
        supported_schema_version: Output schema version this template
            is expected to produce, e.g. "1.0".
    """

    system_instruction: str
    template_body: str
    template_name: str
    version: int
    supported_schema_version: str


@dataclass
class RenderedPrompt:
    """A fully rendered prompt, ready to send to an AI provider.

    Output of the Prompt Renderer (07_AI_INTEGRATION.md Part 2
    Revision 4). All placeholders have been substituted with values
    from a :class:`models.movie_context.MovieContext`.

    Attributes:
        system_instruction: Final system instruction text.
        rendered_text: Final user prompt text, with all placeholders
            resolved.
        prompt_version: Identifier combining template name and
            version, e.g. "default_1"
            (07_AI_INTEGRATION.md Part 1 §9).
    """

    system_instruction: str
    rendered_text: str
    prompt_version: str
