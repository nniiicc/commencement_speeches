"""Heuristic classifier: is this page a comprehensive commencement speaker list?

Four rules, no LLM. See SKILL.md and reference/page_shapes.md.
"""
from __future__ import annotations

import datetime as dt
import io
import re
from dataclasses import dataclass

from bs4 import BeautifulSoup

YEAR_RE = re.compile(r"\b(1[89]\d{2}|20\d{2})\b")
KEYWORDS = ("commencement", "address", "speaker", "honorary", "convocation")
MIN_DISTINCT_YEARS = 15
MIN_REGULAR_FRACTION = 0.70
MIN_KEYWORD_NEIGHBORHOOD = 3
KEYWORD_WINDOW_CHARS = 200


@dataclass
class ClassifyResult:
    classification: str
    confidence: float
    n_distinct_years: int
    year_min: int | None
    year_max: int | None
    is_pdf: bool
    notes: str


def _years_in_range(text: str, year_min: int = 1840, year_max: int | None = None) -> list[int]:
    if year_max is None:
        year_max = dt.date.today().year
    out: list[int] = []
    for m in YEAR_RE.finditer(text):
        y = int(m.group(0))
        if year_min <= y <= year_max:
            out.append(y)
    return out


def _years_in_keyword_neighborhood(text: str, year_positions: list[int]) -> int:
    """Count distinct year positions where any keyword appears within +/- WINDOW chars."""
    text_lower = text.lower()
    count = 0
    for pos in year_positions:
        start = max(0, pos - KEYWORD_WINDOW_CHARS)
        end = min(len(text_lower), pos + KEYWORD_WINDOW_CHARS)
        window = text_lower[start:end]
        if any(kw in window for kw in KEYWORDS):
            count += 1
    return count


def _is_mostly_monotonic(years: list[int]) -> bool:
    if len(years) < 2:
        return True
    asc_pairs = sum(1 for a, b in zip(years, years[1:]) if a <= b)
    desc_pairs = sum(1 for a, b in zip(years, years[1:]) if a >= b)
    total = len(years) - 1
    return max(asc_pairs, desc_pairs) / total >= 0.70


def _years_structurally_regular(soup: BeautifulSoup, year_count: int) -> int:
    """Years that appear as the leading cell of a table row OR as a bold/strong
    leading element of a paragraph/list item count as 'structurally regular'."""
    regular = 0
    for table in soup.find_all("table"):
        for row in table.find_all("tr"):
            cells = row.find_all(["td", "th"])
            if not cells:
                continue
            first = cells[0].get_text(strip=True)
            if YEAR_RE.fullmatch(first):
                regular += 1
    for tag in soup.find_all(["strong", "b"]):
        txt = tag.get_text(strip=True)
        if YEAR_RE.fullmatch(txt):
            parent = tag.parent
            if parent is not None and parent.name in ("p", "li", "div"):
                children = [c for c in parent.children if getattr(c, "name", None) or (isinstance(c, str) and c.strip())]
                if children and children[0] is tag:
                    regular += 1
    return min(regular, year_count)


