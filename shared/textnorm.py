"""Shared program-name normalization (scorer + dedupe import from here).

Lives in src/ so both src/ modules and scripts/ can import it — scripts must
never be imported from src/.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

# Tokens that carry no program identity ("Summer Camp 2026 — Week 3").
_STRIP_TOKENS = frozenset(
    {"camp", "camps", "summer", "2025", "2026", "week", "session", "the", "a"}
)
_PUNCT_RE = re.compile(r"[^\w\s]")


def host_of_url(url: str) -> str:
    """Netloc of url, lowercase, leading www. stripped."""
    h = urlparse(url or "").netloc.lower()
    return h[4:] if h.startswith("www.") else h


def norm_name(name: str) -> str:
    """Lowercase, strip punctuation, drop filler tokens, collapse whitespace."""
    low = _PUNCT_RE.sub(" ", (name or "").lower())
    kept = [t for t in low.split() if t not in _STRIP_TOKENS]
    return " ".join(kept)


def program_key(host: str, name: str) -> tuple[str, str]:
    """Program identity: (host, normalized name)."""
    return (host, norm_name(name))
