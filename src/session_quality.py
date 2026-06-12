"""Phase Q: tier sessions into registrable / needs_trail / rejected."""

from __future__ import annotations

import csv
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from config.settings import STATE
from src.csv_mirror import write_csv_bundle
from src.data_layout import (
    PHASE_META,
    quality_tier_csv,
    parent_verdict_csv,
    refresh_town_index,
    sessions_verified_csv,
    town_phase_dir,
)
from src.geo_filter import is_national_camp_index, is_out_of_state_url
from src.registration import is_registration_platform_url, registration_url_priority
from src.sessions import SESSION_CSV_COLUMNS

PARENT_VERIFY_COLUMNS = [
    "parent_verdict",
    "enrollment_signals",
    "parent_verify_reason",
]

HUB_PATH_RE = re.compile(
    r"/program/(teens|children-classes|faq|membership)(/|$|\?)",
    re.I,
)
JUNK_REGISTER_RE = re.compile(
    r"\.pdf($|\?)|wp-content/uploads|/government/|/discover/contact|"
    r"documentcenter|spedchildmass\.com/special-needs",
    re.I,
)
NATIONAL_INDEX_PATH = re.compile(r"/overnight-camps|/find-a-camp|/camp-finder", re.I)


def _has_platform_id(url: str) -> bool:
    low = url.lower()
    if "iteminfo" in low and "fmid=" in low.replace(" ", ""):
        return True
    if "program_details.aspx" in low:
        qs = parse_qs(urlparse(url).query)
        if qs.get("ProgramID") or qs.get("programid"):
            return True
    if re.search(r"/class/[^/]+/?$", urlparse(url).path, re.I):
        host = urlparse(url).netloc.lower()
        if host.endswith("communityed.org") or host.endswith("communityed.com"):
            return True
    return False


def classify_session_tier(session: dict) -> tuple[str, str]:
    """Return (tier, reason) where tier is registrable|needs_trail|rejected."""
    reg = session.get("register_url", "")
    name = session.get("name", "")
    platform = session.get("platform", "")
    source = session.get("source_url", reg)

    oos, oos_reason = is_out_of_state_url(reg, title=name, state=STATE)
    if oos:
        return "rejected", oos_reason

    national, national_reason = is_national_camp_index(reg)
    if national or NATIONAL_INDEX_PATH.search(reg):
        return "rejected", national_reason or "national camp index"

    if HUB_PATH_RE.search(reg):
        return "rejected", "program hub page (not a camp session)"

    if JUNK_REGISTER_RE.search(reg):
        return "rejected", "junk register URL (PDF/hub/index)"

    # Task 1.3: provider-level program rows are exempt from date-based checks and
    # never rejected for thin metadata — geo/junk rejections above still apply.
    if (session.get("granularity") or "") == "program":
        if registration_url_priority(reg) > 0:
            return "registrable", "provider program row with platform register URL"
        return "needs_trail", "provider-level program row"

    if platform == "llm" and not is_registration_platform_url(reg) and not _has_platform_id(reg):
        if reg.rstrip("/") == source.rstrip("/"):
            return "needs_trail", "LLM session with marketing page as register URL"
        return "needs_trail", "LLM session without platform register URL"

    if session.get("kind") == "portal" and not is_registration_platform_url(reg):
        return "needs_trail", "portal entry — needs registration trail"

    if is_registration_platform_url(reg) or _has_platform_id(reg):
        return "registrable", "platform register URL"

    if reg and reg != source:
        return "needs_trail", "register URL not on known platform"

    return "needs_trail", "no registrable URL found"


def split_sessions(sessions: list[dict]) -> dict[str, list[dict]]:
    tiers: dict[str, list[dict]] = {
        "registrable": [],
        "needs_trail": [],
        "rejected": [],
    }
    for s in sessions:
        tier, reason = classify_session_tier(s)
        tiers[tier].append({**s, "quality_tier": tier, "quality_reason": reason})
    return tiers