def _classify_html(content: bytes, url: str) -> ClassifyResult:
    try:
        text_decoded = content.decode("utf-8", errors="ignore")
    except Exception:
        text_decoded = ""
    soup = BeautifulSoup(text_decoded, "lxml")
    visible_text = soup.get_text(separator=" ", strip=False)

    year_positions = [m.start() for m in YEAR_RE.finditer(visible_text)]
    years_in_visible = _years_in_range(visible_text)
    distinct = sorted(set(years_in_visible))
    n_distinct = len(distinct)

    if n_distinct < MIN_DISTINCT_YEARS:
        return ClassifyResult(
            classification="not_a_list",
            confidence=0.0,
            n_distinct_years=n_distinct,
            year_min=distinct[0] if distinct else None,
            year_max=distinct[-1] if distinct else None,
            is_pdf=False,
            notes=f"only {n_distinct} distinct years (need {MIN_DISTINCT_YEARS})",
        )

    regular = _years_structurally_regular(soup, len(years_in_visible))
    regular_fraction = regular / len(years_in_visible) if years_in_visible else 0.0

    if regular_fraction < MIN_REGULAR_FRACTION:
        return ClassifyResult(
            classification="not_a_list",
            confidence=regular_fraction,
            n_distinct_years=n_distinct,
            year_min=distinct[0],
            year_max=distinct[-1],
            is_pdf=False,
            notes=f"only {regular_fraction:.0%} of years are in structurally regular positions",
        )

    kw_neighborhood = _years_in_keyword_neighborhood(visible_text, year_positions)
    if kw_neighborhood < MIN_KEYWORD_NEIGHBORHOOD:
        return ClassifyResult(
            classification="not_a_list",
            confidence=0.2,
            n_distinct_years=n_distinct,
            year_min=distinct[0],
            year_max=distinct[-1],
            is_pdf=False,
            notes="too few years next to commencement keywords",
        )

    if not _is_mostly_monotonic(years_in_visible):
        return ClassifyResult(
            classification="not_a_list",
            confidence=0.3,
            n_distinct_years=n_distinct,
            year_min=distinct[0],
            year_max=distinct[-1],
            is_pdf=False,
            notes="years are not monotonic (looks like an unrelated date scatter)",
        )

    confidence = min(1.0, regular_fraction)
    return ClassifyResult(
        classification="speaker_list",
        confidence=round(confidence, 3),
        n_distinct_years=n_distinct,
        year_min=distinct[0],
        year_max=distinct[-1],
        is_pdf=False,
        notes="ok",
    )


def _classify_pdf(content: bytes, url: str) -> ClassifyResult:
    try:
        import pdfplumber
    except ImportError:
        return ClassifyResult(
            classification="not_a_list",
            confidence=0.0,
            n_distinct_years=0,
            year_min=None,
            year_max=None,
            is_pdf=True,
            notes="pdfplumber not installed",
        )

    text_lines: list[str] = []
    try:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            for page in pdf.pages:
                t = page.extract_text() or ""
                text_lines.extend(t.splitlines())
    except Exception as e:
        return ClassifyResult(
            classification="not_a_list",
            confidence=0.0,
            n_distinct_years=0,
            year_min=None,
            year_max=None,
            is_pdf=True,
            notes=f"pdfplumber failed: {e}",
        )

    full_text = "\n".join(text_lines)
    years = _years_in_range(full_text)
    distinct = sorted(set(years))
    n_distinct = len(distinct)
    year_prefixed = sum(1 for ln in text_lines if re.match(r"^\s*\d{4}\b", ln))

    if n_distinct < MIN_DISTINCT_YEARS:
        return ClassifyResult(
            "not_a_list", 0.0, n_distinct,
            distinct[0] if distinct else None, distinct[-1] if distinct else None,
            True, f"only {n_distinct} distinct years in PDF",
        )
    if year_prefixed < MIN_DISTINCT_YEARS:
        return ClassifyResult(
            "not_a_list", 0.2, n_distinct, distinct[0], distinct[-1],
            True, f"only {year_prefixed} lines begin with a year",
        )
    text_lower = full_text.lower()
    if not any(kw in text_lower for kw in KEYWORDS):
        return ClassifyResult(
            "not_a_list", 0.2, n_distinct, distinct[0], distinct[-1],
            True, "no commencement keywords in PDF body",
        )
    confidence = min(1.0, year_prefixed / max(1, len(text_lines)) + 0.5)
    return ClassifyResult(
        "speaker_list", round(confidence, 3), n_distinct,
        distinct[0], distinct[-1], True, "ok (pdf)",
    )


def classify(content: bytes, content_type: str, url: str) -> ClassifyResult:
    if "pdf" in content_type.lower() or url.lower().endswith(".pdf"):
        return _classify_pdf(content, url)
    return _classify_html(content, url)
