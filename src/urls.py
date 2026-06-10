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
