"""Engine v3 data model (plan §2): Provider → Program → Session, plus Gap and
FetchRecord. One model, provenance on every row (R6.2). Serializes to the
four-file output schema (providers / programs / sessions / gaps).
"""

from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

PROVIDERS_COLUMNS = [
    "provider_id", "name", "host", "town", "platform", "platform_org_id",
    "seed_url", "status",
]
PROGRAMS_COLUMNS = [
    "program_id", "provider_id", "name", "info_url", "category_hint",
    "description_snippet",
]
SESSIONS_COLUMNS = [
    "session_id", "program_id", "name", "display_name", "raw_name",
    "name_source", "info_url", "register_url", "parent_url", "homepage_url",
    "nearest_hub", "register_is_info", "register_confidence", "dates",
    "ages", "price", "verdict", "evidence_json", "extractor", "fetched_at",
    "content_chars",
]
GAPS_COLUMNS = ["provider_id", "reason", "evidence", "suggested_action"]

GAP_REASONS = (
    "needs_adapter", "render_failed", "blocked", "empty", "needs_review",
    "budget_exceeded",
)
VERDICTS = ("parent_ready", "info_confirmed", "needs_review")


def _slug_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha1("|".join(p or "" for p in parts).encode("utf-8")).hexdigest()[:10]
    return f"{prefix}_{digest}"


@dataclass
class Provider:
    name: str
    host: str
    town: str
    seed_url: str
    vendor: str = "unknown"          # platform
    org_id: str = ""                 # platform_org_id
    aliases: list[str] = field(default_factory=list)
    status: str = "pending"          # pending | done | gap
    provider_id: str = ""

    def __post_init__(self) -> None:
        if not self.provider_id:
            self.provider_id = _slug_id("prov", self.host, self.town)

    def to_row(self) -> dict:
        return {
            "provider_id": self.provider_id, "name": self.name, "host": self.host,
            "town": self.town, "platform": self.vendor,
            "platform_org_id": self.org_id, "seed_url": self.seed_url,
            "status": self.status,
        }

    @classmethod
    def from_row(cls, row: dict) -> "Provider":
        return cls(
            name=row["name"], host=row["host"], town=row["town"],
            seed_url=row["seed_url"], vendor=row.get("platform", "unknown"),
            org_id=row.get("platform_org_id", ""), status=row.get("status", "pending"),
            provider_id=row.get("provider_id", ""),
        )


@dataclass
class Session:
    name: str                        # bare IDENTITY name — dedupe + eval match on this
    info_url: str
    register_url: str = ""
    dates: str = ""
    ages: str = ""
    price: str = ""
    verdict: str = ""                # parent_ready | info_confirmed | needs_review
    evidence: dict = field(default_factory=dict)
    extractor: str = ""
    fetched_at: str = ""
    content_chars: int = 0
    program_id: str = ""
    session_id: str = ""
    # Phase 5 name accuracy: a provider-prefixed human label (the CSV's parent-
    # facing name), the original extracted string for audit, and where the name
    # came from (h1/title/jsonld = reliable; slug/link_text/llm = weak).
    display_name: str = ""
    raw_name: str = ""
    name_source: str = ""
    # v3 link model (§3): the resolved link bundle. parent_url is the ONE link a
    # human sees (always populated by the 6L ladder); register_url is nullable and
    # never aliased from info_url (register_is_info marks a genuine combined page);
    # nearest_hub is the closest catalog/section page above this camp.
    parent_url: str = ""
    homepage_url: str = ""
    nearest_hub: str = ""
    register_is_info: bool = False
    register_confidence: str = ""    # "" | high | medium | low
    # Phase 3 page role (registration | info | peripheral). Transient: computed by
    # the extractor where html/links exist, consumed by the gate in the same run;
    # not a CSV column (gate has already run before serialization).
    page_role: str = ""

    def __post_init__(self) -> None:
        if not self.session_id:
            self.session_id = _slug_id("sess", self.program_id, self.name, self.dates, self.info_url)

    def to_row(self) -> dict:
        return {
            "session_id": self.session_id, "program_id": self.program_id,
            "name": self.name, "display_name": self.display_name or self.name,
            "raw_name": self.raw_name, "name_source": self.name_source,
            "info_url": self.info_url,
            "register_url": self.register_url, "parent_url": self.parent_url,
            "homepage_url": self.homepage_url, "nearest_hub": self.nearest_hub,
            "register_is_info": self.register_is_info,
            "register_confidence": self.register_confidence, "dates": self.dates,
            "ages": self.ages, "price": self.price, "verdict": self.verdict,
            "evidence_json": json.dumps(self.evidence, sort_keys=True),
            "extractor": self.extractor, "fetched_at": self.fetched_at,
            "content_chars": self.content_chars,
        }

    @classmethod
    def from_row(cls, row: dict) -> "Session":
        return cls(
            name=row["name"], info_url=row["info_url"],
            register_url=row.get("register_url", ""), dates=row.get("dates", ""),
            ages=row.get("ages", ""), price=row.get("price", ""),
            verdict=row.get("verdict", ""),
            evidence=json.loads(row.get("evidence_json") or "{}"),
            extractor=row.get("extractor", ""), fetched_at=row.get("fetched_at", ""),
            content_chars=int(row.get("content_chars") or 0),
            program_id=row.get("program_id", ""), session_id=row.get("session_id", ""),
            display_name=row.get("display_name", ""), raw_name=row.get("raw_name", ""),
            name_source=row.get("name_source", ""),
            parent_url=row.get("parent_url", ""), homepage_url=row.get("homepage_url", ""),
            nearest_hub=row.get("nearest_hub", ""),
            register_is_info=str(row.get("register_is_info", "")).lower() in ("true", "1"),
            register_confidence=row.get("register_confidence", ""),
        )


