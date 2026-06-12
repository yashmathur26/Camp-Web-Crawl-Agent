"""Post-run deliverable bundle: organized CSVs + in-depth TXT reports."""

from __future__ import annotations

import csv
import re
import shutil
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from config.settings import SETTINGS, STATE
from src.camp_outputs import host_of
from src.csv_mirror import write_csv_bundle
from src.data_layout import (
    camp_links_csv,
    camp_sessions_csv,
    deliverables_dir,
    refresh_town_index,
    town_phase_dir,
    town_slug,
)
from src.link_quality import drop_reason
from src.session_quality import (
    enrollability_score,
    split_parent_verdicts,
    split_sessions,
    write_parent_verify_csvs,
    write_quality_csvs,
)
from src.sessions import SESSION_CSV_COLUMNS, host_of as session_host_of

CAMP_LINKS_COLUMNS = [
    "url",
    "state",
    "town_hint",
    "source_type",
    "found_via",
    "found_on_page",
    "link_text",
    "status",
    "discovered_at",
    "provider_host",
]

SESSION_CSV_ORGANIZED = [
    "provider_host",
    *SESSION_CSV_COLUMNS,
    "parent_verdict",
    "label",
]

REVIEW_QUEUE_COLUMNS = [*SESSION_CSV_ORGANIZED, "held_reason"]


def _has(value: str) -> bool:
    return bool((value or "").strip())


# --------------------------------------------------------------------------- #
# Task 4.2 — publish gates
# --------------------------------------------------------------------------- #
_MONTHS = {
    m.lower(): i
    for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"],
        start=1,
    )
}
_NAMED_DATE_RE = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})"
    r"(?:\s*[-–]\s*(\d{1,2}))?(?:\s*,?\s*(\d{4}))?",
    re.I,
)
_NUMERIC_DATE_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b")
_ISO_DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")

AUDIENCE_KEYWORD_RE = re.compile(
    r"(?i)(adult|senior|18\+|21\+|parent night|bird walk)"
)


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def parse_date_range(text: str, season_year: int) -> tuple[date, date] | None:
    """(min, max) of every date found in `text`; None when nothing parses.
    Year-less dates assume the season year."""
    found: list[date] = []
    for m in _ISO_DATE_RE.finditer(text or ""):
        d = _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if d:
            found.append(d)
    for m in _NAMED_DATE_RE.finditer(text or ""):
        year = int(m.group(4)) if m.group(4) else season_year
        month = _MONTHS[m.group(1).lower()]
        d = _safe_date(year, month, int(m.group(2)))
        if d:
            found.append(d)
        if m.group(3):  # same-month day range, e.g. "July 7-11"
            d2 = _safe_date(year, month, int(m.group(3)))
            if d2:
                found.append(d2)
    for m in _NUMERIC_DATE_RE.finditer(text or ""):
        mo, day = int(m.group(1)), int(m.group(2))
        if not (1 <= mo <= 12):
            continue
        year = season_year
        if m.group(3):
            year = int(m.group(3))
            if year < 100:
                year += 2000
        d = _safe_date(year, mo, day)
        if d:
            found.append(d)
    if not found:
        return None
    return min(found), max(found)


def _date_sanity_ok(row: dict, season_year: int) -> bool:
    """Session rows need a parseable range intersecting May 1 – Sep 30 of the
    season year. Program rows are exempt (checked by caller)."""
    rng = parse_date_range(row.get("dates", ""), season_year)
    if rng is None:
        return False
    season_start, season_end = date(season_year, 5, 1), date(season_year, 9, 30)
    start, end = rng
    return start <= season_end and end >= season_start


