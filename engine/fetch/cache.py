"""Fetch cache (task 2.1, R5.3): normalize_url-keyed, memory + sqlite.

The same URL is fetched at most once per run regardless of which provider
reached it — lexingtonma.gov re-fetching the LexRec catalog cost the old
pipeline duplicate minutes per town. Disk persistence (data/cache/
fetch_cache.db) allows warm reruns within `cache_ttl_h`.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from config_engine import ENGINE
from engine.fetch.urls import normalize_url

DB_PATH = Path("data/cache/fetch_cache.db")


class FetchCache:
    """Per-run namespace over a persistent sqlite store."""

    def __init__(self, db_path: Path | str = DB_PATH, *, run_id: str = "", ttl_h: float | None = None):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id or time.strftime("%Y%m%dT%H%M%S")
        self.ttl_s = (ttl_h if ttl_h is not None else float(ENGINE["cache_ttl_h"])) * 3600
        self._mem: dict[str, tuple[str, list[dict], int, str]] = {}
        self._db = sqlite3.connect(self.db_path)
        # v2: raw html stored alongside text — cache hits previously returned
        # no html, breaking parsers that read markup (Viking/LexFarm finding).
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS fetch_cache_v2 ("
            "  key TEXT PRIMARY KEY, text TEXT, links_json TEXT,"
            "  status INTEGER, ts REAL, html TEXT DEFAULT '')"
        )
        self._db.commit()
        self.hits = 0
        self.misses = 0

    def _key(self, url: str) -> str:
        return normalize_url(url) or url

    def get(self, url: str) -> tuple[str, list[dict], int, str] | None:
        key = self._key(url)
        if key in self._mem:
            self.hits += 1
            text, links, status, html = self._mem[key]
            return text, [dict(l) for l in links], status, html
        row = self._db.execute(
            "SELECT text, links_json, status, ts, html FROM fetch_cache_v2 WHERE key=?", (key,)
        ).fetchone()
        if row is not None:
            text, links_json, status, ts, html = row
            if self.ttl_s <= 0 or (time.time() - ts) <= self.ttl_s:
                links = json.loads(links_json or "[]")
                self._mem[key] = (text, links, status, html or "")
                self.hits += 1
                return text, [dict(l) for l in links], status, html or ""
        self.misses += 1
        return None

    def put(self, url: str, text: str, links: list[dict], status: int = 200,
            html: str = "") -> None:
        # Don't cache failed/empty fetches — a later retry may succeed.
        if not (text or "").strip():
            return
        key = self._key(url)
        self._mem[key] = (text, links, status, html)
        self._db.execute(
            "INSERT OR REPLACE INTO fetch_cache_v2 (key, text, links_json, status, ts, html) "
            "VALUES (?,?,?,?,?,?)",
            (key, text, json.dumps(links), status, time.time(), html),
        )
        self._db.commit()

    def fetched_this_run(self) -> dict[str, str]:
        """url(normalized) → text map of everything this run has in memory —
        the gate's info-url-invariant view (R4.3: 'fetched in this run')."""
        return {k: v[0] for k, v in self._mem.items()}

    def close(self) -> None:
        self._db.close()
