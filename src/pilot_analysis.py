"""Generate / refresh in-depth pilot run analysis markdown."""

from __future__ import annotations

import csv
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from config.settings import SETTINGS
from src.data_layout import (
    camp_links_csv,
    camp_sessions_csv,
    candidates_csv,
    deliverables_dir,
    pilot_analysis_md,
    rejected_candidates_csv,
    town_slug,
)
from src.geo_filter import is_out_of_state_url
from src.link_quality import drop_reason
from src.store import count_camp_links


def _host(url: str) -> str:
    h = urlparse(url).netloc.lower()
    return h[4:] if h.startswith("www.") else h


def _load_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _parse_harvest_done(log_paths: list[Path]) -> list[dict]:
    rows: list[dict] = []
    pat = re.compile(
        r"(\d{2}:\d{2}:\d{2}).*DONE\s+(\w+)\s+\| \+(\d+) new links "
        r"\| rules:(\d+) \| llm kept:(\d+) \| llm rejected:(\d+)"
    )
    src_pat = re.compile(
        r"(\d{2}:\d{2}:\d{2})  URL:\n\d{2}:\d{2}:\d{2}    (https?://\S+)"
    )
    for path in log_paths:
        if not path.exists():
            continue
        text = path.read_text(errors="replace")
        # pair DONE with preceding SOURCE URL (best effort)
        lines = text.splitlines()
        last_url = ""
        for i, line in enumerate(lines):
            if "  URL:" in line and i + 1 < len(lines):
                m = re.search(r"    (https?://\S+)", lines[i + 1])
                if m:
                    last_url = m.group(1)
            m = pat.search(line)
            if m:
                rows.append(
                    {
                        "time": m.group(1),
                        "kind": m.group(2),
                        "added": int(m.group(3)),
                        "rules": int(m.group(4)),
                        "llm_kept": int(m.group(5)),
                        "llm_rejected": int(m.group(6)),
                        "source_url": last_url,
                    }
                )
    return rows


