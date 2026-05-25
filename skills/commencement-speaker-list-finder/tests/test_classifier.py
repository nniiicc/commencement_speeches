"""Classifier against synthetic HTML fixtures."""
from __future__ import annotations

from pathlib import Path

from scripts.classify_page import classify

FIX = Path(__file__).parent / "fixtures"


def _read(name: str) -> bytes:
    return (FIX / name).read_bytes()


def test_table_year_speaker_role_classifies_as_list():
    result = classify(_read("table_year_speaker_role.html"), "text/html", "https://x/y")
    assert result.classification == "speaker_list"
    assert result.n_distinct_years >= 15
    assert result.confidence > 0.4


def test_table_year_speaker_classifies_as_list():
    result = classify(_read("table_year_speaker.html"), "text/html", "https://x/y")
    assert result.classification == "speaker_list"
    assert result.n_distinct_years >= 15


def test_paragraph_bold_year_classifies_as_list():
    result = classify(_read("paragraph_bold_year.html"), "text/html", "https://x/y")
    assert result.classification == "speaker_list"
    assert result.n_distinct_years >= 15


def test_press_release_rejected():
    result = classify(_read("not_a_list_press_release.html"), "text/html", "https://x/y")
    assert result.classification == "not_a_list"


def test_blog_post_rejected():
    result = classify(_read("not_a_list_blog_post.html"), "text/html", "https://x/y")
    assert result.classification == "not_a_list"
