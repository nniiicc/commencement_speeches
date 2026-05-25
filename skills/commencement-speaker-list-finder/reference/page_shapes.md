# Parser shapes

The detector labels each confirmed `speaker_list` page with one of five shapes so a downstream extractor can dispatch without re-classifying. The skill itself does not parse rows.

## `table_year_speaker_role`

A single `<table>` with a year column and at least two sibling columns (speaker, role/affiliation, optionally speech title). The dominant shape for institutional archives.

Detection rule:
1. Page contains exactly one large `<table>` whose first cell column is mostly four-digit years.
2. That table has >= 3 columns total.

Example: UPenn `archives.upenn.edu/digitized-resources/docs-pubs/commencement-addresses/` — columns: `Year | Month | Speaker | Title`.

If row cells contain `<a href>` deep-linked to a per-year subpage whose URL contains the year (e.g., `.../address-1899`, `.../address-1900`), additionally set `has_transcript_links=True` and override the shape to `per_year_subpage_index`.

## `table_year_speaker`

Same as above but with exactly two columns (year + speaker name only, no role column).

Example: Notre Dame `commencement.nd.edu/archives/speakers/` — columns: `Year | Speaker`.

## `paragraph_bold_year`

The list is a sequence of `<p>` or `<li>` items, each prefixed with a bold or strong four-digit year. Common in older library pages.

Detection rule:
1. >= 15 `<strong>` or `<b>` elements whose text is a four-digit year in [1840, current_year].
2. Each such element is the leading child of a paragraph or list item.

Example: Syracuse `library.syracuse.edu/.../commencement-speakers/` — every entry starts with `<strong>1957</strong> — John F. Kennedy - U.S. Senator from Massachusetts`.

## `pdf_year_rows`

A PDF whose extracted lines start with a four-digit year, followed by speaker and (sometimes) role.

Detection rule:
1. Content-Type is `application/pdf` OR URL ends in `.pdf`.
2. After pdfplumber text extraction, >= 15 lines match `^\s*\d{4}\b`.

Examples:
- Tufts `trustees.tufts.edu/wp-content/uploads/2023-05-22_Commencement_Speakers-1.pdf`
- UNH `www.unh.edu/.../commencement-speaker-historical-list.pdf`

## `per_year_subpage_index`

The page is an index of links to per-year subpages where the actual speech text lives. The index itself is the catalog row; per-year subpages are recorded separately by the downstream extractor (which would set `has_transcript_links=True`).

Detection rule: any of the above shapes, plus the year cells / items contain `<a href>` to URLs that themselves contain the year.

Example: UPenn — the master `commencement-addresses/` table links each year to `.../address-1899`, `.../address-1900`, ... where the full text lives.

## `unknown`

Classifier says yes (>=15 years in commencement-keyword context, mostly monotonic), but no shape rule fires. These land in the catalog with `parser_shape='unknown'` and a human eyeballs them for triage. Examples in the wild: Auburn `auburn.edu/academic/provost/commencement/archives/` (a page listing per-ceremony program PDFs rather than a single roster), Suffolk's `dc.suffolk.edu/comm/` (Bepress repository index).

## Why shape detection lives in this skill, not downstream

Re-classifying a 100KB HTML page costs nothing the first time but a lot when a downstream parser has to re-run it for thousands of institutions. Recording the shape at discovery time turns the parser into a simple dispatcher.
