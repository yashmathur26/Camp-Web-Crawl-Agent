"""Tests for community ed adapter scoping."""

from src.platforms import _is_valid_woo_product, detect_platform


def test_bostonjcc_teens_hub_rejected():
    assert not _is_valid_woo_product("https://bostonjcc.org/program/teens", "Teens")


def test_lexplorations_class_accepted():
    url = "https://lexingtoncommunityed.org/lexplorations/class/summer-art-camp"
    assert _is_valid_woo_product(url, "Summer Art Camp")


def test_community_ed_host_detection():
    links = [{"url": "https://lexingtoncommunityed.org/lexplorations/find-a-class", "text": ""}]
    assert detect_platform(
        "https://lexingtoncommunityed.org/lexplorations/find-a-class",
        links,
        "lexplorations summer",
    ) == "community_ed"