def apply_publish_gates(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split rows into (published, held). Held rows carry held_reason and a
    label column is set on published brochure_only rows. Nothing is deleted."""
    require_verify = bool(SETTINGS.get("publish_require_verify", True))
    allowed = set(SETTINGS.get("publish_allowed_verdicts", ["parent_ready", "brochure_only"]))
    season_year = int(SETTINGS.get("season_year", 2026))

    published: list[dict] = []
    held: list[dict] = []
    for row in rows:
        verdict = (row.get("parent_verdict") or "").strip()
        granularity = (row.get("granularity") or "session").strip() or "session"

        if require_verify and verdict not in allowed:
            held.append(
                {**row, "held_reason": f"verdict:{verdict}" if verdict else "unverified"}
            )
            continue
        if granularity == "session" and not _date_sanity_ok(row, season_year):
            held.append({**row, "held_reason": "date_sanity"})
            continue
        if AUDIENCE_KEYWORD_RE.search(row.get("name", "")) and verdict != "parent_ready":
            held.append({**row, "held_reason": "audience_keyword"})
            continue
        published.append(
            {**row, "label": "brochure_only" if verdict == "brochure_only" else ""}
        )
    return published, held


def write_deliverables(
    town: str,
    enumeration_results: list[dict],
    *,
    camp_links_path: Path | str | None = None,
    output_root: Path | str | None = None,
) -> Path:
    """Write data/<town>/deliverables/ with CSVs and report TXTs. Returns folder path."""
    _ = output_root
    slug = town_slug(town)
    out_dir = deliverables_dir(town)
    camp_links_path = camp_links_path or camp_links_csv()

    # --- Sessions CSV (organized) ---
    session_rows: list[dict] = []
    for res in enumeration_results:
        h = session_host_of(res.get("url", ""))
        for s in res.get("sessions", []):
            session_rows.append(
                {
                    "provider_host": h,
                    **{c: s.get(c, "") for c in SESSION_CSV_COLUMNS},
                    "parent_verdict": s.get("parent_verdict", ""),
                }
            )
    session_rows.sort(
        key=lambda r: (
            r.get("provider_host", ""),
            r.get("name", "").lower(),
            r.get("register_url", ""),
        )
    )

    # Task 4.2: only verified rows reach the parent-facing catalog; the rest are
    # held (never deleted) in phase_p/review_queue.csv with a held_reason.
    published_rows, held_rows = apply_publish_gates(session_rows)
    review_queue_csv = town_phase_dir(town, "phase_p") / "review_queue.csv"
    write_csv_bundle(
        review_queue_csv,
        held_rows,
        REVIEW_QUEUE_COLUMNS,
        title=f"{town} — rows held back from the parent catalog",
        description="Held by publish gates (verdict/date/audience), not deleted.",
    )

    sessions_csv = out_dir / "camp_sessions_organized.csv"
    write_csv_bundle(
        sessions_csv,
        published_rows,
        SESSION_CSV_ORGANIZED,
        title=f"{town} — organized camp sessions (deliverable)",
        description="Verified sessions sorted by provider and camp name.",
    )

    # --- Camp links clean CSV ---
    raw_links: list[dict] = []
    if Path(camp_links_path).exists():
        with open(camp_links_path, encoding="utf-8", newline="") as f:
            raw_links = list(csv.DictReader(f))

    clean_links: list[dict] = []
    slop_links: list[tuple[str, dict]] = []
    for row in raw_links:
        if row.get("town_hint") and row.get("town_hint") != town:
            continue
        reason = drop_reason(row.get("url", ""), row.get("link_text", ""))
        enriched = {**row, "provider_host": host_of(row.get("url", ""))}
        if reason:
            slop_links.append((reason, enriched))
        else:
            clean_links.append(enriched)

    clean_links.sort(key=lambda r: (r.get("provider_host", ""), r.get("url", "")))
    links_csv = out_dir / "camp_links_clean.csv"
    write_csv_bundle(
        links_csv,
        clean_links,
        CAMP_LINKS_COLUMNS,
        title=f"{town} — quality-filtered harvest links",
        description="Phase B links for this town after slop filter.",
    )

    # --- Quality tier CSVs (Phase Q + P in town folders) ---
    write_quality_csvs(town, session_rows)
    write_parent_verify_csvs(town, session_rows)
    enroll_score, tier_counts = enrollability_score(session_rows)
    parent_counts = split_parent_verdicts(session_rows)

    # --- In-depth catalog TXT ---
    catalog_path = out_dir / "CAMPS_CATALOG.txt"
    catalog_path.write_text(
        _build_catalog_txt(town, published_rows, clean_links, enumeration_results, tier_counts),
        encoding="utf-8",
    )

    # --- Quality report TXT ---
    quality_path = out_dir / "QUALITY_REPORT.txt"
    quality_path.write_text(
        _build_quality_report(
            town,
            session_rows,
            raw_links,
            clean_links,
            slop_links,
            enumeration_results,
            enroll_score=enroll_score,
            tier_counts=tier_counts,
        ),
        encoding="utf-8",
    )

    # --- Index README ---
    readme = out_dir / "README.txt"
    readme.write_text(
        _build_readme(
            town, out_dir, len(session_rows), len(clean_links), len(raw_links),
            enroll_score=enroll_score, tier_counts=tier_counts,
            parent_counts={k: len(v) for k, v in parent_counts.items()},
        ),
        encoding="utf-8",
    )

    src_sessions_txt = camp_sessions_csv(town).with_suffix(".txt")
    if src_sessions_txt.exists():
        shutil.copy2(src_sessions_txt, out_dir / "camp_sessions_raw.txt")

    refresh_town_index(town)
    return out_dir


def _build_readme(
    town: str,
    out_dir: Path,
    sessions: int,
    clean_links: int,
    raw_links: int,
    *,
    enroll_score: int = 0,
    tier_counts: dict | None = None,
    parent_counts: dict | None = None,
) -> str:
    tiers = tier_counts or {}
    parent = parent_counts or {}
    return f"""╔══════════════════════════════════════════════════════════════════════╗
║  {town.upper()} CAMP DISCOVERY — DELIVERABLES
╚══════════════════════════════════════════════════════════════════════╝

Generated: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}

