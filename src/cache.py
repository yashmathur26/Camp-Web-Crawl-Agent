import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from src.urls import normalize_url

_CACHE_DIR = Path(os.environ.get("FIREFLY_CACHE_ROOT", "cache"))
_SEEN_SEARCHES_PATH = _CACHE_DIR / "seen_searches.json"
_SEEN_URLS_PATH = _CACHE_DIR / "seen_urls.json"


def _ensure_cache_dir() -> None:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _read_json(path: Path, default):
    if not path.exists():
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: Path, data) -> None:
    _ensure_cache_dir()
    # Atomic write (temp + replace): a crash or a concurrent writer (parallel
    # town pipelines share this cache) can never leave a half-written, unparseable
    # JSON file. os.replace is atomic on the same filesystem.
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def load_seen_searches() -> dict[str, str | dict]:
    return _read_json(_SEEN_SEARCHES_PATH, {})


def get_cached_search_results(query: str) -> list[dict] | None:
    """Return cached Serper rows for *query*, or None if not cached."""
    entry = load_seen_searches().get(query)
    if isinstance(entry, dict) and isinstance(entry.get("results"), list):
        return entry["results"]
    return None


def record_search(query: str, results: list[dict] | None = None) -> None:
    seen = load_seen_searches()
    if results is not None:
        seen[query] = {
            "at": datetime.now(timezone.utc).isoformat(),
            "results": results,
        }
    else:
        seen[query] = datetime.now(timezone.utc).isoformat()
    _write_json(_SEEN_SEARCHES_PATH, seen)


def is_search_seen(query: str) -> bool:
    return get_cached_search_results(query) is not None


def load_seen_urls() -> set[str]:
    raw = _read_json(_SEEN_URLS_PATH, [])
    return {normalize_url(u) for u in raw if u}


def add_seen_urls(urls: Iterable[str]) -> None:
    existing = _read_json(_SEEN_URLS_PATH, [])
    existing_set = {normalize_url(u) for u in existing if u}
    for url in urls:
        normalized = normalize_url(url)
        if normalized:
            existing_set.add(normalized)
    _write_json(_SEEN_URLS_PATH, sorted(existing_set))