def update_pilot_analysis(
    town: str = "Lexington",
    *,
    output_path: Path | str | None = None,
    run_status: str | None = None,
    stats: dict | None = None,
    notes: list[str] | None = None,
) -> Path:
    """Rewrite pilot analysis markdown from current data artifacts."""
    slug = town_slug(town)
    out = Path(output_path or pilot_analysis_md(town))

    candidates = _load_csv(candidates_csv())
    town_cands = [c for c in candidates if c.get("town") == town]
    links = _load_csv(camp_links_csv())
    town_links = [l for l in links if l.get("town_hint") == town]
    rejected = _load_csv(rejected_candidates_csv())

    crawled = sum(1 for c in town_cands if c.get("crawled") == "true")
    pending = [c for c in town_cands if c.get("crawled") != "true"]
    sessions_csv = camp_sessions_csv(town)
    deliverables = deliverables_dir(town)

    if run_status is None:
        if sessions_csv.exists() and crawled == len(town_cands):
            run_status = "COMPLETE"
        elif crawled == len(town_cands):
            run_status = "PHASE B COMPLETE — B.5 pending or in progress"
        else:
            run_status = "IN PROGRESS — Phase B"

    slop_reasons: Counter[str] = Counter()
    clean = 0
    oos_count = 0
    for row in town_links:
        reason = drop_reason(row.get("url", ""), row.get("link_text", ""))
        if reason:
            slop_reasons[reason] += 1
        else:
            clean += 1
        if is_out_of_state_url(row.get("url", ""), title=row.get("link_text", ""))[0]:
            oos_count += 1

    from src.data_layout import LOGS_ROOT, town_log_dir

    log_paths = sorted(LOGS_ROOT.glob("**/*.log"))
    town_log_dir(town)  # ensure town log folder exists
    done_events = _parse_harvest_done(log_paths)
    slowest = sorted(done_events, key=lambda x: x["rules"], reverse=True)[:12]
    geo_skips = 0
    llm_total = 0
    for p in log_paths:
        if p.exists():
            t = p.read_text(errors="replace")
            geo_skips += len(re.findall(r"SKIPPED\s+\[geo\]", t))
            llm_total += len(re.findall(r"LLM\s+(KEEP|REJECT)", t))

    by_class = Counter(c.get("classified_as") for c in town_cands)
    by_source = Counter(l.get("source_type") for l in town_links)
    top_hosts = Counter(_host(l["url"]) for l in town_links).most_common(20)

    session_count = 0
    if sessions_csv.exists():
        session_count = sum(1 for _ in open(sessions_csv)) - 1

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    extra_notes = notes or []

    lines = [
        f"# {town}, MA — Pilot Run Analysis",
        "",
        f"> **Last updated:** {now}  ",
        f"> **Run status:** `{run_status}`  ",
        f"> **Command:** `./venv/bin/python -m src.run --no-dry-run --phase all --town {town}`  ",
        "",
        "---",
        "",
        "## Executive summary",
        "",
        f"This document tracks the **first full pipeline pilot** for {town}: Phase A (Serper search) → "
        "Phase B (crawl + Ollama link filter) → Phase B.5 (session enumeration) → deliverables bundle. "
        "Phase C (niche STEM/sports keywords) is **disabled** (`phase_all_includes_c: false`).",
        "",
        "**Headline verdict:** The pipeline **works end-to-end** and produces a large, usable camp link "
        "catalog plus (when B.5 completes) registrable session rows. It is **not production-optimized** — "
        "runtime is dominated by sequential Ollama calls and undifferentiated deep crawls on low-value seeds.",
        "",
        "---",
        "",
        "## Live metrics snapshot",
        "",
        "| Metric | Value |",
        "|--------|------:|",
        f"| Phase A candidates (unique URLs) | {len(town_cands)} |",
        f"| Phase A search rejects | {len(rejected)} |",
        f"| Phase B sources crawled | {crawled} / {len(town_cands)} |",
        f"| Phase B sources pending | {len(pending)} |",
        f"| Raw camp links (`camp_links.csv`) | {len(town_links)} |",
        f"| Quality-filtered links (est.) | {clean} |",
        f"| Slop / filtered links (est.) | {len(town_links) - clean} |",
        f"| Out-of-state URLs in raw links | {oos_count} |",
        f"| Unique link hosts | {len({_host(l['url']) for l in town_links})} |",
        f"| B.5 sessions enumerated | {session_count or '—'} |",
        f"| Geo-skipped seeds (log) | {geo_skips} |",
        f"| LLM keep/reject decisions (log) | {llm_total} |",
    ]
    if stats:
        for k, v in stats.items():
            lines.append(f"| {k} | {v} |")

    lines.extend(["", "---", "", "## Run timeline", ""])
    lines.extend(
        [
            "| Time (local) | Event |",
            "|--------------|-------|",
            "| 6:30 PM | First attempt — DuckDuckGo, Phase A failed (429) |",
            "| 6:42 PM | Restart with Serper API |",
            "| 6:43 PM | **Phase A complete** — 53 queries, 81 unique candidates, 134 rejected |",
            "| 6:43 PM | Phase B harvest begins |",
            "| 7:28 PM | **Pause #1** — add geo filter, LLM cap (30/source), resume banner |",
            "| 8:00 PM | **Pause #2 / resume** after user stop |",
            "| 9:57 PM | **Pause #3 / resume** — expanded geo filter (Pittsburgh, national indexes) |",
            "| ~2:54 AM | Middlesex CC crawl begins (`unknown` profile, 300-page cap) |",
            "| *(manual)* | **Middlesex CC crawl killed** — marked crawled without completion; "
            "3+ hours on non-camp college pages |",
            "| — | B.5 + deliverables: pending until run completes |",
            "",
        ]
    )

    lines.extend(["---", "", "## Phase A — Search discovery", "", "### What worked", ""])
    lines.extend(
        [
            "- **53 Serper queries** in ~1 minute; cost ~$0.05.",
            "- Found **LexRec, Lexplorations, Lexington.gov rec**, YMCA Boston, MetroWest YMCA, parent guides.",
            "- **134 bad hits rejected** at ingest (aggregators, after-school, some OOS).",
            "- Search cache (`cache/seen_searches.json`) makes re-runs instant.",
            "",
            "### Candidate breakdown",
            "",
            "| classified_as | Count | Role in Phase B |",
            "|---------------|------:|-----------------|",
        ]
    )
    for k, v in by_class.most_common():
        lines.append(f"| {k} | {v} | see below |")
    lines.extend(
        [
            "",
            "| Type | Behavior | Quality |",
            "|------|----------|---------|",
            "| `guide` (12) | Single-page outbound link mine | **High ROI** — BostonCentral, Community Kangaroo, BostonTechMom |",
            "| `directory` (36) | Deep crawl | **Mixed** — LexCE/LexRec great; national indexes wasteful |",
            "| `unknown` (30) | Deep crawl, 300 pages, 8s delay | **Low ROI** — college sites, national blogs, wrong-state JCCs |",
            "| `camp` (3) | Focused crawl | **High** — direct camp hosts |",
            "",
            "### Phase A problems",
            "",
            "- Generic queries (`JCC summer camp Lexington, MA`) returned **Pittsburgh, New Haven CT, Virginia, Milwaukee** JCCs.",
            "- **No MA signal required** in title/snippet for `unknown` keeps.",
            "- Regional keywords (`Boston area`, `MetroWest`, `Middlesex county`) intentionally widen net — good for "
            "statewide dedupe, confusing for town-only view.",
            "- **Empow Studios** not found — not on guides, Phase C off, empow.me reportedly closed.",
            "",
        ]
    )

    lines.extend(["---", "", "## Phase B — Harvest & link discovery", "", "### What worked", ""])
    lines.extend(
        [
            "- **Guide referrals** (~38 links) fast and high-quality: Capitol Debate, Mass Audubon, NEOC, iD Tech, etc.",
            "- **Lexplorations / LexCE** — largest single yield (~59+29 links from WooCommerce catalog).",
            "- **Lexington.gov / LexRec** — municipal rec pages captured.",
            "- **Rule-based high-confidence URLs** skip LLM (`program_details.aspx`, `/summer-camp`, myrec, etc.).",
            "- **Verdict cache** (`cache/camp_verdicts.json`) avoids repeat Ollama on same URL.",
            "- **LLM cap** (30 calls/source) prevented unbounded runs on 200+ link catalogs.",
            "- **`link_quality` + geo filter** (post-hoc) — slop dropped at save and in deliverables.",
            "- **Resume/checkpoints** — `crawled=true` per source; safe pause/resume.",
            "",
            "### Link output breakdown",
            "",
            "| source_type | Count |",
            "|-------------|------:|",
        ]
    )
    for k, v in by_source.most_common():
        lines.append(f"| {k} | {v} |")

    lines.extend(
        [
            "",
            "### Slowest sources (by rule-pass link count before LLM)",
            "",
            "These dominated wall-clock time:",
            "",
            "| Time | rules | +links | llm kept | Source (approx) |",
            "|------|------:|-------:|---------:|-----------------|",
        ]
    )
    for ev in slowest:
        url = ev.get("source_url", "")[:55]
        lines.append(
            f"| {ev['time']} | {ev['rules']} | {ev['added']} | {ev['llm_kept']} | `{url}` |"
        )

    lines.extend(
        [
            "",
            "### Phase B problems (critical)",
            "",
            "1. **Sequential Ollama (~10–15 sec/call)** — main bottleneck; ~2,370+ LLM decisions logged across runs.",
            "2. **One crawl profile for all non-guides** — `max_pages=300`, `delay=8s`, no focused mode for `unknown`.",
            "3. **Middlesex CC** — seed was `/community/summeryouth.html` but crawler walked entire college site "
            "(corporate, adult ed, DEI) for **3+ hours** before manual kill.",
            "4. **YMCA Central MA (`ymcaofcm.org`)** — crawled image URLs (`wp-content/uploads/*.jpg`); 2535 rule-pass links.",
            "5. **Out-of-state seeds crawled before geo fix** — Pittsburgh JCC (~50 links), New Haven JCC (~15), Virginia JCC (~15).",
            "6. **National indexes crawled** — `jcca.org`, `acacamps.org`, `ymca.org` (trade association, not registrable).",
            "7. **`town_hint=Lexington` ≠ camp location** — ~70% of link hosts have no \"lexington\" in domain (regional by design).",
            "8. **Guide hosts not re-enumerated in B.5** unless same host in `candidates.csv`.",
            "",
            "### Top slop reasons (quality filter)",
            "",
            "| Reason | Count |",
            "|--------|------:|",
        ]
    )
    for reason, n in slop_reasons.most_common(12):
        lines.append(f"| {reason} | {n} |")

    lines.extend(["", "### Top link hosts (raw)", "", "| Host | Links |", "|------|------:|"])
    for h, n in top_hosts:
        lines.append(f"| {h} | {n} |")

    lines.extend(["", "---", "", "## Phase B.5 — Session enumeration", ""])
    if session_count:
        lines.extend(
            [
                f"- **{session_count} sessions** written to `data/{slug}_camp_sessions.csv`.",
                "- See `data/lexington_deliverables/` for organized outputs.",
                "",
            ]
        )
    else:
        lines.extend(
            [
                "**Not complete yet.** When finished, expect:",
                "",
                "- `data/lexington_camp_sessions.csv` + `.txt`",
                "- Platform adapters: WooCommerce (Lexplorations), MyRec/WebTrac (LexRec), Sawyer, etc.",
                "- `adapter_llm` fallback for unknown marketing sites (slow).",
                "- Focus filter drops adult/off-season programs.",
                "",
            ]
        )

    lines.extend(["---", "", "## Configuration in effect", "", "```python"])
    for k in (
        "search_provider",
        "delay_seconds",
        "max_pages_per_source",
        "max_links_per_domain_per_harvest",
        "ollama_validate_max_calls_per_source",
        "phase_all_includes_c",
        "geo_filter_crawl",
        "program_focus",
    ):
        lines.append(f"{k}: {SETTINGS.get(k)!r}")
    lines.extend(["```", ""])

    lines.extend(["---", "", "## Pending sources (Phase B)", ""])
    if pending:
        for c in pending:
            lines.append(
                f"- [{c.get('classified_as')}] `{c.get('url', '')}` — {c.get('title', '')[:60]}"
            )
    else:
        lines.append("- None — Phase B complete.")

    lines.extend(["", "---", "", "## Fixes applied mid-pilot", ""])
    lines.extend(
        [
            "| Change | When | Impact |",
            "|--------|------|--------|",
            "| `ollama_validate_max_calls_per_source: 30` | Pause #1 | Capped LLM on fat catalogs |",
            "| `geo_filter_crawl` + KY/VA/MI markers | Pause #1 | Skip wrong-state seeds |",
            "| `phase_all_includes_c: false` | Before run | Skip 281 niche queries/town |",
            "| `link_quality` save-time gate | Before run | Block admin/PDF/national indexes |",
            "| Expanded geo: Pittsburgh, New Haven, national YMCA/JCC/ACA | Pause #3 | Skip before crawl |",
            "| Middlesex CC manual skip | This session | Saved hours of college-site crawl |",
            "",
        ]
    )

    lines.extend(["---", "", "## Recommended fixes (next iteration)", "", "### P0 — Must do before multi-town rollout", ""])
    lines.extend(
        [
            "1. **`--preferred-only` harvest flag** — crawl ~25 `preferred=true` seeds; skip `unknown` national noise.",
            "2. **Tiered crawl profiles** — focused mode + 10-page cap for `unknown`; keep 300 only for rec/community-ed.",
            "3. **Parallel Ollama** in `filter_rows_with_llm` (3–4 concurrent with semaphore).",
            "4. **Phase A: require MA signal** in title/snippet for ambiguous results.",
            "5. **Skip image/media URLs** during crawl (`wp-content/uploads`, `.jpg`, `.pdf`).",
            "6. **Stop crawl on catalog detection** for all source types, not just focused camp hosts.",
            "",
            "### P1 — High value",
            "",
            "7. **`--no-llm-validate` mode** for statewide link harvest; LLM only in B.5.",
            "8. **Global host dedupe for B.5** — enumerate once per provider, not per town.",
            "9. **B.5 from `camp_links` hosts** — include guide-discovered providers.",
            "10. **Reduce `delay_seconds`** 8 → 2–3 for non-preferred crawls.",
            "",
            "### P2 — Scale MA",
            "",
            "11. Phase A all towns → Phase B preferred-only → B.5 on fingerprinted platforms only.",
            "12. Split pipeline: fast link discovery vs slow session enumeration.",
            "13. Re-enable narrow Phase C (STEM) as optional `--phase c` per county.",
            "",
        ]
    )

    lines.extend(["---", "", "## Time & cost estimates (this pilot)", "", "| Phase | Actual / projected |", "|-------|-------------------|"])
    lines.extend(
        [
            "| Phase A | ~1 min, ~$0.05 |",
            "| Phase B | **~8–12 hours** wall-clock (with pauses, Ollama, Middlesex) |",
            "| Phase B.5 | ~45–90 min (projected) |",
            "| **Total pilot** | **~10–14 hours** for one town (unoptimized) |",
            "| Optimized target | **~2–3 hours/town** with P0 fixes |",
            "",
        ]
    )

    if extra_notes:
        lines.extend(["---", "", "## Session notes", ""])
        for n in extra_notes:
            lines.append(f"- {n}")
        lines.append("")

    lines.extend(
        [
            "---",
            "",
            "## Artifacts",
            "",
            "| File | Description |",
            "|------|-------------|",
            "| `data/candidates.csv` / `.txt` | Phase A seeds |",
            "| `data/camp_links.csv` / `.txt` | Phase B output (raw + filtered view) |",
            "| `data/rejected_candidates.csv` | Phase A rejects |",
            "| `data/harvest_activity_*.csv` | Per-link LLM/save audit |",
            "| `logs/full_run_lexington_20260609_1842.log` | First run (stopped 7:28 PM) |",
            "| `logs/full_run_lexington_resume_20260609.log` | Resume runs |",
            "| `data/lexington_deliverables/` | Final bundle (after B.5) |",
            "| `cache/camp_verdicts.json` | LLM URL verdict cache |",
            "",
            "---",
            "",
            "*This file auto-regenerates at end of each `--town` pipeline run via `src/pilot_analysis.py`.*",
            "",
        ]
    )

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    return out
