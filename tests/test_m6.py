"""Acceptance checks for store.py idempotency (M6)."""

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from shared.store import save_new_links, count_camp_links  # noqa: E402
from shared.cache import add_seen_urls, load_seen_urls  # noqa: E402


def test_store_idempotent():
    with tempfile.TemporaryDirectory() as tmp:
        csv_path = Path(tmp) / "camp_links.csv"
        cache_dir = Path(tmp) / "cache"
        cache_dir.mkdir()
        # Redirect cache by temporarily using project cache after clearing
        rows = [
            {
                "url": "https://example.com/summer-camp",
                "state": "MA",
                "town_hint": "Lexington",
                "source_type": "directory",
                "found_via": "A",
                "found_on_page": "https://example.com/programs",
                "link_text": "Summer Camp",
            }
        ]
        n1 = save_new_links(rows, path=str(csv_path))
        assert n1 == 1
        assert count_camp_links(str(csv_path)) == 1

        n2 = save_new_links(rows, path=str(csv_path))
        assert n2 == 0
        assert count_camp_links(str(csv_path)) == 1
        print("store idempotent: OK")


def test_filter_denylist():
    from phase_a.filter_links import is_likely_camp_link

    assert is_likely_camp_link("https://facebook.com/camp", "camp") is False
    assert is_likely_camp_link("mailto:x@y.com", "") is False
    assert is_likely_camp_link("https://example.com/summer-camp", "Register") is True
    assert is_likely_camp_link(
        "https://lexingtoncommunityed.org/class-category/cooking", "COOKING"
    ) is False
    assert is_likely_camp_link(
        "https://lexingtoncommunityed.org/class/lexplorations-2026", "READ MORE"
    ) is True
    assert is_likely_camp_link(
        "https://lexingtoncommunityed.org/class/decompress-your-stress-with-laughter-4",
        "READ MORE",
    ) is False
    print("filter: OK")


if __name__ == "__main__":
    test_store_idempotent()
    test_filter_denylist()
    print("\nAll M6 acceptance tests passed.")