def write_quality_csvs(
    town: str,
    sessions: list[dict],
    *,
    output_dir: Path | str | None = None,
) -> dict[str, Path]:
    _ = output_dir  # legacy; paths come from data_layout
    town_phase_dir(town, "phase_q")
    tiers = split_sessions(sessions)
    paths: dict[str, Path] = {}
    cols = [*SESSION_CSV_COLUMNS, "quality_tier", "quality_reason"]
    title_base, desc = PHASE_META["phase_q"]
    tier_labels = {
        "registrable": "Registrable — URL looks like a real signup page",
        "needs_trail": "Needs trail — camp found but register link is weak",
        "rejected": "Rejected — geo junk, hubs, PDFs, national indexes",
    }
    for tier_name, rows in tiers.items():
        csv_path = quality_tier_csv(town, tier_name)
        write_csv_bundle(
            csv_path,
            rows,
            cols,
            title=f"{town} — {tier_labels[tier_name]}",
            description=desc,
        )
        paths[tier_name] = csv_path
    refresh_town_index(town)
    return paths


def split_parent_verdicts(sessions: list[dict]) -> dict[str, list[dict]]:
    """Split sessions by Phase P parent_verdict (falls back to quality tier)."""
    buckets: dict[str, list[dict]] = {
        "parent_ready": [],
        "brochure_only": [],
        "wrong_audience": [],
        "fetch_failed": [],
        "unverified": [],
    }
    for s in sessions:
        verdict = s.get("parent_verdict", "")
        if not verdict:
            tier, _ = classify_session_tier(s)
            if tier == "rejected":
                verdict = "wrong_audience"
            elif tier == "registrable":
                verdict = "unverified"
            else:
                verdict = "unverified"
        if verdict not in buckets:
            verdict = "unverified"
        buckets[verdict].append(s)
    return buckets


def write_parent_verify_csvs(
    town: str,
    sessions: list[dict],
    *,
    output_dir: Path | str | None = None,
) -> dict[str, Path]:
    _ = output_dir
    town_phase_dir(town, "phase_p")
    buckets = split_parent_verdicts(sessions)
    paths: dict[str, Path] = {}
    base_cols = [*SESSION_CSV_COLUMNS, "quality_tier", "quality_reason", *PARENT_VERIFY_COLUMNS]
    _, desc = PHASE_META["phase_p"]
    verdict_labels = {
        "parent_ready": "Parent-ready — youth camp with register path",
        "brochure_only": "Brochure only — described but cannot enroll on this URL",
        "wrong_audience": "Wrong audience — adult ed, not youth summer camp",
        "fetch_failed": "Fetch failed — page did not load",
        "unverified": "Unverified — could not confirm enrollment",
    }
    for verdict, rows in buckets.items():
        if verdict == "all":
            continue
        csv_path = parent_verdict_csv(town, verdict)
        write_csv_bundle(
            csv_path,
            rows,
            base_cols,
            title=f"{town} — {verdict_labels.get(verdict, verdict)}",
            description=desc,
        )
        paths[verdict] = csv_path
    all_path = sessions_verified_csv(town)
    write_csv_bundle(
        all_path,
        sessions,
        base_cols,
        title=f"{town} — all sessions after parent verify",
        description=desc,
    )
    paths["all"] = all_path
    refresh_town_index(town)
    return paths


def enrollability_score(sessions: list[dict]) -> tuple[int, dict[str, int]]:
    """Score 0-100; uses parent_ready when Phase P columns present."""
    total = len(sessions) or 1
    parent_counts = split_parent_verdicts(sessions)
    has_parent = any(s.get("parent_verdict") for s in sessions)
    if has_parent:
        ready = len(parent_counts["parent_ready"])
        partial = len(parent_counts["unverified"])
        weighted = ready + 0.5 * partial
        score = round(100 * weighted / total)
        tiers = split_sessions(sessions)
        counts = {k: len(v) for k, v in tiers.items()}
        counts["parent_ready"] = ready
        counts["brochure_only"] = len(parent_counts["brochure_only"])
        return score, counts
    tiers = split_sessions(sessions)
    counts = {k: len(v) for k, v in tiers.items()}
    score = round(100 * counts["registrable"] / total)
    return score, counts
