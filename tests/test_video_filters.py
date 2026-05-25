import datetime as dt

from commencement.config import CONFIG
from commencement.discovery.step3_video_link import (
    _looks_like_full_ceremony,
    _within_date_window,
)


def test_full_ceremony_long_with_keyword():
    entry = {"title": "2026 Commencement Ceremony", "duration": 4500}
    assert _looks_like_full_ceremony(entry) is True


def test_full_ceremony_short_clip():
    entry = {"title": "commencement highlights", "duration": 90}
    assert _looks_like_full_ceremony(entry) is False


def test_full_ceremony_uncertain():
    entry = {"title": "commencement speaker", "duration": 1200}
    assert _looks_like_full_ceremony(entry) is None


def test_within_date_window_close():
    cer = dt.datetime(2026, 5, 15)
    pub = dt.datetime(2026, 5, 20)
    assert _within_date_window(pub, cer) is True


def test_within_date_window_far():
    cer = dt.datetime(2026, 5, 15)
    pub = dt.datetime(2026, 8, 1)
    assert _within_date_window(pub, cer) is False


def test_within_date_window_no_published():
    cer = dt.datetime(2026, 5, 15)
    assert _within_date_window(None, cer) is True
