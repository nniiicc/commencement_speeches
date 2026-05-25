from commencement.common.normalize import (
    domain_matches,
    normalize_name,
    registered_domain,
    state_to_region,
)


def test_state_to_region():
    assert state_to_region("NY") == "Northeast"
    assert state_to_region("ca") == "West"
    assert state_to_region("TX") == "South"
    assert state_to_region("IL") == "Midwest"
    assert state_to_region(None) is None
    assert state_to_region("XX") is None


def test_normalize_name():
    assert normalize_name("Dr. Jane O'Neill, Jr.") == "dr jane o neill jr"
    assert normalize_name("  multiple   spaces  ") == "multiple spaces"


def test_registered_domain():
    assert registered_domain("https://news.harvard.edu/foo") == "harvard.edu"
    assert registered_domain("http://www.mit.edu/path") == "mit.edu"
    assert registered_domain("") is None


def test_domain_matches():
    assert domain_matches("https://news.harvard.edu/a", "https://harvard.edu/b")
    assert not domain_matches("https://harvard.edu", "https://yale.edu")
