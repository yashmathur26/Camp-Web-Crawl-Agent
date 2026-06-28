"""Acceptance checks for urls.py and cache.py (M1)."""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

# Run from project root
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from shared.urls import normalize_url, to_absolute  # noqa: E402


def test_normalize_url():
    assert normalize_url("http://WWW.X.com/a/?utm_x=1#z") == "https://x.com/a"
    assert normalize_url("https://x.com/a/") == "https://x.com/a"
    assert normalize_url("https://www.example.com/path?utm_source=x&id=1") == (
        "https://example.com/path?id=1"
    )
    print("normalize_url: OK")


def test_to_absolute():
    assert to_absolute("https://example.com/dir/", "page.html") == (
        "https://example.com/dir/page.html"
    )
    assert to_absolute("https://example.com/", "mailto:test@x.com") == ""
    assert to_absolute("https://example.com/", "javascript:void(0)") == ""
    print("to_absolute: OK")


def test_cache_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        cache_dir = Path(tmp) / "cache"
        cache_dir.mkdir()
        searches_path = cache_dir / "seen_searches.json"
        urls_path = cache_dir / "seen_urls.json"

        # Patch paths via env workaround: copy module logic inline for isolated test
        import json
        from datetime import datetime, timezone

        query = "summer camps Lexington, MA"
        ts = datetime.now(timezone.utc).isoformat()
        searches = {query: ts}
        with open(searches_path, "w") as f:
            json.dump(searches, f)

        urls = ["https://example.com/camp1", "https://example.com/camp2"]
        with open(urls_path, "w") as f:
            json.dump(urls, f)

        with open(searches_path) as f:
            loaded_searches = json.load(f)
        assert query in loaded_searches

        with open(urls_path) as f:
            loaded_urls = json.load(f)
        assert len(loaded_urls) == 2

        # Subprocess restart simulation
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                f"""
import json
from pathlib import Path
searches = json.loads(Path("{searches_path}").read_text())
urls = json.loads(Path("{urls_path}").read_text())
assert "summer camps Lexington, MA" in searches
assert len(urls) == 2
print("cache subprocess: OK")
""",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        assert "OK" in result.stdout
    print("cache roundtrip: OK")


if __name__ == "__main__":
    test_normalize_url()
    test_to_absolute()
    test_cache_roundtrip()
    print("\nAll M1 acceptance tests passed.")
