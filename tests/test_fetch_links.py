"""Link-selection tests for SerpAPI Google Jobs results.

Uses realistic payload shapes from SerpAPI's own docs (share_link with
htidocid, base64 job_id blob, apply_options). No network.
"""
import pytest

from fetch_jobs import get_job_link, _is_job_specific_link

SHARE = (
    "https://www.google.com/search?ibp=htl;jobs&q=barista"
    "&htidocid=02AYwjDxI9sGg4UEAAAAAA%3D%3D&hl=en-US"
    "#fpstate=tldetail&htivrt=jobs&htiq=barista"
    "&htidocid=02AYwjDxI9sGg4UEAAAAAA%3D%3D"
)
ATS = "https://careers.oatly.com/jobs/4553887-nyc?utm_source=google_jobs_apply"
BLOB = (
    "eyJqb2JfdGl0bGUiOiJCYXJpc3RhIE1hcmtldCBEZXZlbG9wZXIgTGVhZCAtIE5ZQyIs"
    "ImNvbXBhbnlfbmFtZSI6Ik9hdGx5IEFCIiwiaHRpZG9jaWQiOiIwMkFZd2pEeEk5c0dnNF"
    "VRUFBQUFBQT09In0="
)


def test_apply_link_preferred():
    job = {"apply_options": [{"title": "Oatly", "link": ATS}], "share_link": SHARE, "job_id": BLOB}
    assert get_job_link(job) == ATS


def test_share_link_used_when_no_apply_or_related():
    job = {"title": "Barista", "company_name": "Oatly", "share_link": SHARE, "job_id": BLOB}
    assert get_job_link(job) == SHARE


def test_related_link_used_when_no_apply_or_share():
    job = {"title": "Barista", "company_name": "Oatly", "related_links": [{"link": ATS}], "job_id": BLOB}
    assert get_job_link(job) == ATS


def test_generic_search_fallback_identifies_nothing_but_never_emits_blob():
    job = {"title": "Barista", "company_name": "Oatly", "job_id": BLOB}
    link = get_job_link(job)
    assert BLOB not in link
    assert "eyJ" not in link
    assert link.startswith("https://www.google.com/search?q=")
    assert not _is_job_specific_link(link)


def test_job_specific_link_classifier():
    assert _is_job_specific_link(ATS)
    assert _is_job_specific_link(SHARE)
    assert not _is_job_specific_link("https://www.google.com/search?q=x&ibp=htl;jobs")
    assert not _is_job_specific_link("")
    assert not _is_job_specific_link(None)
