"""Integration test for cache.py persistence across subprocess restart."""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.cache import (  # noqa: E402
    add_seen_urls,
    get_cached_search_results,
    is_search_seen,
    load_seen_urls,
    record_search,
)


def test_cache_integration():
    cache_dir = ROOT / "cache"
    searches_file = cache_dir / "seen_searches.json"
    urls_file = cache_dir / "seen_urls.json"

    # Clean slate for test
    for f in (searches_file, urls_file):
        if f.exists():
            f.unlink()

    sample_results = [{"url": "https://test.example/camp", "title": "Camp", "snippet": ""}]
    record_search("test query integration", sample_results)
    add_seen_urls(["https://test.example/camp"])

    assert is_search_seen("test query integration")
    assert get_cached_search_results("test query integration") == sample_results
    assert "https://test.example/camp" in load_seen_urls()

    result = subprocess.run(
        [sys.executable, "-c", f"""
import sys
sys.path.insert(0, "{ROOT}")
from src.cache import is_search_seen, load_seen_urls
assert is_search_seen("test query integration")
assert "https://test.example/camp" in load_seen_urls()
print("OK")
"""],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        check=True,
    )
    assert "OK" in result.stdout
    print("cache integration: OK")


if __name__ == "__main__":
    test_cache_integration()
    print("\nCache integration test passed.")
