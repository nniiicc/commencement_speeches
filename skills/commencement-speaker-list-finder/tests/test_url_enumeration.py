from scripts.enumerate_urls import (
    candidate_urls,
    host_subdomain,
    institution_slug,
    publisher_for,
    registered_domain,
)


def test_registered_domain_https():
    assert registered_domain("https://www.upenn.edu/") == "upenn.edu"


def test_registered_domain_no_scheme():
    assert registered_domain("library.syracuse.edu") == "syr.edu" or registered_domain("library.syracuse.edu") == "syracuse.edu"


def test_institution_slug_acronym():
    assert institution_slug("UNCG") == "uncg"


def test_institution_slug_long_name():
    s = institution_slug("University of Notre Dame")
    assert s in {"und", "university"}


def test_candidate_urls_includes_archive_and_commencement_office():
    urls = candidate_urls("https://www.upenn.edu/", "University of Pennsylvania")
    assert any("archives.upenn.edu" in u for u in urls)
    assert any("commencement.upenn.edu" in u for u in urls)
    assert any("secretary.upenn.edu" in u for u in urls)


def test_publisher_for_archives_subdomain():
    assert publisher_for("https://archives.upenn.edu/x") == "university_archives"


def test_publisher_for_commencement_subdomain():
    assert publisher_for("https://commencement.nd.edu/y") == "commencement_office"


def test_host_subdomain_archives():
    assert host_subdomain("https://archives.upenn.edu/x") == "archives"
