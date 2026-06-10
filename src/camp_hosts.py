"""Detect recreation centers and camp venues that host programs directly."""

import re
from urllib.parse import urlparse

from config.sources import REC_CENTER_HOST_HINTS

_CAMP_HOST_PATH_RE = re.compile(
    r"summer-camp|summer-camps|/camps?[/\-]|specialty-camp|"
    r"camp-program|day-camp|lexplorations|summer_vacation|summerfun|"
    r"/summer(?:[/\-]|$)",
    re.IGNORECASE,
)

_SINGLE_PURPOSE_CAMP_DOMAIN_RE = re.compile(
    r"(^|\.)((summer)?sedge|camp[a-z0-9\-]*)\.",
    re.IGNORECASE,
)


def _host(url: str) -> str:
    return urlparse(url).netloc.lower()


def is_camp_host_seed_url(url: str) -> bool:
    """URL is itself a camp venue page (rec center summer camp, YMCA camp, etc.)."""
    if not url:
        return False
    path = urlparse(url).path.lower()
    host = _host(url)

    if _CAMP_HOST_PATH_RE.search(path):
        return True

    if any(hint in host for hint in REC_CENTER_HOST_HINTS):
        if _CAMP_HOST_PATH_RE.search(f"{host}{path}"):
            return True
        if path in ("", "/") and any(
            token in host for token in ("daycamp", "summercamp", "camp")
        ):
            return True

    if _SINGLE_PURPOSE_CAMP_DOMAIN_RE.search(host):
        return True

    if any(token in host for token in ("daycamp", "summercamp", "camp.org", "camp.com")):
        return True

    if "program_details.aspx" in path.lower():
        return True

    return False


def is_rec_center_host(url: str) -> bool:
    host = _host(url)
    return any(hint in host for hint in REC_CENTER_HOST_HINTS) or host.endswith(".gov")
