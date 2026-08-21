"""Streamlit application entry point.

MVP vertical slice: Random Discovery -> Movie Card -> AI generation.

Per 03_SOFTWARE_ARCHITECTURE.md, this file owns ONLY routing, layout,
and state initialization — no business logic. Provider construction
goes through config.py's composition root (ADR-001); discovery and
generation logic live in the provider/service layer, not here.

Full navigation (04_UI_UX_SPEC.md Part 1 §5: Discover / Vault /
Statistics) is deferred to a later batch; this MVP implements the
Discover flow only, per the MVP Scope Cut. Vault, Statistics, full
regenerate/persistence workflows, and UX polish beyond basic error
handling are intentionally out of scope for this slice.

History logging (Google Sheets) is a separate, lightweight feature
distinct from the deferred full Vault — see services/sheet_service.py
for scope notes. It is best-effort: failures show a soft warning and
never block the discovery/generation flow.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional

import streamlit as st

import config
from models.movie import Movie
from services.ai_service import generate_script_raw
from services.ai_provider.gemini_provider import AIError
from services.movie_provider.tmdb_provider import TMDbError
from services.sheet_service import HistoryLogError, log_movie_view
from utils.logger import get_logger, log_event

logger = get_logger(__name__)

st.set_page_config(page_title="แอบดูหนัง", page_icon="🎬", layout="centered")

_LANGUAGE_OPTIONS = {"English": "English", "ภาษาไทย": "Thai"}


def _init_session_state() -> None:
    st.session_state.setdefault("tmdb_api_key", "")
    st.session_state.setdefault("gemini_api_key", "")
    st.session_state.setdefault("current_movie", None)
    st.session_state.setdefault("ai_result", None)
    st.session_state.setdefault("output_language_label", "English")


def _render_sidebar() -> None:
    with st.sidebar:
        st.header("API Keys")
        st.caption("Only needed if this deployment doesn't already have server-side keys configured (ADR-001 Type B).")
        st.session_state["tmdb_api_key"] = st.text_input(
            "TMDb API Key", value=st.session_state["tmdb_api_key"], type="password"
        )
        st.session_state["gemini_api_key"] = st.text_input(
            "Gemini API Key", value=st.session_state["gemini_api_key"], type="password"
        )


def _render_movie_card(movie: Movie) -> None:
    if movie.poster_url:
        st.image(movie.poster_url, width=300)
    st.subheader(f"{movie.title} ({movie.release_year})")
    st.caption(movie.genre_names.replace("|", ", ") if movie.genre_names else "—")
    if movie.tmdb_rating is not None:
        st.write(f"⭐ {movie.tmdb_rating:.1f}/10")
    if movie.watch_provider:
        st.write(f"📺 {movie.watch_provider.replace('|', ', ')}")
    if movie.trailer_url:
        st.video(movie.trailer_url)
    st.write(movie.overview)
    if movie.is_hidden_gem:
        st.info("💎 Hidden Gem pick")


def _try_parse_script(raw_text: str) -> Optional[Dict[str, Any]]:
    """Best-effort parse of the AI's raw JSON output, for display only.

    This is NOT the full services/response_validator.py pipeline
    (07_AI_INTEGRATION.md Part 2 Revision 2, still deferred) — just
    enough to render the script in readable form, with a graceful
    fallback to raw text display if parsing fails for any reason.
    """
    text = raw_text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    required = {"hook", "body", "caption", "hashtags", "cta"}
    if not required.issubset(data.keys()):
        return None
    return data


def _render_script(raw_text: str) -> None:
    parsed = _try_parse_script(raw_text)
    if parsed is None:
        st.caption("แสดงผลดิบ (ไม่สามารถแยกส่วนได้ตามรูปแบบที่คาดไว้)")
        st.code(raw_text, language="json")
        return

    st.markdown("**🎬 Hook**")
    st.write(parsed["hook"])
    st.markdown("**📜 Body**")
    st.write(parsed["body"])
    st.markdown("**📝 Caption**")
    st.write(parsed["caption"])
    hashtags = parsed.get("hashtags") or []
    if hashtags:
        st.markdown("**#️⃣ Hashtags**")
        st.write(" ".join(f"#{tag}" for tag in hashtags))
    st.markdown("**👉 Call to action**")
    st.write(parsed["cta"])

    with st.expander("Raw JSON"):
        st.code(raw_text, language="json")


def _render_discovery() -> None:
    st.header("🎲 Discover")

    if st.button("สุ่มหนัง (Random Discovery)", type="primary"):
        try:
            provider = config.get_movie_provider_client(
                session_key=st.session_state["tmdb_api_key"] or None
            )
        except ValueError:
            st.error("กรุณาใส่ TMDb API Key ในแถบด้านซ้ายก่อน")
            return

        with st.spinner("กำลังสุ่มหนัง..."):
            try:
                movie = provider.discover_random()
                st.session_state["current_movie"] = movie
                st.session_state["ai_result"] = None
            except TMDbError as exc:
                log_event(logger, "app_tmdb_error", level=40, fields={"error": str(exc)})
                st.error("ไม่สามารถสุ่มหนังได้ในขณะนี้ กรุณาลองใหม่อีกครั้ง")
                return
            except Exception as exc:  # never crash UI (03 §Error Handling)
                log_event(logger, "app_unexpected_error", level=40, fields={"error": str(exc)})
                st.error("เกิดข้อผิดพลาดที่ไม่คาดคิด กรุณาลองใหม่อีกครั้ง")
                return

        # History logging: best-effort, never blocks the main flow.
        try:
            log_movie_view(movie)
        except HistoryLogError as exc:
            log_event(logger, "app_history_log_error", level=30, fields={"error": str(exc)})
            st.warning("บันทึกประวัติลง Google Sheets ไม่สำเร็จ (ไม่กระทบการใช้งานหลัก)")

    movie: Optional[Movie] = st.session_state.get("current_movie")
    if movie is None:
        st.caption("กดปุ่มด้านบนเพื่อเริ่มสุ่มหนัง")
        return

    _render_movie_card(movie)

    st.divider()
    st.header("✨ AI Script")

    language_label = st.radio(
        "Output language",
        options=list(_LANGUAGE_OPTIONS.keys()),
        index=list(_LANGUAGE_OPTIONS.keys()).index(st.session_state["output_language_label"]),
        horizontal=True,
    )
    st.session_state["output_language_label"] = language_label

    if st.button("Generate Script"):
        try:
            ai_provider = config.get_ai_provider_client(
                session_key=st.session_state["gemini_api_key"] or None
            )
        except ValueError:
            st.error("กรุณาใส่ Gemini API Key ในแถบด้านซ้ายก่อน")
            return

        with st.spinner("กำลังสร้างสคริปต์..."):
            try:
                language = _LANGUAGE_OPTIONS[st.session_state["output_language_label"]]
                text = generate_script_raw(movie, ai_provider, language=language)
                st.session_state["ai_result"] = text
            except AIError as exc:
                log_event(logger, "app_ai_error", level=40, fields={"error": str(exc)})
                st.error("ไม่สามารถสร้างสคริปต์ได้ในขณะนี้ กรุณาลองใหม่อีกครั้ง")
            except Exception as exc:
                log_event(logger, "app_unexpected_error", level=40, fields={"error": str(exc)})
                st.error("เกิดข้อผิดพลาดที่ไม่คาดคิด กรุณาลองใหม่อีกครั้ง")

    result = st.session_state.get("ai_result")
    if result:
        _render_script(result)


def main() -> None:
    _init_session_state()
    _render_sidebar()
    st.title("แอบดูหนัง 🎬")
    _render_discovery()


if __name__ == "__main__":
    main()