FILES IN THIS FOLDER
────────────────────
  camp_sessions_organized.csv (+ .txt)
      Organized session catalog (sorted by provider → camp name).

  camp_links_clean.csv (+ .txt)
      Quality-filtered discovery links for this town.
      {clean_links} links (of {raw_links} raw in shared/phase_b/camp_links.csv).

  See also town phase folders:
    ../phase_q/     registrable.csv, needs_trail.csv, rejected.csv
    ../phase_p/     parent_ready.csv, brochure_only.csv, wrong_audience.csv
    ../phase_b5/    camp_sessions.csv

  CAMPS_CATALOG.txt
      Full human-readable walkthrough of every session and provider.

  QUALITY_REPORT.txt
      Coverage stats, data completeness, gaps, and trust assessment.

  camp_sessions_raw.txt  (if present)
      Copy of the B.5 enumeration readable log.

SUMMARY
───────
  Registrable sessions enumerated: {sessions}
  Enrollability score:             {enroll_score}/100
  Registrable tier:                {tiers.get('registrable', 0)}
  Needs trail:                     {tiers.get('needs_trail', 0)}
  Rejected:                        {tiers.get('rejected', 0)}
  Parent-ready (Phase P):          {parent.get('parent_ready', 0)}
  Brochure-only:                   {parent.get('brochure_only', 0)}
  Clean harvest links:             {clean_links}

