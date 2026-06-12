"""Validate Google search results before saving to candidates.csv."""

from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlparse

import tldextract

from config.sources import (
    AGGREGATOR_DENY_DOMAINS,
    GUIDE_DOMAINS,
    PREFERRED_HOST_SUBSTRINGS,
    PREFERRED_PATH_SUBSTRINGS,
    TITLE_REJECT_OVERRIDES,
    TITLE_REJECT_PATTERNS,
    URL_REJECT_PATH_PATTERNS,
)
from config.settings import STATE
from src.geo_filter import is_out_of_state_url
from src.urls import normalize_url

Verdict = Literal["keep", "reject"]
SourceType = Literal[
    "primary", "guide", "aggregator", "irrelevant", "after_school", "unknown"
]


@dataclass
class ValidationResult:
    url: str
    verdict: Verdict
    reason: str
    source_type: SourceType
    preferred: bool = False


def _registered_domain(url: str) -> str:
    parsed = urlparse(url)
    ext = tldextract.extract(parsed.netloc)
    if not ext.domain or not ext.suffix:
        return parsed.netloc.lower()
    return f"{ext.domain}.{ext.suffix}".lower()


def _combined_text(item: dict) -> str:
    parts = [
        item.get("url") or "",
        item.get("title") or "",
        item.get("snippet") or "",
    ]
    return " ".join(parts).lower()


CHAIN_BRANCH_DOMAINS: frozenset[str] = frozenset({
    "codeninjas.com", "schoolofrock.com", "goldfishswimschool.com",
    "britishswimschool.com", "idtech.com", "mathnasium.com", "kumon.com",
    "snapology.com", "kidcreate.com", "engineeringforkids.com",
    "challengersports.com", "ussportscamps.com", "supersoccerstars.com",
    "skyhawks.com", "britishsoccercamps.com",
})

_LOCATION_SIGNAL_RE = None


def _has_location_signal(url: str, title_snippet: str) -> bool:
    """/locations/<town>, MA town name in title, or an MA zip."""
    import re as _re

    from config.towns import TOWNS

    low = url.lower()
    if "/locations/" in low or "/location/" in low:
        return True
    blob = f"{low} {title_snippet.lower()}"
    if _re.search(r"\b0[12]\d{3}\b", blob):  # MA zips 01xxx/02xxx
        return True
    return any(t.lower() in blob for t in TOWNS)


def is_aggregator_domain(url: str) -> bool:
    return _registered_domain(url) in AGGREGATOR_DENY_DOMAINS


def is_guide_domain(url: str) -> bool:
    return _registered_domain(url) in GUIDE_DOMAINS


def is_preferred_source(url: str, *, title: str = "") -> bool:
    if is_out_of_state_url(url, title=title, state=STATE)[0]:
        return False
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    if any(sub in host for sub in PREFERRED_HOST_SUBSTRINGS):
        return True
    if host.endswith(".gov") and any(
        seg in path for seg in ("/recreation", "/parks", "/programs")
    ):
        return True
    if any(sub in path for sub in PREFERRED_PATH_SUBSTRINGS):
        return True
    return False


def validate_search_result(item: dict) -> ValidationResult:
    url = normalize_url(item.get("url") or item.get("href") or "")
    if not url:
        return ValidationResult("", "reject", "empty url", "irrelevant")

    title_snippet = _combined_text(item)
    parsed = urlparse(url)
    path_lower = parsed.path.lower()

    if is_aggregator_domain(url):
        # Part C 3.5: branded local-branch pages (Code Ninjas, School of Rock,
        # Goldfish Swim...) are PRIMARY sources for niche categories when the
        # URL/title carries a location signal.
        if _registered_domain(url) in CHAIN_BRANCH_DOMAINS and _has_location_signal(
            url, title_snippet
        ):
            return ValidationResult(
                url, "keep", f"chain branch w/ location: {_registered_domain(url)}", "primary"
            )
        return ValidationResult(
            url, "reject", f"aggregator domain: {_registered_domain(url)}", "aggregator"
        )

    oos, oos_reason = is_out_of_state_url(
        url,
        title=item.get("title") or "",
        snippet=item.get("snippet") or "",
        state=STATE,
    )
    if oos:
        return ValidationResult(url, "reject", f"out of state: {oos_reason}", "irrelevant")

    if is_guide_domain(url):
        return ValidationResult(
            url, "keep", f"parent guide (mine outbound): {_registered_domain(url)}", "guide"
        )

    for pattern in URL_REJECT_PATH_PATTERNS:
        if pattern in path_lower:
            return ValidationResult(
                url, "reject", f"url path contains {pattern}", "after_school"
            )

    has_reject_term = any(p in title_snippet for p in TITLE_REJECT_PATTERNS)
    has_override = any(o in title_snippet for o in TITLE_REJECT_OVERRIDES)
    if has_reject_term and not has_override:
        return ValidationResult(
            url, "reject", "title/snippet indicates after-school or non-camp", "after_school"
        )

    preferred = is_preferred_source(url, title=item.get("title") or "")
    if preferred:
        return ValidationResult(
            url, "keep", "preferred primary source host/path", "primary", preferred=True
        )

    if "summer" in title_snippet or "camp" in title_snippet:
        return ValidationResult(url, "keep", "summer/camp in metadata", "unknown")

    return ValidationResult(url, "keep", "passed rules; ambiguous", "unknown")


def validate_search_results(items: list[dict]) -> tuple[list[dict], list[ValidationResult]]:
    """Return (kept items with validation metadata, all results including rejected)."""
    kept: list[dict] = []
    all_results: list[ValidationResult] = []

    for item in items:
        result = validate_search_result(item)
        all_results.append(result)
        if result.verdict == "keep" and result.url:
            kept.append(
                {
                    "url": result.url,
                    "title": item.get("title") or "",
                    "snippet": item.get("snippet") or "",
                    "source_type": result.source_type,
                    "preferred": result.preferred,
                }
            )

    return kept, all_results
