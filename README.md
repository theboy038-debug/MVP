# แอบดูหนัง — Random Movie & Content Hub

A Streamlit application for TikTok content creators that shortens the
workflow from movie discovery to publishing: randomize a movie,
review its details, generate a TikTok script with AI, and manage a
content vault backed by Google Sheets.

## Status

Specification phase is complete. All architecture, UX, database,
integration, and implementation contracts are frozen in the Project
Bible (see below). Production code implementation is in progress.

## Project Bible

This project is developed against a frozen set of specification
documents ("Project Bible"), which are the single source of truth
for all requirements, architecture, UX, schema, and integration
contracts. Implementation must not contradict these documents; any
conflict discovered during implementation is reported rather than
resolved silently.

| Doc | Title | Scope |
|---|---|---|
| 00 | Project Index | Master index, registry, change log |
| 01 | System Architect Prompt | Global rules, dependency map |
| 02 | Product Requirements | Scope, users, priorities |
| 03 | Software Architecture | Structure, layering, ADRs |
| 04 | UI/UX Spec (Parts 1–3) | UX foundation, screens, components |
| 05 | Database Schema | Google Sheets Vault/Meta schema |
| 06 | TMDb Integration | Movie discovery domain logic |
| 07 | AI Integration (Parts 1–2) | Prompt contract, AI runtime |
| 08 | Implementation Spec | Module wiring, session state, event flow |

## Project Structure

```
project/
    app.py                # Entry point — routing and layout only
    config.py              # Configuration and client composition root
    services/               # Business orchestration, providers, persistence
    ui/                      # Presentation layer only
    models/                   # Data structures
    utils/                     # Generic, reusable helpers
    prompts/                    # AI prompt assets (system prompt, templates)
    assets/                      # Static assets
    logs/                         # Runtime log output
    cache/                         # Runtime cache storage
```

See `08_IMPLEMENTATION_SPEC.md` for the full module structure and
dependency rules.

## Setup

### 1. Install

Unzip the package, then open a terminal **inside the folder that
directly contains `requirements.txt`** (on Windows: after extracting,
open the extracted folder in File Explorer, check the address bar
shows the folder with `requirements.txt`/`app.py` directly inside it
— not a folder containing another folder — then right-click →
"Open in Terminal", or `cd` there manually).

```bash
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

If you see `Could not open requirements file`, you're one folder
level off — run `dir` (Windows) or `ls` (Mac/Linux) and confirm
`requirements.txt` is listed before retrying.

### 2. Configure API keys

Three options — pick whichever suits you:

**Option A — `.env` file (recommended for repeated local use):**

```bash
cp .env.example .env
```

Then open `.env` in a text editor and fill in:

```
TMDB_API_KEY=your-tmdb-api-key
GEMINI_API_KEY=your-gemini-api-key
```

The app loads `.env` automatically at startup — no need to re-export
variables every time you open a new terminal. **Never commit your
real `.env` file** (only `.env.example`, which has no real secrets,
is safe to share).

**Option B — Environment variables (per-terminal-session):**

```bash
export TMDB_API_KEY="your-tmdb-api-key"
export GEMINI_API_KEY="your-gemini-api-key"
```

Get a TMDb API key at https://www.themoviedb.org/settings/api and a
Gemini API key at https://ai.google.dev/.

**Option C — Enter keys in the app itself:** if neither of the above
is set, the app's sidebar shows two password fields (TMDb API Key,
Gemini API Key) where you can paste them in directly per session.

### 3. (Optional) Set up viewing history in Google Sheets

Skip this entirely if you don't want it — the app works fully
without it, it's a nice-to-have.

1. Go to https://console.cloud.google.com/, create a project (or use
   an existing one)
2. Enable the **Google Sheets API** for that project
3. Create a **Service Account** (APIs & Services → Credentials →
   Create Credentials → Service Account), then create a JSON key for
   it and download the file
4. Create a Google Sheet (or use an existing one), then **share it**
   with the service account's email address (found inside the JSON
   key file, looks like `xxx@xxx.iam.gserviceaccount.com`) — give it
   **Editor** access
5. Copy the Sheet's ID from its URL:
   `https://docs.google.com/spreadsheets/d/`**`THIS_PART`**`/edit`
6. Add both to your `.env`:
   ```
   GOOGLE_SERVICE_ACCOUNT_JSON_PATH=/full/path/to/your-downloaded-key.json
   GOOGLE_SHEET_ID=the-sheet-id-from-step-5
   ```

A worksheet named `History` will be created automatically on first
use, with a header row. Every movie you discover gets logged as one
row (timestamp, TMDb ID, title, year, genres, watch provider,
rating, hidden-gem flag). If Sheets isn't configured, or something
goes wrong (bad credentials, sheet not shared, network issue), the
app shows a small warning but **never stops working** — history
logging never blocks discovery or script generation.

**Deploying to Streamlit Cloud?** Cloud deployments have no
persistent disk, so a `GOOGLE_SERVICE_ACCOUNT_JSON_PATH` file won't
exist there — use `GOOGLE_SERVICE_ACCOUNT_JSON` instead (the JSON
file's *contents*, not a path), set via Streamlit Cloud's **Settings
→ Secrets** UI in TOML format:

```toml
TMDB_API_KEY = "your-tmdb-api-key"
GEMINI_API_KEY = "your-gemini-api-key"
GOOGLE_SHEET_ID = "your-sheet-id"
GOOGLE_SERVICE_ACCOUNT_JSON = """
{
  "type": "service_account",
  "project_id": "...",
  "private_key": "...",
  "client_email": "...",
  ...
}
"""
```

Paste this directly into the Streamlit Cloud Secrets UI — **never**
commit real credentials into any file in your repo. Locally, prefer
`GOOGLE_SERVICE_ACCOUNT_JSON_PATH` (a file path) via `.env` instead —
simpler for local dev, and keeps the actual key file out of your
repo entirely (`.gitignore` already excludes common credential
filenames — double check it covers whatever you name yours).

> ⚠️ If you ever paste real API keys or a service-account private
> key into a chat, doc, or public place by mistake, rotate/regenerate
> that credential immediately — treat it as compromised the moment
> it left a secrets manager.

### 4. Run

```bash
streamlit run app.py
```

Open the URL Streamlit prints (usually http://localhost:8501).

### 5. Current MVP workflow

1. (If needed) enter API keys in the sidebar
2. Click "สุ่มหนัง (Random Discovery)" to pull a random movie from TMDb
3. Review the movie card (poster, info, trailer, watch providers)
4. Choose the output language (English by default, or ภาษาไทย)
5. Click "Generate Script" to get an AI-generated TikTok script from Gemini, shown broken into Hook / Body / Caption / Hashtags / CTA (raw JSON is available in a collapsible section if you need it)

### 6. Not yet implemented (deferred)

Full Content Vault workflow (status tracking, editing, dedup
enforcement per the original schema), Statistics dashboard, Hidden
Gem discovery mode in the UI, script regeneration as a separate
labeled action. The Google Sheets integration that exists now is a
lightweight viewing-history log only — not the full Vault feature.

### 7. Testing

```bash
python -m unittest tests.test_mvp_smoke -v
```