@dataclass
class Program:
    name: str
    provider_id: str
    info_url: str = ""
    category_hint: str = ""
    description_snippet: str = ""
    sessions: list[Session] = field(default_factory=list)
    # True when the program came from a camp-scoped catalog (WebTrac type=CAMP,
    # an ACTIVE camp season, /lexplorations/ weeks) — R4.2: that IS the evidence.
    camp_scoped: bool = False
    program_id: str = ""

    def __post_init__(self) -> None:
        if not self.program_id:
            self.program_id = _slug_id("prog", self.provider_id, self.name)
        for s in self.sessions:
            if not s.program_id:
                s.program_id = self.program_id
                s.session_id = _slug_id("sess", s.program_id, s.name, s.dates, s.info_url)

    def to_row(self) -> dict:
        return {
            "program_id": self.program_id, "provider_id": self.provider_id,
            "name": self.name, "info_url": self.info_url,
            "category_hint": self.category_hint,
            "description_snippet": self.description_snippet[:300],
        }

    @classmethod
    def from_row(cls, row: dict) -> "Program":
        return cls(
            name=row["name"], provider_id=row["provider_id"],
            info_url=row.get("info_url", ""),
            category_hint=row.get("category_hint", ""),
            description_snippet=row.get("description_snippet", ""),
            program_id=row.get("program_id", ""),
        )


@dataclass
class Gap:
    provider_id: str
    reason: str                      # one of GAP_REASONS
    evidence: str = ""
    suggested_action: str = ""

    def __post_init__(self) -> None:
        if self.reason not in GAP_REASONS:
            raise ValueError(f"unknown gap reason {self.reason!r}; use one of {GAP_REASONS}")

    def to_row(self) -> dict:
        return {
            "provider_id": self.provider_id, "reason": self.reason,
            "evidence": self.evidence, "suggested_action": self.suggested_action,
        }

    @classmethod
    def from_row(cls, row: dict) -> "Gap":
        return cls(
            provider_id=row["provider_id"], reason=row["reason"],
            evidence=row.get("evidence", ""),
            suggested_action=row.get("suggested_action", ""),
        )


@dataclass
class FetchRecord:
    url: str
    status: str          # ok | error | refused | cache
    ms: int = 0
    chars: int = 0
    note: str = ""


# --------------------------------------------------------------------------- #
# Four-file (de)serialization — ONE writer shape (R6.1 consumes this).
# --------------------------------------------------------------------------- #

# sessions.csv is the CONFIRMED tier (the deliverable); review.csv is the
# separate human-markup tier (thin-evidence / off-domain / unresolved rows);
# gaps.csv is diagnosed-not-published. One writer, three published tiers (plan
# Phase 1). review.csv shares the session schema.
_FILES = {
    "providers.csv": PROVIDERS_COLUMNS,
    "programs.csv": PROGRAMS_COLUMNS,
    "sessions.csv": SESSIONS_COLUMNS,
    "review.csv": SESSIONS_COLUMNS,
    "gaps.csv": GAPS_COLUMNS,
}


def write_output(
    out_dir: Path,
    providers: list[Provider],
    programs: list[Program],
    gaps: list[Gap],
    review: list[Program] | None = None,
) -> dict[str, int]:
    """Write the CSVs. Sessions are flattened from programs (one nesting, one
    writer). `programs` is the confirmed tier → sessions.csv; `review` is the
    review tier → review.csv. Returns row counts per file — the same counts logs
    must print."""
    out_dir.mkdir(parents=True, exist_ok=True)
    sessions = [s for p in programs for s in p.sessions]
    review_sessions = [s for p in (review or []) for s in p.sessions]
    rows = {
        "providers.csv": [p.to_row() for p in providers],
        "programs.csv": [p.to_row() for p in programs],
        "sessions.csv": [s.to_row() for s in sessions],
        "review.csv": [s.to_row() for s in review_sessions],
        "gaps.csv": [g.to_row() for g in gaps],
    }
    for fname, columns in _FILES.items():
        with open(out_dir / fname, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=columns)
            w.writeheader()
            w.writerows(rows[fname])
    return {fname: len(rows[fname]) for fname in _FILES}


def read_output(out_dir: Path) -> dict:
    def _read(fname, cls):
        path = out_dir / fname
        if not path.exists():
            return []
        with open(path, newline="", encoding="utf-8") as f:
            return [cls.from_row(r) for r in csv.DictReader(f)]

    return {
        "providers": _read("providers.csv", Provider),
        "programs": _read("programs.csv", Program),
        "sessions": _read("sessions.csv", Session),
        "review": _read("review.csv", Session),
        "gaps": _read("gaps.csv", Gap),
    }
