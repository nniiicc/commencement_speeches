---
name: commencement-speaker-list-finder
description: Given a list of US universities, find each institution's own published roster of historical commencement speakers — the kind of page UPenn, Syracuse, Notre Dame, NC State, Auburn, UNCG, and Tufts maintain in their archives or commencement offices. Verify each candidate page is a real comprehensive speaker list (not a one-year press release or curated "best of"). Emit a single CSV catalog. Use this skill when the user asks to find commencement speaker lists, build a catalog of commencement speaker archives, audit institutions for archive coverage, or asks which universities publish a historical roster of commencement speakers.
---

# Commencement Speaker List Finder

A deterministic discovery + verification pipeline that catalogs the pages on which US universities publish their historical commencement speaker rosters. The skill produces a catalog of pages, not the speakers themselves — row-by-row parsing is downstream.

## When to use this skill

Trigger on phrases like:
- "find commencement speaker lists for [these schools]"
- "build a catalog of commencement speaker archives"
- "which of these universities publishes a historical roster of commencement speakers"
- "audit our institution list for archive coverage"

Do NOT trigger for: single-year speaker lookups, transcript fetching, or video discovery — those belong to the live discovery pipeline.

## Quickstart

```bash
cd skills/commencement-speaker-list-finder
pip install -r requirements.txt

# Single-institution probe (prints CSV row to stdout)
python scripts/probe_institution.py \
  --name "University of Pennsylvania" \
  --homepage https://www.upenn.edu/

# Batch over an input CSV (columns: name, homepage_url, optionally ipeds_id)
python scripts/batch_catalog.py \
  --input examples/sample_institutions.csv \
  --output catalogs/speaker_lists_catalog.csv

# Validate against the bundled truth set
pytest tests/
```

## How it works

For each input institution the pipeline:

1. **Enumerates** ~12 candidate URLs under the institution's registered domain — `archives.{domain}`, `library.{domain}`, `commencement.{domain}`, `secretary.{domain}`, plus provost / trustees PDF patterns. See `reference/url_patterns.md`.
2. **Fetches** each candidate politely (User-Agent, robots, rate-limit, exponential backoff). See `scripts/fetch.py`.
3. **Classifies** the response with a deterministic four-rule heuristic (year count + structural regularity + commencement keywords + monotonicity). No LLM in the loop. See `scripts/classify_page.py`.
4. **Detects the parser shape** for confirmed lists (table / paragraph-with-bold-year / PDF / per-year subpage index). See `scripts/detect_shape.py`.
5. **Falls back to Tavily site-restricted search** if zero candidates classify as `speaker_list` and `TAVILY_API_KEY` is set. Re-runs the classifier on top hits.
6. **Writes** one CSV row per confirmed list page. Multiple rows per institution are allowed (some publish both an archive and an office copy).

## Output schema

One row per confirmed `speaker_list` page. See `reference/csv_schema.md` for full column docs. Quick view:

| Column | Notes |
|---|---|
| `ipeds_id`, `institution_name`, `registered_domain` | Identity |
| `list_url`, `publisher`, `host_subdomain` | Where the list lives |
| `coverage_year_min`, `coverage_year_max`, `n_years_listed` | Completeness proxy |
| `parser_shape`, `has_transcript_links`, `has_role_column` | For the downstream extractor |
| `content_hash`, `bytes_len`, `fetched_at`, `classifier_confidence` | Provenance + QA |
| `notes` | Free-text for triage |

## Layout

```
skills/commencement-speaker-list-finder/
  SKILL.md                       this file
  requirements.txt
  reference/
    url_patterns.md              the URL family list, with example URLs per pattern
    page_shapes.md               annotated parser-shape examples
    csv_schema.md                output CSV column docs
    known_good_lists.csv         hand-curated truth set
  scripts/
    fetch.py                     rate-limited polite fetcher
    enumerate_urls.py            domain -> candidate URL list
    classify_page.py             heuristic verifier (HTML + PDF)
    detect_shape.py              parser-shape dispatcher
    probe_institution.py         single-institution entrypoint
    batch_catalog.py             input CSV -> catalog CSV
    tavily_search.py             optional site-restricted search fallback
  examples/
    sample_institutions.csv      5-row pilot input
  tests/
    test_classifier.py
    test_url_enumeration.py
    test_detect_shape.py
    fixtures/                    HTML samples covering each parser_shape
  catalogs/                      output goes here (gitignored)
```

## Configuration

Environment variables (all optional except where noted):

| Var | Purpose | Default |
|---|---|---|
| `USER_AGENT` | HTTP User-Agent | `commencement-speaker-list-finder/0.1 (contact: you@example.com)` |
| `RATE_LIMIT_PER_DOMAIN_RPS` | Requests/sec per domain | `1.0` |
| `HTTP_TIMEOUT_SECONDS` | Per-request timeout | `20` |
| `HTTP_MAX_RETRIES` | Retries on 429/5xx | `3` |
| `TAVILY_API_KEY` | Enables the fallback site search | unset (fallback disabled) |

## What it does NOT do

- Parse rows out of confirmed lists. The catalog records the page; row extraction is a separate downstream job that dispatches on `parser_shape`.
- Reconcile against an existing ceremonies DB. The skill is read-only against the input and write-only to the catalog CSV.
- Fetch transcript text from per-year subpages. The `has_transcript_links` flag tells the next pipeline where to go; nothing more.
- Use an LLM for classification. Pure heuristics keep it cheap, reproducible, and debuggable.

## Evaluation target

Against `reference/known_good_lists.csv` (13 positives, 5 negatives): recall >= 90% on positives, precision >= 95% on negatives. Run `pytest tests/test_classifier.py -v` to see current scores.
