# Output CSV schema (`speaker_lists_catalog.csv`)

One row per confirmed `speaker_list` page. Multiple rows per institution are allowed.

| Column | Type | Notes |
|---|---|---|
| `ipeds_id` | int / nullable | Pass-through from input if supplied |
| `institution_name` | string | Pass-through from input |
| `registered_domain` | string | e.g., `upenn.edu`, derived via `tldextract` |
| `list_url` | string | Final canonical URL of the speaker-list page (after redirects) |
| `publisher` | enum | `library_archive`, `university_archives`, `commencement_office`, `secretary_office`, `trustees_office`, `provost_office`, `other` |
| `host_subdomain` | string | e.g., `archives`, `library`, `commencement`, `secretary` |
| `coverage_year_min` | int | Earliest year detected on the page |
| `coverage_year_max` | int | Latest year detected on the page |
| `n_years_listed` | int | Distinct years detected; rough completeness proxy |
| `parser_shape` | enum | `table_year_speaker`, `table_year_speaker_role`, `paragraph_bold_year`, `pdf_year_rows`, `per_year_subpage_index`, `unknown` |
| `has_transcript_links` | bool | True if list rows deep-link to per-year speech text |
| `has_role_column` | bool | True if speaker role/affiliation column is present |
| `content_hash` | string | sha256 of fetched bytes; lets a re-run detect page changes |
| `bytes_len` | int | |
| `fetched_at` | ISO 8601 string | UTC |
| `classifier_confidence` | float in [0, 1] | |
| `notes` | string | Free-text triage notes |

## Publisher inference

| Host subdomain | publisher |
|---|---|
| `archives.{domain}` | `university_archives` |
| `library.{domain}` | `library_archive` |
| `commencement.{domain}` | `commencement_office` |
| `secretary.{domain}` | `secretary_office` |
| `trustees.{domain}` | `trustees_office` |
| `{domain}/.../provost/...` | `provost_office` |
| anything else | `other` |

## Empty / negative rows

Institutions where zero candidates classified as `speaker_list` get a single row with empty `list_url` and `notes='no_candidates_passed_classifier'`. This makes the catalog joinable back to the input list without losing track of attempted-but-empty institutions.
