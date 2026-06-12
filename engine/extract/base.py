"""Extractor interface + vendor dispatch (plan §5, task 3.1).

An extractor returns programs+sessions with candidate info_urls, or a diagnosed
gap. It must not publish (the gate does), must not call the LLM unless it is
generic.py, and prefers the vendor's data path over rendering (R5.7). An
extractor returning zero programs MUST return a Gap (R4.4).
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from engine.fetch.client import Budget, FetchClient
from engine.model import FetchRecord, Gap, Program, Provider

_WEEK_LABEL_RE = re.compile(
    r"\b(?:week|session|wk|sess)\s*(?:[#:]?\s*)?(?:\d+|one|two|three|four|five|"
    r"six|seven|eight|nine|ten)\b",
    re.I,
)
_DATE_FRAG_RE = re.compile(
    r"\(?\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s*\d{1,2}"
    r"(?:\s*[-–—]\s*(?:[a-z]+\.?\s*)?\d{1,2})?(?:st|nd|rd|th)?\)?"
    r"|\(?\b\d{1,2}/\d{1,2}(?:/\d{2,4})?(?:\s*[-–—]\s*\d{1,2}/\d{1,2}(?:/\d{2,4})?)?\)?"
    r"|\b20\d{2}\b",
    re.I,
)


def normalize_program_name(name: str) -> str:
    """Grouping key (plan §2): strip dates, week labels, session numbers."""
    s = _DATE_FRAG_RE.sub(" ", name or "")
    s = _WEEK_LABEL_RE.sub(" ", s)
    s = re.sub(r"[\s\-–—:,()/]+$", "", s)
    s = re.sub(r"^[\s\-–—:,()/]+", "", s)
    return re.sub(r"\s+", " ", s).strip()


@dataclass
class ExtractResult:
    programs: list[Program] = field(default_factory=list)
    gap: Gap | None = None
    fetch_log: list[FetchRecord] = field(default_factory=list)


class Extractor(ABC):
    vendor: str = "unknown"

    @abstractmethod
    async def extract(self, provider: Provider, fetch: FetchClient) -> ExtractResult:
        ...


def group_sessions_into_programs(
    provider: Provider,
    raw_sessions: list,
    *,
    camp_scoped: bool = False,
    program_info_url: dict[str, str] | None = None,
) -> list[Program]:
    """Collapse identical-name-modulo-dates sessions into Programs
    (Hayden's 10 'Lower Camp' weeks = 1 program / 10 sessions)."""
    by_key: dict[str, Program] = {}
    for sess in raw_sessions:
        key = normalize_program_name(sess.name).lower()
        if not key:
            key = sess.name.lower()
        if key not in by_key:
            display = normalize_program_name(sess.name) or sess.name
            prog = Program(
                name=display,
                provider_id=provider.provider_id,
                info_url=(program_info_url or {}).get(key, sess.info_url),
                camp_scoped=camp_scoped,
            )
            by_key[key] = prog
        prog = by_key[key]
        sess.program_id = prog.program_id
        prog.sessions.append(sess)
    return list(by_key.values())


# --------------------------------------------------------------------------- #
# Dispatch (runner hook). Vendors register here as they land.
# --------------------------------------------------------------------------- #

def _vendors() -> dict[str, Extractor]:
    from engine.extract.vendors.active import ActiveExtractor
    from engine.extract.vendors.campbrain import CampbrainExtractor
    from engine.extract.vendors.daxko import DaxkoExtractor
    from engine.extract.vendors.enrollsy import EnrollsyExtractor
    from engine.extract.vendors.communityed import CommunityedExtractor
    from engine.extract.vendors.myrec import MyrecExtractor
    from engine.extract.vendors.sawyer import SawyerExtractor
    from engine.extract.vendors.webtrac import WebtracExtractor

    table: dict[str, Extractor] = {
        "webtrac": WebtracExtractor(),
        "myrec": MyrecExtractor(),
        "active": ActiveExtractor(),
        "communityed": CommunityedExtractor(),
        "sawyer": SawyerExtractor(),
        "campbrain": CampbrainExtractor(),
        "enrollsy": EnrollsyExtractor(),
        "daxko": DaxkoExtractor(),
    }
    try:
        from engine.extract.generic import GenericExtractor

        table["unknown"] = GenericExtractor()
    except ImportError:
        pass  # Phase 5 — until then unknown vendors gap as needs_adapter
    return table


_shared_client: FetchClient | None = None


def shared_client() -> FetchClient:
    global _shared_client
    if _shared_client is None:
        _shared_client = FetchClient()
    return _shared_client


def reset_shared_client() -> None:
    global _shared_client
    if _shared_client is not None:
        _shared_client.close()
    _shared_client = None


async def extract_for_provider(provider: Provider):
    """Runner entry: dispatch by vendor; unknown → generic (or needs_adapter).
    Returns (programs, gap, fetched_text) — fetched_text is the run-cache view
    the gate's info-url invariant reads (R4.3)."""
    fetch = shared_client()
    table = _vendors()
    # Task 4.6: a KNOWN vendor without an implementation is a needs_adapter
    # stub — only vendor "unknown" routes to the generic path.
    extractor = table.get(provider.vendor)
    if extractor is None and provider.vendor == "unknown":
        extractor = table.get("unknown")
    if extractor is None:
        gap = Gap(
            provider_id=provider.provider_id, reason="needs_adapter",
            evidence=f"no extractor for vendor '{provider.vendor}'",
            suggested_action=f"implement engine/extract/vendors/{provider.vendor}.py",
        )
        return [], gap, {}
    try:
        result = await extractor.extract(provider, fetch)
    except Exception as exc:  # noqa: BLE001 — diagnose, never crash the town
        gap = Gap(
            provider_id=provider.provider_id, reason="render_failed",
            evidence=f"{type(exc).__name__}: {exc}",
            suggested_action="inspect engine log",
        )
        return [], gap, fetch.cache.fetched_this_run()
    if not result.programs and result.gap is None:
        result.gap = Gap(
            provider_id=provider.provider_id, reason="needs_review",
            evidence="extractor returned zero programs without a diagnosis (R4.4 bug)",
            suggested_action="fix the extractor to diagnose its gap",
        )
    return result.programs, result.gap, fetch.cache.fetched_this_run()