Start with CAMPS_CATALOG.txt for browsing, camp_sessions_organized.csv for data.
"""


def _build_catalog_txt(
    town: str,
    sessions: list[dict],
    clean_links: list[dict],
    results: list[dict],
    tier_counts: dict | None = None,
) -> str:
    split = split_sessions(sessions)
    counts = tier_counts or {k: len(v) for k, v in split.items()}
    registrable_sessions = split["registrable"]

    lines = [
        "╔══════════════════════════════════════════════════════════════════════╗",
        f"║  {town.upper()}, {STATE} — CAMP SESSION CATALOG",
        "╚══════════════════════════════════════════════════════════════════════╝",
        "",
        f"  Sessions: {len(sessions)}   Registrable: {counts.get('registrable', 0)}   "
        f"Providers checked: {len(results)}",
        "",
        "═" * 74,
        "  SECTION 1 — REGISTRABLE SESSIONS (Phase Q)",
        "═" * 74,
        "",
    ]

    if not registrable_sessions:
        lines.append("  No registrable sessions in catalog.\n")
    else:
        by_reg: dict[str, list[dict]] = defaultdict(list)
        for s in registrable_sessions:
            by_reg[s.get("provider_host", session_host_of(s.get("source_url", "")))].append(s)
        for host in sorted(by_reg.keys(), key=lambda h: (-len(by_reg[h]), h)):
            group = by_reg[host]
            plat = group[0].get("platform", "?")
            source = group[0].get("source_url", "")
            lines.extend(
                [
                    f"  ▶ {host.upper()}",
                    f"    Platform: {plat}",
                    f"    Seed URL: {source}",
                    f"    Sessions: {len(group)}",
                    "    " + "─" * 68,
                ]
            )
            for i, s in enumerate(group, 1):
                marker = (
                    "  [PROVIDER PAGE]"
                    if (s.get("granularity") or "") == "program"
                    else ""
                )
                lines.append(f"    [{i}] {s.get('name', 'Unnamed')}{marker}")
                if _has(s.get("dates")):
                    lines.append(f"        Dates .... {s['dates']}")
                if _has(s.get("ages")):
                    lines.append(f"        Ages ..... {s['ages']}")
                if _has(s.get("price")):
                    lines.append(f"        Price .... {s['price']}")
                lines.append(f"        Register . {s.get('register_url', '')}")
                if s.get("kind") == "portal":
                    lines.append("        Note ..... portal/listing page (not single session)")
                lines.append("")

    lines.extend(
        [
            "",
            "═" * 74,
            "  SECTION 2 — PROVIDERS WITH ZERO SESSIONS (gaps)",
            "═" * 74,
            "",
        ]
    )
    empty = [r for r in results if not r.get("sessions")]
    if not empty:
        lines.append("  None — every checked provider returned at least one session.\n")
    else:
        for r in sorted(empty, key=lambda x: session_host_of(x.get("url", ""))):
            dropped = len(r.get("dropped", []))
            lines.append(f"  ✗ {session_host_of(r.get('url', ''))}")
            lines.append(f"    Platform: {r.get('platform', '?')}   Dropped off-focus: {dropped}")
            lines.append(f"    Seed: {r.get('url', '')}")
            lines.append("")

    lines.extend(
        [
            "",
            "═" * 74,
            "  SECTION 3 — DISCOVERY LINKS (quality-filtered harvest)",
            "═" * 74,
            "",
            f"  {len(clean_links)} links from Phase B (guide referrals + directory crawl)",
            "",
        ]
    )
    links_by_host: dict[str, list[dict]] = defaultdict(list)
    for row in clean_links:
        links_by_host[row.get("provider_host", "?")].append(row)

    for host in sorted(links_by_host.keys(), key=lambda h: (-len(links_by_host[h]), h))[:40]:
        group = links_by_host[host]
        lines.append(f"  • {host} ({len(group)} links)")
        for row in group[:5]:
            title = (row.get("link_text") or "").strip() or row.get("url", "")
            lines.append(f"      - {title[:60]}")
            lines.append(f"        {row.get('url', '')[:70]}")
        if len(group) > 5:
            lines.append(f"      ... +{len(group) - 5} more")
        lines.append("")

    if len(links_by_host) > 40:
        lines.append(f"  ... +{len(links_by_host) - 40} more providers in CSV\n")

    return "\n".join(lines).rstrip() + "\n"


def _build_quality_report(
    town: str,
    sessions: list[dict],
    raw_links: list[dict],
    clean_links: list[dict],
    slop_links: list[tuple[str, dict]],
    results: list[dict],
    *,
    enroll_score: int = 0,
    tier_counts: dict | None = None,
) -> str:
    n_sess = len(sessions)
    tiers = tier_counts or split_sessions(sessions)
    if not tier_counts:
        tier_counts = {k: len(v) for k, v in tiers.items()}

    with_dates = sum(1 for s in sessions if _has(s.get("dates")))
    with_ages = sum(1 for s in sessions if _has(s.get("ages")))
    with_price = sum(1 for s in sessions if _has(s.get("price")))
    with_reg = tier_counts.get("registrable", 0)
    portals = sum(1 for s in sessions if s.get("kind") == "portal")
    program_fallback_rows = sum(
        1 for s in sessions if (s.get("granularity") or "") == "program"
    )

    plat_counts = Counter(s.get("platform", "?") for s in sessions)
    providers_with = len({s.get("provider_host") for s in sessions})
    providers_checked = len(results)
    providers_empty = providers_checked - sum(1 for r in results if r.get("sessions"))
    total_dropped = sum(len(r.get("dropped", [])) for r in results)

    slop_by_reason = Counter(r for r, _ in slop_links)
    source_types = Counter(r.get("source_type", "?") for r in clean_links)

    score = enroll_score or (round(100 * with_reg / n_sess) if n_sess else 0)
    score_notes: list[str] = []
    if n_sess == 0:
        score = 0
        score_notes.append("No sessions enumerated — run incomplete or all providers blocked.")
    else:
        if with_reg < n_sess * 0.5:
            score_notes.append(f"Only {with_reg}/{n_sess} sessions are registrable (enrollability tier).")
        if providers_empty > providers_with:
            score_notes.append(
                f"{providers_empty} providers returned 0 camps vs {providers_with} with camps."
            )
        if tier_counts.get("rejected", 0) > 0:
            score_notes.append(f"{tier_counts['rejected']} sessions rejected (geo/hub/junk URLs).")

    score = max(0, min(100, score))
    if score >= 80:
        grade = "A — Strong"
    elif score >= 65:
        grade = "B — Good"
    elif score >= 50:
        grade = "C — Usable with gaps"
    else:
        grade = "D — Incomplete"

    lines = [
        "╔══════════════════════════════════════════════════════════════════════╗",
        f"║  {town.upper()} — DATA QUALITY REPORT",
        "╚══════════════════════════════════════════════════════════════════════╝",
        "",
        f"  Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "┌─ OVERALL ASSESSMENT ──────────────────────────────────────────────────┐",
        f"│  Enrollability score: {score}/100   Grade: {grade:<22}│",
        "└───────────────────────────────────────────────────────────────────────┘",
        "",
        f"  Registrable: {tier_counts.get('registrable', 0)}  "
        f"Needs trail: {tier_counts.get('needs_trail', 0)}  "
        f"Rejected: {tier_counts.get('rejected', 0)}",
        "",
    ]
    for note in score_notes:
        lines.append(f"  • {note}")
    if not score_notes:
        lines.append("  • Good session coverage with register URLs and provider diversity.")
    lines.append("")

    lines.extend(
        [
            "┌─ SESSION DATA COMPLETENESS (Phase B.5) ───────────────────────────────┐",
            f"│  Total sessions .............. {n_sess:>5}                              │",
            f"│  With register URL ........... {with_reg:>5}  ({100*with_reg/n_sess if n_sess else 0:>5.1f}%)                   │",
            f"│  With dates .................. {with_dates:>5}  ({100*with_dates/n_sess if n_sess else 0:>5.1f}%)                   │",
            f"│  With ages ................... {with_ages:>5}  ({100*with_ages/n_sess if n_sess else 0:>5.1f}%)                   │",
            f"│  With price .................. {with_price:>5}  ({100*with_price/n_sess if n_sess else 0:>5.1f}%)                   │",
            f"│  Portal/listing pages ........ {portals:>5}                              │",
            "└───────────────────────────────────────────────────────────────────────┘",
            "",
            f"  program_fallback_rows: {program_fallback_rows}",
            "",
            "┌─ PROVIDER COVERAGE ───────────────────────────────────────────────────┐",
            f"│  Providers checked ........... {providers_checked:>5}                              │",
            f"│  Providers with sessions ..... {providers_with:>5}                              │",
            f"│  Providers with 0 sessions ... {providers_empty:>5}                              │",
            f"│  Sessions dropped (off-focus)  {total_dropped:>5}                              │",
            "└───────────────────────────────────────────────────────────────────────┘",
            "",
            "  Platform breakdown (sessions):",
        ]
    )
    for plat, n in plat_counts.most_common():
        lines.append(f"    {plat:<20} {n:>4}")
    lines.append("")

    lines.extend(
        [
            "┌─ HARVEST LINK QUALITY (Phase B) ──────────────────────────────────────┐",
            f"│  Raw links in camp_links.csv . {len(raw_links):>5}                              │",
            f"│  Quality-filtered (clean) .... {len(clean_links):>5}                              │",
            f"│  Filtered as slop ............. {len(slop_links):>5}                              │",
            "└───────────────────────────────────────────────────────────────────────┘",
            "",
            "  Clean links by source type:",
        ]
    )
    for st, n in source_types.most_common():
        lines.append(f"    {st:<18} {n:>4}")
    lines.append("")
    lines.append("  Top slop reasons (filtered out):")
    for reason, n in slop_by_reason.most_common(10):
        lines.append(f"    [{n:>3}×] {reason}")
    lines.append("")

    lines.extend(
        [
            "┌─ KNOWN LIMITATIONS ───────────────────────────────────────────────────┐",
            "│  • Guide-discovered camps (BostonCentral etc.) are in camp_links but │",
            "│    not re-enumerated unless the host also appears in candidates.csv  │",
            "│  • JS/bot-blocked sites may show 0 sessions (Robo Hub, some JCCs)    │",
            "│  • LLM harvest kept some noise before quality filters were added     │",
            "│  • Dates/ages often missing until Firecrawl detail pass (future)     │",
            "└───────────────────────────────────────────────────────────────────────┘",
            "",
            "┌─ TOP PROVIDERS BY SESSION COUNT ──────────────────────────────────────┐",
        ]
    )
    by_prov = Counter(s.get("provider_host") for s in sessions)
    for host, n in by_prov.most_common(15):
        lines.append(f"  {host:<40} {n:>4} sessions")
    if not by_prov:
        lines.append("  (none yet)")
    lines.append("")
    lines.append("┌─ PROVIDERS WITH ZERO SESSIONS (action needed) ────────────────────────┐")
    for r in sorted(
        [x for x in results if not x.get("sessions")],
        key=lambda x: session_host_of(x.get("url", "")),
    )[:20]:
        lines.append(f"  {session_host_of(r.get('url', '')):<40} [{r.get('platform', '?')}]")
    if providers_empty > 20:
        lines.append(f"  ... +{providers_empty - 20} more")
    lines.append("")

    return "\n".join(lines).rstrip() + "\n"
