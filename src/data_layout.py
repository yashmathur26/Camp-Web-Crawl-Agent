"""Canonical paths for data/ and logs/ — one folder per town and phase."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

DATA_ROOT = Path(os.environ.get("FIREFLY_DATA_ROOT", "data"))
LOGS_ROOT = Path(os.environ.get("FIREFLY_LOGS_ROOT", "logs"))

PHASE_META: dict[str, tuple[str, str]] = {
    "phase_a": (
        "Phase A — Search discovery",
        "Google searches find recreation centers, community ed, YMCAs, and parent guides. "
        "Outputs: candidates.csv (keep) and rejected_candidates.csv (dropped at ingest).",
    ),
    "phase_b": (
        "Phase B — Crawl and harvest",
        "Visits provider websites and saves camp-related registration URLs. "
        "Outputs: camp_links.csv and harvest activity logs.",
    ),
    "phase_b5": (
        "Phase B.5 — Session enumeration",
        "Lists individual camp sessions from each provider (MyRec, WebTrac, Lexplorations, etc.). "
        "Outputs: camp_sessions.csv — one row per registrable camp week or program.",
    ),
    "phase_q": (
        "Phase Q — URL quality tiers",
        "Sorts sessions by register URL quality: registrable, needs_trail, or rejected. "
        "No page fetch — URL rules only.",
    ),
    "phase_p": (
        "Phase P — Parent enrollment verify",
        "Checks whether a parent can actually register (cart, price, youth summer camp). "
        "Outputs: parent_ready, brochure_only, wrong_audience, etc.",
    ),
    "phase_trail": (
        "Phase B.6 — Registration trail",
        "Follows marketing pages to find real signup URLs for weak register links.",
    ),
    "phase_gap": (
        "Phase C — Agentic gap fill",
        "Audits catalog holes and runs targeted searches to find missing camps.",
    ),
    "deliverables": (
        "Deliverables — Parent-ready bundle",
        "Organized exports, catalog walkthrough, and quality report for the town.",
    ),
}


def town_slug(town: str) -> str:
    return town.lower().replace(" ", "_")


def shared_phase_dir(phase: str) -> Path:
    return _ensure_phase_dir(DATA_ROOT / "shared" / phase, phase)


def town_phase_dir(town: str, phase: str) -> Path:
    return _ensure_phase_dir(DATA_ROOT / town_slug(town) / phase, phase)


def town_root(town: str) -> Path:
    p = DATA_ROOT / town_slug(town)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _ensure_phase_dir(path: Path, phase: str) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    title, desc = PHASE_META.get(phase, (phase, ""))
    readme = path / "DESCRIPTION.txt"
    readme.write_text(
        f"{title}\n{'=' * len(title)}\n\n{desc}\n",
        encoding="utf-8",
    )
    return path


def data_root_readme() -> Path:
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    lines = [
        "CAMP DISCOVERY DATA LAYOUT",
        "==========================",
        "",
        "shared/",
        "  Cross-town discovery (Phase A search + Phase B harvest).",
        "",
        "<town>/  (e.g. lexington/, burlington/)",
        "  Per-town pipeline outputs, one subfolder per phase:",
    ]
    for phase, (title, _) in PHASE_META.items():
        if phase == "deliverables":
            continue
        lines.append(f"    {phase}/  — {title}")
    lines.extend(
        [
            "    deliverables/  — final parent bundle",
            "",
            "Every .csv has a matching .txt with the same data in readable form.",
            "Each phase folder contains DESCRIPTION.txt explaining that step.",
            "",
            f"Updated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        ]
    )
    path = DATA_ROOT / "README.txt"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def refresh_town_index(town: str) -> Path:
    """Rewrite town README listing phase folders and files."""
    root = town_root(town)
    slug = town_slug(town)
    lines = [
        f"{town.upper()}, {slug} — pipeline outputs",
        "=" * 50,
        "",
        "Each subfolder is one pipeline step. Open DESCRIPTION.txt inside any folder",
        "to learn what that step does. Pair every .csv with its .txt sibling.",
        "",
    ]
    for phase in (
        "phase_b5",
        "phase_q",
        "phase_p",
        "phase_trail",
        "phase_gap",
        "deliverables",
    ):
        pdir = root / phase
        if not pdir.is_dir():
            continue
        title = PHASE_META.get(phase, (phase, ""))[0]
        lines.append(f"## {title}")
        lines.append(f"   {slug}/{phase}/")
        for f in sorted(pdir.iterdir()):
            if f.name == "DESCRIPTION.txt":
                continue
            lines.append(f"   - {f.name}")
        lines.append("")
    path = root / "README.txt"
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return path


# --- Shared (cross-town) paths ---

def candidates_csv() -> Path:
    return shared_phase_dir("phase_a") / "candidates.csv"


def rejected_candidates_csv() -> Path:
    return shared_phase_dir("phase_a") / "rejected_candidates.csv"


def camp_links_csv() -> Path:
    return shared_phase_dir("phase_b") / "camp_links.csv"


def harvest_activity_csv(timestamp: str | None = None) -> Path:
    ts = timestamp or datetime.now().strftime("%Y-%m-%d_%H%M")
    return shared_phase_dir("phase_b") / f"harvest_activity_{ts}.csv"


def platform_fingerprint_csv() -> Path:
    return shared_phase_dir("phase_b") / "platform_fingerprint_report.csv"


# --- Town-scoped paths ---

def camp_sessions_csv(town: str) -> Path:
    return town_phase_dir(town, "phase_b5") / "camp_sessions.csv"


def quality_tier_csv(town: str, tier: str) -> Path:
    return town_phase_dir(town, "phase_q") / f"{tier}.csv"


def parent_verdict_csv(town: str, verdict: str) -> Path:
    return town_phase_dir(town, "phase_p") / f"{verdict}.csv"


def sessions_verified_csv(town: str) -> Path:
    return town_phase_dir(town, "phase_p") / "all_verified.csv"


def trail_log_txt(town: str) -> Path:
    return town_phase_dir(town, "phase_trail") / "trail_log.txt"


def gap_audit_json(town: str, round_num: int) -> Path:
    return town_phase_dir(town, "phase_gap") / f"audit_round{round_num}.json"


def gap_new_sessions_csv(town: str) -> Path:
    return town_phase_dir(town, "phase_gap") / "new_sessions.csv"


def deliverables_dir(town: str) -> Path:
    return town_phase_dir(town, "deliverables")


def pilot_analysis_md(town: str) -> Path:
    return town_root(town) / "pilot_analysis.md"


# --- Logs ---

def shared_log_dir() -> Path:
    p = LOGS_ROOT / "shared"
    p.mkdir(parents=True, exist_ok=True)
    return p


def town_log_dir(town: str) -> Path:
    p = LOGS_ROOT / town_slug(town)
    p.mkdir(parents=True, exist_ok=True)
    return p


def run_log_path(*, agent: bool = False) -> Path:
    prefix = "agent" if agent else "run"
    return shared_log_dir() / f"{prefix}_{datetime.now().strftime('%Y-%m-%d')}.log"


def session_log_path(town: str) -> Path:
    ts = datetime.now().strftime("%Y-%m-%d_%H%M")
    return town_log_dir(town) / f"b5_sessions_{ts}.log"


def logs_root_readme() -> Path:
    LOGS_ROOT.mkdir(parents=True, exist_ok=True)
    text = """LOGS LAYOUT
===========

shared/
  General run logs (run_YYYY-MM-DD.log, agent logs).

<town>/  (e.g. lexington/)
  Town-specific detailed logs (B.5 session enumeration, etc.).

DESCRIPTION.txt in each folder explains what logs belong there.
"""
    for sub in LOGS_ROOT.iterdir():
        if sub.is_dir() and sub.name != "shared":
            (sub / "DESCRIPTION.txt").write_text(
                f"Logs for {sub.name.replace('_', ' ').title()} pipeline runs.\n"
                "Includes B.5 session enumeration and town-scoped harvest detail.\n",
                encoding="utf-8",
            )
    shared = shared_log_dir() / "DESCRIPTION.txt"
    shared.write_text(
        "Shared pipeline logs for multi-town or non-town-specific runs.\n"
        "run_*.log — main orchestrator output.\n",
        encoding="utf-8",
    )
    path = LOGS_ROOT / "README.txt"
    path.write_text(text, encoding="utf-8")
    return path
