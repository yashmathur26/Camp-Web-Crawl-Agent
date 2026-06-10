"""Tests for platform registry detection."""

from config.platforms_registry import PLATFORM_SIGNATURES, host_signatures


def test_registry_has_community_ed():
    assert "community_ed" in PLATFORM_SIGNATURES


def test_host_signatures_includes_myrec():
    platforms = [p for p, _ in host_signatures()]
    assert "myrec" in platforms


def test_host_signatures_includes_recdesk():
    platforms = [p for p, _ in host_signatures()]
    assert "recdesk" in platforms
