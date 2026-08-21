"""Prompt loading and rendering utilities.

Implements 07_AI_INTEGRATION.md Part 1 (Prompt Contract: Loading
Strategy, Placeholder Rules, Prompt Validation) and Part 2
Revision 4 (Prompt Rendering split — PromptLoader / PromptRenderer).

This module owns ONLY prompt asset loading and variable rendering.
It performs no AI provider calls, no business orchestration, and no
persistence — those belong to services/ai_service.py and
services/response_validator.py (07_AI_INTEGRATION.md Part 2
Revision 1/2), which are out of scope for this batch.

``PromptAsset`` is deprecated per the Post-Patch Consistency Audit on
07_AI_INTEGRATION.md and must never be reintroduced; only
``PromptTemplate`` and ``RenderedPrompt``
(models/prompt_template.py, Batch 1) are valid representations of a
prompt at any stage.

KNOWN GAP (flagged, not silently resolved): 07_AI_INTEGRATION.md
Part 1 §3 requires ``load_prompt`` to be cached via ``st.cache_data``
with a TTL "10-60 minutes" — a range, not a Frozen exact value, and
no ``config.py`` constant exists for it (Batch 2's approved scope did
not include this value). Applying caching here would require either
patching the already-closed Batch 2 (``config.py``) or inventing a
magic literal outside of config ownership, per
08_IMPLEMENTATION_SPEC.md §11. Per the Batch 5 execution rule
("ห้ามแก้ Batch ก่อนหน้าเพื่อให้ Batch 5 ผ่าน — หาก contract ไม่ตรง
ให้หยุดรายงานก่อน"), ``load_prompt`` below is fully functional but
UNCACHED. Caching must be added once the TTL value's home is decided.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Mapping

from models.prompt_template import PromptTemplate, RenderedPrompt

# ---------------------------------------------------------------------------
# Known prompt variables (07_AI_INTEGRATION.md Part 1 §4)
# ---------------------------------------------------------------------------

KNOWN_PLACEHOLDERS = frozenset(
    {
        "movie_title",
        "release_year",
        "genre_names",
        "overview",
        "watch_provider",
        "tmdb_rating",
        "is_hidden_gem",
        "target_platform",
        # target_language: NOT part of MovieContext (07 Part1
        # Revision1's field list is movie data only) — this is a
        # user/workflow preference supplied separately by
        # services/ai_service.py's caller. Added here because any
        # placeholder used in templates.md must be in this known-set
        # (Part 1 §5/§6 validation).
        "target_language",
    }
)

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
_MANIFEST_PATH = _PROMPTS_DIR / "manifest.json"
_SYSTEM_PROMPT_PATH = _PROMPTS_DIR / "system_prompt.md"
_TEMPLATES_PATH = _PROMPTS_DIR / "templates.md"

_PLACEHOLDER_PATTERN = re.compile(r"\{([a-z_]+)\}")
_TEMPLATE_HEADER_PATTERN = re.compile(r"^## template:\s*(\S+)\s*$", re.MULTILINE)
_VERSION_COMMENT_PATTERN = re.compile(r"<!--\s*version:\s*(\d+)\s*-->")


class PromptNotFoundError(Exception):
    """Raised when a requested template does not exist or is inactive.

    Per 07_AI_INTEGRATION.md Part 1 Revision 3 (manifest loading,
    steps 3-4): both "no manifest entry" and "entry exists but
    active is false" are treated identically as not found.
    """


class PromptValidationError(Exception):
    """Raised when a prompt fails template- or injection-level validation.

    Per 07_AI_INTEGRATION.md Part 1 §6, this covers:
    - An unrecognized placeholder appears in the template
      (template-level, checked by the Loader).
    - The manifest version does not match the templates.md version
      comment (Revision 3, loading step 7).
    - A placeholder remains unresolved after rendering
      (injection-level, checked by the Renderer).
    - A supplied variable value is blank.
    """


def _load_manifest() -> Dict[str, Any]:
    """Read and parse prompts/manifest.json."""
    with _MANIFEST_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _find_manifest_entry(manifest: Mapping[str, Any], template_name: str) -> Dict[str, Any]:
    """Return the manifest entry for ``template_name``.

    Raises:
        PromptNotFoundError: If no entry matches, or the matching
            entry has ``active`` set to False.
    """
    for entry in manifest.get("templates", []):
        if entry.get("name") == template_name:
            if not entry.get("active", False):
                raise PromptNotFoundError(
                    f"Template '{template_name}' exists in the manifest but is not active."
                )
            return entry
    raise PromptNotFoundError(f"Template '{template_name}' is not defined in the manifest.")


def _load_system_prompt() -> str:
    """Read prompts/system_prompt.md verbatim (no placeholders expected)."""
    return _SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")


def _load_template_body(template_name: str, expected_version: int) -> str:
    """Extract one named template section from prompts/templates.md.

    Args:
        template_name: The template name to locate, e.g. "default".
        expected_version: The version number from the manifest, used
            to cross-check against the section's version comment.

    Returns:
        The raw template body text, with placeholders still
        unresolved.

    Raises:
        PromptNotFoundError: If no matching section header exists.
        PromptValidationError: If the section's version comment does
            not match ``expected_version``.
    """
    content = _TEMPLATES_PATH.read_text(encoding="utf-8")
    headers = list(_TEMPLATE_HEADER_PATTERN.finditer(content))

    for index, match in enumerate(headers):
        if match.group(1) != template_name:
            continue
        section_start = match.end()
        section_end = headers[index + 1].start() if index + 1 < len(headers) else len(content)
        section_text = content[section_start:section_end]

        version_match = _VERSION_COMMENT_PATTERN.search(section_text)
        if version_match is None:
            raise PromptValidationError(
                f"Template '{template_name}' section has no version comment."
            )
        actual_version = int(version_match.group(1))
        if actual_version != expected_version:
            raise PromptValidationError(
                f"Template '{template_name}' version mismatch: manifest says "
                f"{expected_version}, templates.md says {actual_version}."
            )

        body = section_text[version_match.end() :]
        body = body.split("\n---", 1)[0]
        return body.strip()

    raise PromptNotFoundError(f"Template '{template_name}' has no section in templates.md.")


def _validate_known_placeholders(template_body: str) -> None:
    """Ensure every placeholder in ``template_body`` is a known variable.

    Implements 07_AI_INTEGRATION.md Part 1 §6, template-level
    validation layer (performed by the Loader).

    Raises:
        PromptValidationError: If an unrecognized placeholder is
            found.
    """
    found = set(_PLACEHOLDER_PATTERN.findall(template_body))
    unknown = found - KNOWN_PLACEHOLDERS
    if unknown:
        raise PromptValidationError(
            f"Template contains unknown placeholder(s): {', '.join(sorted(unknown))}"
        )


def load_prompt(template_name: str = "default") -> PromptTemplate:
    """Load a prompt template by name.

    Implements the Loading Strategy from 07_AI_INTEGRATION.md
    Part 1 §3 and Revision 3 (manifest-driven loading, steps 1-7);
    step 8 (attaching supported_schema_version) is fulfilled by
    populating the returned PromptTemplate.

    NOT YET CACHED — see module docstring "KNOWN GAP". Caching per
    07_AI_INTEGRATION.md Part 1 §3 is pending a decision on where the
    TTL constant should live.

    Args:
        template_name: Name of the template to load, matching a
            "name" entry in prompts/manifest.json.

    Returns:
        A :class:`models.prompt_template.PromptTemplate` with
        placeholders not yet resolved.

    Raises:
        PromptNotFoundError: If the template does not exist or is
            inactive.
        PromptValidationError: If the manifest/templates.md versions
            disagree, or an unknown placeholder is present.
    """
    manifest = _load_manifest()
    entry = _find_manifest_entry(manifest, template_name)
    version = int(entry["version"])

    system_instruction = _load_system_prompt()
    template_body = _load_template_body(template_name, expected_version=version)
    _validate_known_placeholders(template_body)

    return PromptTemplate(
        system_instruction=system_instruction,
        template_body=template_body,
        template_name=template_name,
        version=version,
        supported_schema_version=str(entry["supported_schema_version"]),
    )


def render_prompt(template: PromptTemplate, variables: Mapping[str, str]) -> RenderedPrompt:
    """Render a loaded template into a final, provider-ready prompt.

    Implements 07_AI_INTEGRATION.md Part 2 Revision 4
    (PromptRenderer) and Part 1 §6 injection-level validation.

    Args:
        template: A :class:`models.prompt_template.PromptTemplate`
            returned by :func:`load_prompt`.
        variables: A flat string-to-string mapping, typically derived
            from a :class:`models.movie_context.MovieContext`. Every
            value must already be a string (07_AI_INTEGRATION.md
            Part 1 §4 — type conversion happens before this call, in
            the MovieContext Builder, which is out of scope for this
            batch).

    Returns:
        A :class:`models.prompt_template.RenderedPrompt` with all
        placeholders resolved.

    Raises:
        PromptValidationError: If a supplied variable value is blank,
            or if any placeholder remains unresolved after rendering.
    """
    for key, value in variables.items():
        if value is None or value == "":
            raise PromptValidationError(f"Prompt variable '{key}' must not be blank.")

    rendered_text = template.template_body
    for key, value in variables.items():
        rendered_text = rendered_text.replace(f"{{{key}}}", value)

    leftover = _PLACEHOLDER_PATTERN.findall(rendered_text)
    if leftover:
        raise PromptValidationError(
            f"Unresolved placeholder(s) remain after rendering: "
            f"{', '.join(sorted(set(leftover)))}"
        )

    return RenderedPrompt(
        system_instruction=template.system_instruction,
        rendered_text=rendered_text,
        prompt_version=f"{template.template_name}_{template.version}",
    )
