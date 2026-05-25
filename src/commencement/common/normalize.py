"""String/URL normalization helpers shared across the pipeline."""
from __future__ import annotations

import re
from urllib.parse import urlparse

import tldextract


_STATE_TO_REGION = {
    **{s: "Northeast" for s in ("ME", "NH", "VT", "MA", "RI", "CT", "NY", "NJ", "PA")},
    **{s: "Midwest" for s in ("OH", "IN", "IL", "MI", "WI", "MN", "IA", "MO", "ND", "SD", "NE", "KS")},
    **{
        s: "South"
        for s in (
            "DE", "MD", "DC", "VA", "WV", "NC", "SC", "GA", "FL", "KY", "TN",
            "AL", "MS", "AR", "LA", "OK", "TX",
        )
    },
    **{
        s: "West"
        for s in (
            "MT", "ID", "WY", "CO", "NM", "AZ", "UT", "NV", "CA", "OR",
            "WA", "AK", "HI",
        )
    },
}


def state_to_region(state: str | None) -> str | None:
    if not state:
        return None
    return _STATE_TO_REGION.get(state.upper())


def normalize_name(name: str) -> str:
    s = name.lower().strip()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def registered_domain(url: str) -> str | None:
    if not url:
        return None
    try:
        ext = tldextract.extract(url)
        if ext.domain and ext.suffix:
            return f"{ext.domain}.{ext.suffix}".lower()
    except Exception:
        return None
    return None


def domain_matches(a: str, b: str) -> bool:
    da, db = registered_domain(a), registered_domain(b)
    return bool(da and db and da == db)


def url_netloc(url: str) -> str:
    return urlparse(url).netloc.lower()
