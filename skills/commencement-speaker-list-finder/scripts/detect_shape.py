"""Parser-shape dispatcher for confirmed speaker_list pages."""
from __future__ import annotations

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup

YEAR_RE = re.compile(r"\b(1[89]\d{2}|20\d{2})\b")


@dataclass
class ShapeResult:
    parser_shape: str
    has_transcript_links: bool
    has_role_column: bool
    notes: str


def detect_pdf_shape() -> ShapeResult:
    return ShapeResult(
        parser_shape="pdf_year_rows",
        has_transcript_links=False,
        has_role_column=False,
        notes="PDF",
    )


def _table_year_column(table) -> tuple[int | None, int]:
    """Return (year_column_index, n_columns) for the dominant year column, or (None, 0)."""
    rows = table.find_all("tr")
    if not rows:
        return None, 0
    col_year_count: dict[int, int] = {}
    n_cols_total = 0
    for row in rows:
        cells = row.find_all(["td", "th"])
        if not cells:
            continue
        n_cols_total = max(n_cols_total, len(cells))
        for idx, c in enumerate(cells):
            if YEAR_RE.fullmatch(c.get_text(strip=True)):
                col_year_count[idx] = col_year_count.get(idx, 0) + 1
    if not col_year_count:
        return None, n_cols_total
    best_col = max(col_year_count, key=col_year_count.get)
    return best_col, n_cols_total


def _table_has_per_year_subpage_links(table, year_col: int) -> bool:
    rows = table.find_all("tr")
    hits = 0
    for row in rows:
        cells = row.find_all(["td", "th"])
        if len(cells) <= year_col:
            continue
        year_cell = cells[year_col]
        year_text = year_cell.get_text(strip=True)
        if not YEAR_RE.fullmatch(year_text):
            continue
        for sibling in cells:
            for a in sibling.find_all("a", href=True):
                if year_text in a["href"]:
                    hits += 1
                    break
    return hits >= 5


def detect_html_shape(content: bytes) -> ShapeResult:
    soup = BeautifulSoup(content.decode("utf-8", errors="ignore"), "lxml")

    # Try table shapes first
    best_table = None
    best_table_count = 0
    best_col = None
    best_ncols = 0
    for tbl in soup.find_all("table"):
        col, ncols = _table_year_column(tbl)
        if col is None:
            continue
        rows = tbl.find_all("tr")
        ycount = sum(
            1 for r in rows
            for cells in [r.find_all(["td", "th"])]
            if len(cells) > col and YEAR_RE.fullmatch(cells[col].get_text(strip=True))
        )
        if ycount > best_table_count:
            best_table_count = ycount
            best_table = tbl
            best_col = col
            best_ncols = ncols

    if best_table is not None and best_table_count >= 10:
        per_year = _table_has_per_year_subpage_links(best_table, best_col)
        if per_year:
            return ShapeResult(
                parser_shape="per_year_subpage_index",
                has_transcript_links=True,
                has_role_column=best_ncols >= 3,
                notes=f"table with {best_table_count} year rows, per-year subpage hrefs detected",
            )
        if best_ncols >= 3:
            return ShapeResult(
                parser_shape="table_year_speaker_role",
                has_transcript_links=False,
                has_role_column=True,
                notes=f"table {best_ncols} cols x {best_table_count} year rows",
            )
        return ShapeResult(
            parser_shape="table_year_speaker",
            has_transcript_links=False,
            has_role_column=False,
            notes=f"table 2 cols x {best_table_count} year rows",
        )

    # Paragraph-with-bold-year shape
    bold_year_count = 0
    for tag in soup.find_all(["strong", "b"]):
        if YEAR_RE.fullmatch(tag.get_text(strip=True)):
            parent = tag.parent
            if parent and parent.name in ("p", "li", "div"):
                bold_year_count += 1
    if bold_year_count >= 15:
        return ShapeResult(
            parser_shape="paragraph_bold_year",
            has_transcript_links=False,
            has_role_column=False,
            notes=f"{bold_year_count} <strong>YYYY</strong> entries",
        )

    return ShapeResult(
        parser_shape="unknown",
        has_transcript_links=False,
        has_role_column=False,
        notes="no shape rule fired; manual triage",
    )


def detect_shape(content: bytes, content_type: str, url: str) -> ShapeResult:
    if "pdf" in content_type.lower() or url.lower().endswith(".pdf"):
        return detect_pdf_shape()
    return detect_html_shape(content)
