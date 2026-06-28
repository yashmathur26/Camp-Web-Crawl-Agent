"""roadmap2 Phase 2 — capture-then-extract.

Persist a *rendered* page's text to disk (data/<town>/phase_b5/captured/) so
extraction runs against a fully-loaded copy instead of racing page load, and so
the same capture can be re-extracted offline with a better model without
re-crawling. Gated by SETTINGS["b5_capture_pages"].

Caveat (roadmap2 §6.2): this only helps if the capture step rendered first —
it rides on the Phase 2 render fixes, it does not replace them. Saving an
un-rendered shell just stores an empty page.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from config.settings import SETTINGS
from shared.data_layout import town_phase_dir
from shared.urls import normalize_url

logger = logging.getLogger(__name__)


def _capture_dir(town: str) -> Path:
    return town_phase_dir(town, "phase_b5") / "captured"


def _key(url: str) -> str:
    norm = normalize_url(url) or url
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()[:16]


def capture_enabled() -> bool:
    return bool(SETTINGS.get("b5_capture_pages", False))


def capture_page(town: str, url: str, text: str, *, html: str = "") -> Path | None:
    """Write the rendered text (and optional raw HTML) to the per-town cache.

    Returns the path written, or None if capture is disabled / there's nothing
    worth saving (an empty render is not persisted — see the §6.2 caveat)."""
    if not capture_enabled() or not (text or "").strip():
        return None
    cdir = _capture_dir(town)
    cdir.mkdir(parents=True, exist_ok=True)
    key = _key(url)
    md = cdir / f"{key}.md"
    md.write_text(f"<!-- {normalize_url(url) or url} -->\n\n{text}", encoding="utf-8")
    if html:
        (cdir / f"{key}.html").write_text(html, encoding="utf-8")
    return md


def load_capture(town: str, url: str) -> str | None:
    """Read back a previously captured page's text, or None if not captured."""
    md = _capture_dir(town) / f"{_key(url)}.md"
    if not md.exists():
        return None
    body = md.read_text(encoding="utf-8")
    # Strip the leading "<!-- url -->\n\n" provenance line.
    return body.split("\n\n", 1)[1] if "\n\n" in body else body
