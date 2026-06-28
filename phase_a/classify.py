from typing import Literal
from urllib.parse import urlparse

import tldextract

from config.sources import GUIDE_DOMAINS

DirectoryCampUnknown = Literal["directory", "camp", "unknown", "guide"]

_DIRECTORY_PATH_HINTS = (
    "/camps",
    "/programs",
    "/directory",
    "/activities",
    "/recreation",
    "/camp-guide",
    "/summer-camps",
    "/youth-programs",
    "/summer-camp",
)

_CAMP_PATH_HINTS = (
    "/camp/",
    "/program/",
    "/class/",
    "/clinic/",
    "/session/",
    "/workshop/",
    "/lessons/",
    "/academy/",
)

_PRIMARY_HOST_HINTS = (
    "communityed.org",
    "communityed.com",
    "myrec.com",
    "ymca.org",
    "ymca.net",
)


def _registered_domain(url: str) -> str:
    parsed = urlparse(url)
    ext = tldextract.extract(parsed.netloc)
    if not ext.domain or not ext.suffix:
        return parsed.netloc.lower()
    return f"{ext.domain}.{ext.suffix}".lower()


def classify(url: str) -> DirectoryCampUnknown:
    parsed = urlparse(url)
    path_lower = parsed.path.lower()
    host_lower = parsed.netloc.lower()

    if _registered_domain(url) in GUIDE_DOMAINS:
        return "guide"

    for hint in _PRIMARY_HOST_HINTS:
        if hint in host_lower:
            return "directory"

    if host_lower.endswith(".gov") and any(
        seg in path_lower for seg in ("/recreation", "/parks", "/programs")
    ):
        return "directory"

    for hint in _DIRECTORY_PATH_HINTS:
        if hint in path_lower:
            return "directory"

    for hint in _CAMP_PATH_HINTS:
        if hint in path_lower:
            return "camp"

    if any(
        segment in path_lower
        for segment in ("/list", "/guide", "/roundup", "/catalog")
    ):
        return "directory"

    return "unknown"
