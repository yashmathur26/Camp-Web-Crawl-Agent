"""Tests for YMCA WebTrac discovery helpers."""

import re

from src.platforms import _EMBED_PLATFORM_RE, _YMCA_HOST_RE


def test_ymca_host_match():
    assert _YMCA_HOST_RE.search("ymcaboston.org")
    assert _YMCA_HOST_RE.search("wsymca.org")


def test_embedded_webtrac_in_html():
    html = 'Register at https://majwhaydenweb.myvscloud.com/webtrac/web/search.html?type=CAMP'
    assert _EMBED_PLATFORM_RE.search(html)
