# URL patterns for commencement speaker archives

The probe enumerates these patterns under each institution's registered domain. First 2xx response that passes the classifier wins, but the enumerator keeps probing afterwards so duplicates published in multiple places (e.g., Penn's archive copy + secretary's office copy) both make it into the catalog.

The {domain} placeholder is the registered domain via `tldextract` (e.g., `upenn.edu`, `nd.edu`, `syr.edu`). The {slug} placeholder is the short form of the institution name (e.g., `uncg`).

## Family A — Library / archives

```
https://archives.{domain}/digitized-resources/docs-pubs/commencement-addresses/
https://archives.{domain}/digitized-resources/docs-pubs/commencement-speakers/
https://archives.{domain}/research/facts/commencement.htm
https://archives.{domain}/commencement/
https://library.{domain}/special-collections-research-center/university-archives/founding-history/commencement-speakers/
https://library.{domain}/about-us/library-departments/special-collections-university-archives/university-archives/lists-{slug}-history/commencement-speakers/
```

Real examples:
- `archives.upenn.edu/digitized-resources/docs-pubs/commencement-addresses/`
- `archives.nd.edu/research/facts/commencement.htm`
- `library.syracuse.edu/special-collections-research-center/university-archives/founding-history/commencement-speakers/`
- `library.uncg.edu/about-us/library-departments/special-collections-university-archives/university-archives/lists-uncg-history/commencement-speakers/`

## Family B — Commencement / events office

```
https://commencement.{domain}/archives/speaker/
https://commencement.{domain}/archives/speakers/
https://commencement.{domain}/ceremonies/speaker-and-honorary-degrees/
https://commencement.{domain}/archives/
```

Real examples:
- `commencement.ncsu.edu/archives/speaker/`
- `commencement.nd.edu/archives/speakers/`
- `commencement.upenn.edu/ceremonies/speaker-and-honorary-degrees/`

## Family C — Secretary / trustees / provost

```
https://secretary.{domain}/ceremonies/commencement-speakers
https://www.{domain}/academic/provost/commencement/archives/
https://trustees.{domain}/  # listed but Tufts-style PDFs hit via search
```

Real examples:
- `secretary.upenn.edu/ceremonies/commencement-speakers`
- `auburn.edu/academic/provost/commencement/archives/`
- `trustees.tufts.edu/wp-content/uploads/2023-05-22_Commencement_Speakers-1.pdf` (found via search, not enumeration)

## Family D — Site-restricted search fallback

If `TAVILY_API_KEY` is set and zero candidates classify, fall back to Tavily with:

```
include_domains=["{domain}"]
query='"commencement speakers" OR "commencement addresses" list history archive'
max_results=10
```

Re-classify the top 10 results.

## Redirect handling

Some schools redirect across hosts (e.g., `udel.edu` -> `sites.udel.edu/uarm/...`). After enumeration, if any 30x redirect resolves to a host on a different registered domain than the input, the enumerator re-derives the domain from the final URL and runs Family A/B/C/D once more against that new domain.

## What this list intentionally does NOT include

- `news.{domain}` — covered by the live discovery pipeline for current-year press releases.
- `youtube.com/{channel}` — videos, out of scope for this skill.
- `c-span.org` — out of scope.
- Wikipedia, NPR, GraduationWisdom, BestColleges — curated third-party collections, not institutional rosters.
