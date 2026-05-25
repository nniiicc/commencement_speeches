"""Domain -> candidate URL list. See reference/url_patterns.md."""
from __future__ import annotations

import re
from urllib.parse import urlparse

import tldextract


def registered_domain(homepage_url: str) -> str | None:
    if not homepage_url:
        return None
    if not homepage_url.startswith(("http://", "https://")):
        homepage_url = "https://" + homepage_url
    ext = tldextract.extract(homepage_url)
    if ext.domain and ext.suffix:
        return f"{ext.domain}.{ext.suffix}".lower()
    return None


def institution_slug(name: str) -> str:
    """Crude slug for {slug}-style URLs (e.g., UNCG -> 'uncg').
    Picks the first acronym-shaped token or the first lowercase word."""
    if not name:
        return ""
    acronym = "".join(c for c in name if c.isupper())
    if 2 <= len(acronym) <= 6:
        return acronym.lower()
    token = re.split(r"\W+", name.lower())[0]
    return token or name.lower().replace(" ", "")


PATTERNS = [
    "https://archives.{domain}/digitized-resources/docs-pubs/commencement-addresses/",
    "https://archives.{domain}/digitized-resources/docs-pubs/commencement-speakers/",
    "https://archives.{domain}/research/facts/commencement.htm",
    "https://archives.{domain}/commencement/",
    "https://library.{domain}/special-collections-research-center/university-archives/founding-history/commencement-speakers/",
    "https://library.{domain}/about-us/library-departments/special-collections-university-archives/university-archives/lists-{slug}-history/commencement-speakers/",
    "https://commencement.{domain}/archives/speaker/",
    "https://commencement.{domain}/archives/speakers/",
    "https://commencement.{domain}/ceremonies/speaker-and-honorary-degrees/",
    "https://commencement.{domain}/archives/",
    "https://secretary.{domain}/ceremonies/commencement-speakers",
    "https://www.{domain}/academic/provost/commencement/archives/",
]


def candidate_urls(homepage_url: str, name: str) -> list[str]:
    domain = registered_domain(homepage_url)
    if not domain:
        return []
    slug = institution_slug(name)
    out: list[str] = []
    for p in PATTERNS:
        out.append(p.format(domain=domain, slug=slug))
    return out


def publisher_for(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if host.startswith("archives."):
        return "university_archives"
    if host.startswith("library."):
        return "library_archive"
    if host.startswith("commencement."):
        return "commencement_office"
    if host.startswith("secretary."):
        return "secretary_office"
    if host.startswith("trustees."):
        return "trustees_office"
    if "/provost/" in url.lower():
        return "provost_office"
    return "other"


def host_subdomain(url: str) -> str:
    host = urlparse(url).netloc.lower()
    parts = host.split(".")
    if len(parts) >= 3:
        return parts[0]
    return ""
