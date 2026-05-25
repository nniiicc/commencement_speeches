# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Scope of this pipeline

This repo is the **2026 pilot** of a commencement-speech corpus. It discovers, per pilot institution:

1. The universitywide commencement speaker (LLM extraction over web search results).
2. Transcript link(s) — institutional HTML/PDF, C-SPAN page, etc.
3. Video link(s) — YouTube first, then Vimeo / Panopto / Kaltura via per-institution overrides.

It deliberately does **not** download audio, run Whisper, or extract transcript text. Those are downstream pipelines that will read from `transcript_links` / `video_links`. Do not add them here — they belong in separate flows (see "Expansion path" in README.md). Departmental convocations are also out of scope; Step 1 explicitly discards them (see `DiscardedCandidate`).

## Commands

Setup uses `uv` per repo conventions (README shows `python -m venv` but `uv venv` + `uv pip install -e ".[dev]"` is preferred).

```bash
commencement init-db                                  # create SQLite schema
commencement frame                                    # Stage 0: IPEDS HD download + stratified sample
commencement frame --reload                           # drop & reload institutions table
commencement discover --mode initial                  # all three steps for every pilot institution
commencement discover --mode catch-late               # re-run gaps (low confidence or not_found links)
commencement discover --mode future                   # only future-dated ceremonies
commencement discover --mode institution --ipeds-id 166027  # single-institution debug
commencement export --version 1                       # versioned export to exports/

pytest                                                # full test suite
pytest tests/test_stratify.py::test_name -x           # single test
ruff format . && ruff check .                         # format + lint
mypy src/                                             # type check
```

Required env: `ANTHROPIC_API_KEY`, `TAVILY_API_KEY`. Optional: `YOUTUBE_API_KEY` (otherwise falls back to `yt-dlp ytsearch`), `USER_AGENT`, `DB_URL`, `OBJECT_STORE_DIR`. See `.env.example`.

## Architecture

**Config is the single source of truth.** All tunables — sample size, seed, pilot year, model names, rate limits, date windows, override file paths — live in [src/commencement/config.py](src/commencement/config.py) as a frozen `Config` dataclass exposed as `CONFIG`. Do not introduce tunables elsewhere; add them here and import.

**Two flows, both Prefect:**

- `stage0_frame.flow.flow_frame_construction` — downloads IPEDS HD (tries `IPEDS_HD_YEAR_CANDIDATES` newest-first), loads `institutions`, draws a stratified sample of `PILOT_SAMPLE_SIZE` rows using `RANDOM_SEED`, and records per-stratum draw counts to `pilot_sample_log` for reproducibility. Stratification logic is [src/commencement/stage0_frame/stratify.py](src/commencement/stage0_frame/stratify.py).
- `discovery.flow.flow_discovery` — walks pilot institutions for the chosen mode and calls Steps 1→2→3 sequentially per institution. Each run writes a `DiscoveryRun` row with mode, target count, seed, and a summary JSON.

**Discovery modes** are SQL filters over `(Institution.in_pilot, Ceremony.year == PILOT_YEAR, Ceremony.ceremony_status, link statuses, identity_confidence)`. See `_select_targets` in [src/commencement/discovery/flow.py](src/commencement/discovery/flow.py); `tests/test_mode_filters.py` pins this behavior. Adding a new mode means updating both `_select_targets`, the CLI's `--mode` choice list, and the test.

**Step 1 (speaker):** web search → LLM extraction. Source HTML is content-addressed into `BlobStore` under `OBJECT_STORE_DIR`, with a `sources` row keyed by SHA hash; blob writes are idempotent (`tests/test_blob_store.py`). The LLM extractor uses `LLM_MODEL_EXTRACTION` by default and escalates to `LLM_MODEL_HARD_PAGES` for hard pages. `identity_method` records whether the source was an official press release vs. third-party news; downstream coverage analysis depends on this distinction.

**Step 2 (transcript link):** records pointers only. `source_tier` distinguishes institutional transcript (Tier 1) from C-SPAN (Tier 2). Append-only; multiple links per ceremony are expected.

**Step 3 (video link):** YouTube search (API if `YOUTUBE_API_KEY` set, else `yt-dlp ytsearch`) filtered by `YOUTUBE_DURATION_MIN_SECONDS` and `YOUTUBE_DATE_WINDOW_DAYS`. Non-YouTube platforms come exclusively from `overrides/video_platforms.yaml` — there's no general crawler for Vimeo/Panopto/Kaltura. Override schema is documented in README.

**Search is pluggable.** `search/base.py` defines the interface; `tavily_provider.py` is the only implementation. `get_search_provider()` is the seam to mock in tests.

**Database is SQLite by default** (`sqlite:///data/corpus.sqlite`). All cross-row coverage statistics (transcript availability by stratum, link counts by tier) are computed from the schema; the export step writes versioned CSV/Parquet to `exports/` including `coverage_by_stratum_v{n}.csv`. Schema is created via `Base.metadata.create_all` in `db.session.init_schema` — there is no Alembic in the pilot. Postgres is the documented upgrade path; if you switch, swap `DB_URL` and add migrations.

## Conventions specific to this repo

- **Universitywide only.** Step 1 must discard per-college / departmental ceremonies into `discarded_candidates` rather than recording them. When tweaking the LLM prompt, preserve this.
- **Don't reintroduce text extraction / Whisper.** If a task seems to need transcript bodies, stop and confirm — that's a separate downstream pipeline.
- **Link statuses are tri-state**: `not_searched` (default) ≠ `not_found` (we looked) ≠ `found`. Catch-late mode depends on this distinction.
- **`ceremony_date` may be null.** `ceremony_status` is the authoritative past/future/unknown flag and is what filters use.
- **Pilot year is fixed in CONFIG.** Don't hardcode 2026; read `CONFIG.PILOT_YEAR`.
- **Bias caveat (from README, load-bearing):** coverage rates skew by institutional resourcing. Tier-1 institutional transcripts and Tier-3 videos are not equivalent artifacts; analysis must hold tier fixed.
