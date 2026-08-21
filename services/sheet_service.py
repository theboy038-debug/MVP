"""Movie viewing history logger (Google Sheets).

This is a lightweight "what have I already viewed" log — appends one
row per movie the user discovers/views. It is intentionally NOT the
full Content Vault feature described in 05_DATABASE_SCHEMA.md
(VaultEntry schema, status workflow, dedup enforcement, script
persistence, CRUD editing) — that remains deferred. This module logs
history only, using gspread as the concrete implementation for the
"Repository role" defined in 08_IMPLEMENTATION_SPEC.md §9 for this
smaller-scoped feature.

Design principle: logging is best-effort and must NEVER block or
crash the main discovery/generation flow. If Google Sheets isn't
configured, unreachable, or the credentials are invalid, the caller
gets a clear exception it can catch and ignore/display a soft
warning for — it must not propagate as an unhandled crash.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import gspread
from gspread.exceptions import WorksheetNotFound

import config
from models.movie import Movie
from utils.logger import get_logger, log_event

logger = get_logger(__name__)


class HistoryLogError(Exception):
    """Raised when a history-log write fails. Callers should catch this
    and degrade gracefully (skip logging), never let it crash the UI.
    """


def _build_client(sheets_config: Dict[str, str]) -> "gspread.Client":
    """Construct a gspread client from either credential mode.

    Supports two mutually exclusive forms from
    config.get_google_sheets_config():
        - "credentials_path": a file path (local dev)
        - "credentials_json": the raw JSON content as a string
          (Streamlit Cloud, via st.secrets — no persistent disk
          available for a credentials file, so a temp file is
          neither needed nor used; gspread.service_account_from_dict
          takes the parsed credentials directly in memory)

    Raises:
        HistoryLogError: If the JSON content is present but not
            valid JSON.
    """
    if "credentials_path" in sheets_config:
        return gspread.service_account(filename=sheets_config["credentials_path"])

    try:
        info = json.loads(sheets_config["credentials_json"])
    except (json.JSONDecodeError, ValueError) as exc:
        raise HistoryLogError(
            f"GOOGLE_SERVICE_ACCOUNT_JSON is not valid JSON: {exc}"
        ) from exc
    return gspread.service_account_from_dict(info)


def _get_or_create_history_worksheet(spreadsheet: "gspread.Spreadsheet") -> "gspread.Worksheet":
    """Return the History worksheet, creating it with headers if absent."""
    try:
        return spreadsheet.worksheet(config.HISTORY_WORKSHEET_NAME)
    except WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(
            title=config.HISTORY_WORKSHEET_NAME,
            rows=1000,
            cols=len(config.HISTORY_HEADER_ROW),
        )
        worksheet.append_row(config.HISTORY_HEADER_ROW)
        return worksheet


def log_movie_view(movie: Movie) -> None:
    """Append one row to the History worksheet for a viewed movie.

    Silently does nothing if Google Sheets isn't configured
    (config.get_google_sheets_config() returns None) — this is by
    design (best-effort, optional feature), not an error condition.

    Args:
        movie: The movie that was just discovered/viewed.

    Raises:
        HistoryLogError: If Sheets IS configured but the write fails
            (bad credentials, sheet not shared with the service
            account, network error, etc). Callers must catch this.
    """
    sheets_config = config.get_google_sheets_config()
    if sheets_config is None:
        return

    try:
        client = _build_client(sheets_config)
        spreadsheet = client.open_by_key(sheets_config["sheet_id"])
        worksheet = _get_or_create_history_worksheet(spreadsheet)

        row = [
            datetime.now(timezone.utc).isoformat(),
            movie.tmdb_id,
            movie.title,
            movie.release_year,
            movie.genre_names or "",
            movie.watch_provider or "",
            movie.tmdb_rating if movie.tmdb_rating is not None else "",
            "true" if movie.is_hidden_gem else "false",
        ]
        worksheet.append_row(row)
        log_event(logger, "history_log_success", fields={"tmdb_id": movie.tmdb_id})
    except HistoryLogError:
        raise
    except Exception as exc:
        log_event(
            logger, "history_log_failed", level=40,
            fields={"tmdb_id": movie.tmdb_id, "error": str(exc)},
        )
        raise HistoryLogError(f"Failed to log movie view to Google Sheets: {exc}") from exc
