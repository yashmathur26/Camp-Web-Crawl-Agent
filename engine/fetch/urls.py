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


# --- platform-canonical link identity (v3 §2.3, PORTED from src/urls.py) ------
# normalize_url gives string identity; on a KNOWN platform the identity is the
# platform key (WebTrac FMID+Module, MyRec ProgramID) so reordered/tracked URLs
# for the same item collapse to one. Used for register dedupe + "same link".
_REGISTER_DROP_PARAM_RE = re.compile(
    r"^(?:_csrf|csrf|utm_|fbclid|gclid|mc_|session|sid|jsessionid|phpsessid)", re.I
)


def canonical_register_url(url: str, platform: str = "") -> str:
    """Identity key for a register URL (NOT a fetchable URL): normalize_url plus
    platform rules — WebTrac iteminfo collapses to FMID+Module, MyRec
    program_details to ProgramID, tracking/session params dropped."""
    norm = normalize_url(url)
    if not norm:
        return ""
    parsed = urlparse(norm)
    host = parsed.netloc.lower()
    path_low = parsed.path.lower()
    pairs = [
        (k, v)
        for k, vs in parse_qs(parsed.query, keep_blank_values=True).items()
        for v in vs
    ]
    is_webtrac = "myvscloud" in host or platform == "webtrac"
    if is_webtrac and "iteminfo.html" in path_low:
        pairs = [(k, v) for k, v in pairs if k.lower() in ("fmid", "module")]
    elif is_webtrac and "search.html" in path_low:
        pairs = [
            (k, v) for k, v in pairs
            if k.lower() != "_csrf_token" and not k.lower().startswith("arwebsearch")
        ]
    elif platform == "myrec" or "program_details.aspx" in path_low:
        pairs = [(k, v) for k, v in pairs if k.lower() == "programid"]
    pairs = [(k, v) for k, v in pairs if not _REGISTER_DROP_PARAM_RE.match(k)]
    pairs.sort()
    return urlunparse(
        (parsed.scheme, parsed.netloc, parsed.path, parsed.params, urlencode(pairs), "")
    )


def register_platform_id(url: str) -> str:
    """Stable per-host platform identity (`host|fmid|<id>` / `host|programid|<id>`)
    from a register URL; "" when the URL carries no item id."""
    if not url:
        return ""
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    qs = {k.lower(): vs for k, vs in parse_qs(parsed.query).items()}
    if "iteminfo.html" in parsed.path.lower() and qs.get("fmid"):
        return f"{host}|fmid|{qs['fmid'][0]}"
    if "program_details.aspx" in parsed.path.lower() and qs.get("programid"):
        return f"{host}|programid|{qs['programid'][0]}"
    return ""
