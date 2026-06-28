"""Tests for WooCommerce product URL validation."""

from phase_b.platforms import _is_valid_woo_product


def test_program_teens_rejected():
    assert not _is_valid_woo_product("https://example.org/program/teens")


def test_program_summer_camp_accepted():
    assert _is_valid_woo_product("https://example.org/program/summer-art-camp")
