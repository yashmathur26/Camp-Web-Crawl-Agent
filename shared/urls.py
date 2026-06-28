import re
from urllib.parse import urljoin, urlparse, urlunparse, parse_qs, urlencode

_TRACKING_PARAM_RE = re.compile(r"^(utm_|fbclid|gclid|mc_)")
# Per-request/session params (esp. WebTrac/myvscloud) that change every load and
# would otherwise make identical catalog pages look like distinct URLs.
_VOLATILE_PARAMS = frozenset(
    p.lower()
    for p in (
        "_csrf_token",
        "csrf_token",
        "csrf",
        "arfmidlist",
        "interfaceparameter",
        "action",
        "subaction",
    )
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
        if _TRACKING_PARAM_RE.match(key):
            continue
        if key.lower() in _VOLATILE_PARAMS:
            continue
        for value in values:
            filtered_params.append((key, value))
    filtered_params.sort()
    query = urlencode(filtered_params, doseq=True)

    path = parsed.path
    if path.endswith("/") and path != "/":
        path = path.rstrip("/")

    return urlunparse((scheme, host, path, parsed.params, query, ""))


# Task 4.1 — params that are pure tracking/session noise on ANY register URL.
_REGISTER_DROP_PARAM_RE = re.compile(
    r"^(utm_|fbclid|gclid|_csrf|session|sid$|phpsessid)", re.IGNORECASE
)


def canonical_register_url(url: str, platform: str = "") -> str:
    """Canonical form of a register URL for dedupe (normalize_url + platform rules).

    Does NOT replace normalize_url — callers that need a fetchable URL keep the
    original; this is an identity key (WebTrac iteminfo collapses to FMID+Module,
    MyRec program_details to ProgramID, tracking/session params dropped)."""
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
            (k, v)
            for k, v in pairs
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
    """Stable per-host platform identity (FMID / ProgramID) from a canonical
    register URL; "" when the URL carries none."""
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


def to_absolute(base_url: str, href: str) -> str:
    if not href or not href.strip():
        return ""
    href = href.strip()
    lower = href.lower()
    if lower.startswith(("javascript:", "mailto:", "tel:", "#")):
        return ""
    absolute = urljoin(base_url, href)
    parsed = urlparse(absolute)
    if parsed.scheme not in ("http", "https"):
        return ""
    return absolute
