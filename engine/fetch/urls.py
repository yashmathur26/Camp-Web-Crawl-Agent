"""URL normalization — PORTED from src/urls.py (R2: owned by engine).

normalize_url is the cache key (R5.3): tracking/volatile params (WebTrac CSRF
tokens etc.) are stripped so identical catalog pages don't look distinct.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

_TRACKING_PARAM_RE = re.compile(r"^(utm_|fbclid|gclid|mc_)")
# Per-request/session params (esp. WebTrac/myvscloud) that change every load.
_VOLATILE_PARAMS = frozenset(
    p.lower()
    for p in (
        "_csrf_token", "csrf_token", "csrf", "arfmidlist",
        "interfaceparameter", "action", "subaction",
    )
)

# R5.5: media/asset URL classes are never pages.
MEDIA_URL_RE = re.compile(
    r"\.(?:pdf|png|jpe?g|gif|svg|webp|ico|css|js|docx?|xlsx?|pptx?|zip|mp[34])"
    r"(?:$|\?)|/documentcenter/|/wp-content/uploads/",
    re.I,
)


def normalize_url(url: str) -> str:
    if not url or not url.strip():
        return ""
    parsed = urlparse(url.strip())
    if not parsed.scheme or not parsed.netloc:
        return url.strip()

    scheme = "https"
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]

    filtered_params = []
    for key, values in parse_qs(parsed.query, keep_blank_values=True).items():
        if _TRACKING_PARAM_RE.match(key) or key.lower() in _VOLATILE_PARAMS:
            continue
        for value in values:
            filtered_params.append((key, value))
    filtered_params.sort()
    query = urlencode(filtered_params, doseq=True)

    path = parsed.path
    if path.endswith("/") and path != "/":
        path = path.rstrip("/")

    return urlunparse((scheme, host, path, parsed.params, query, ""))


def to_absolute(base_url: str, href: str) -> str:
    if not href or not href.strip():
        return ""
    href = href.strip()
    if href.lower().startswith(("javascript:", "mailto:", "tel:", "#")):
        return ""
    absolute = urljoin(base_url, href)
    if urlparse(absolute).scheme not in ("http", "https"):
        return ""
    return absolute


def is_media_url(url: str) -> bool:
    return bool(MEDIA_URL_RE.search((url or "").lower()))
