"""Probe one institution for commencement-speaker-list pages.

Usage:
  python scripts/probe_institution.py \
    --name "University of Pennsylvania" \
    --homepage https://www.upenn.edu/ \
    [--ipeds-id 215062]

Prints one CSV row per confirmed speaker_list page (or one empty row if none).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import logging
import sys
from datetime import datetime
from urllib.parse import urlparse

if __package__ is None:
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.classify_page import classify
from scripts.detect_shape import detect_shape
from scripts.enumerate_urls import (
    candidate_urls,
    host_subdomain,
    publisher_for,
    registered_domain,
)
from scripts.fetch import try_fetch
from scripts.tavily_search import search_site_restricted

log = logging.getLogger(__name__)


CSV_COLUMNS = [
    "ipeds_id",
    "institution_name",
    "registered_domain",
    "list_url",
    "publisher",
    "host_subdomain",
    "coverage_year_min",
    "coverage_year_max",
    "n_years_listed",
    "parser_shape",
    "has_transcript_links",
    "has_role_column",
    "content_hash",
    "bytes_len",
    "fetched_at",
    "classifier_confidence",
    "notes",
]


def _empty_row(ipeds_id: int | None, name: str, domain: str | None, notes: str) -> dict:
    return {
        "ipeds_id": ipeds_id or "",
        "institution_name": name,
        "registered_domain": domain or "",
        "list_url": "",
        "publisher": "",
        "host_subdomain": "",
        "coverage_year_min": "",
        "coverage_year_max": "",
        "n_years_listed": "",
        "parser_shape": "",
        "has_transcript_links": "",
        "has_role_column": "",
        "content_hash": "",
        "bytes_len": "",
        "fetched_at": "",
        "classifier_confidence": "",
        "notes": notes,
    }


def _evaluate_url(url: str, name: str, ipeds_id: int | None, domain: str | None) -> dict | None:
    result = try_fetch(url)
    if result is None or result.status_code != 200:
        return None
    cls = classify(result.content, result.content_type, result.final_url)
    if cls.classification != "speaker_list":
        return None
    shape = detect_shape(result.content, result.content_type, result.final_url)
    return {
        "ipeds_id": ipeds_id or "",
        "institution_name": name,
        "registered_domain": domain or "",
        "list_url": result.final_url,
        "publisher": publisher_for(result.final_url),
        "host_subdomain": host_subdomain(result.final_url),
        "coverage_year_min": cls.year_min or "",
        "coverage_year_max": cls.year_max or "",
        "n_years_listed": cls.n_distinct_years,
        "parser_shape": shape.parser_shape,
        "has_transcript_links": shape.has_transcript_links,
        "has_role_column": shape.has_role_column,
        "content_hash": hashlib.sha256(result.content).hexdigest(),
        "bytes_len": len(result.content),
        "fetched_at": datetime.utcnow().isoformat() + "Z",
        "classifier_confidence": cls.confidence,
        "notes": f"{cls.notes}; {shape.notes}".strip("; "),
    }


def probe(name: str, homepage_url: str, ipeds_id: int | None = None) -> list[dict]:
    domain = registered_domain(homepage_url)
    if not domain:
        return [_empty_row(ipeds_id, name, None, "could_not_derive_domain")]

    seen_urls: set[str] = set()
    rows: list[dict] = []

    for url in candidate_urls(homepage_url, name):
        if url in seen_urls:
            continue
        seen_urls.add(url)
        row = _evaluate_url(url, name, ipeds_id, domain)
        if row is not None and row["list_url"] not in {r["list_url"] for r in rows}:
            rows.append(row)

    if not rows:
        for hit in search_site_restricted(domain, max_results=10):
            if hit.url in seen_urls:
                continue
            seen_urls.add(hit.url)
            row = _evaluate_url(hit.url, name, ipeds_id, domain)
            if row is not None and row["list_url"] not in {r["list_url"] for r in rows}:
                rows.append(row)

    if not rows:
        return [_empty_row(ipeds_id, name, domain, "no_candidates_passed_classifier")]
    return rows


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser()
    p.add_argument("--name", required=True)
    p.add_argument("--homepage", required=True)
    p.add_argument("--ipeds-id", type=int, default=None)
    args = p.parse_args()

    rows = probe(args.name, args.homepage, args.ipeds_id)
    writer = csv.DictWriter(sys.stdout, fieldnames=CSV_COLUMNS)
    writer.writeheader()
    for r in rows:
        writer.writerow(r)
    return 0


if __name__ == "__main__":
    sys.exit(main())
