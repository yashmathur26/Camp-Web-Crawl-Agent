"""Tests for networkidle fetch selection."""

from phase_b.crawl import fetch_wait_until


def test_register_kind_uses_networkidle():
    assert fetch_wait_until("https://example.com/camp", kind="register") == "networkidle"
    assert fetch_wait_until("https://example.com/camp", kind="portal") == "networkidle"


def test_myvscloud_host_uses_networkidle():
    url = "https://majwhaydenweb.myvscloud.com/webtrac/web/iteminfo.html?FMID=1"
    assert fetch_wait_until(url) == "networkidle"


def test_generic_host_uses_domcontentloaded():
    assert fetch_wait_until("https://summersedgedaycamp.com/camps") == "domcontentloaded"
