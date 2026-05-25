from pathlib import Path

from scripts.detect_shape import detect_shape

FIX = Path(__file__).parent / "fixtures"


def _read(name: str) -> bytes:
    return (FIX / name).read_bytes()


def test_detects_per_year_subpage_when_table_links_to_year_urls():
    result = detect_shape(_read("table_year_speaker_role.html"), "text/html", "https://x/y")
    assert result.parser_shape == "per_year_subpage_index"
    assert result.has_transcript_links is True


def test_detects_table_year_speaker_two_cols():
    result = detect_shape(_read("table_year_speaker.html"), "text/html", "https://x/y")
    assert result.parser_shape == "table_year_speaker"
    assert result.has_role_column is False


def test_detects_paragraph_bold_year():
    result = detect_shape(_read("paragraph_bold_year.html"), "text/html", "https://x/y")
    assert result.parser_shape == "paragraph_bold_year"


def test_detects_pdf_shape_for_pdf_url():
    result = detect_shape(b"%PDF-1.4 stub", "application/pdf", "https://x/y.pdf")
    assert result.parser_shape == "pdf_year_rows"
