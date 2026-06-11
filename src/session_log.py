"""Detailed plain-English logging for Phase B.5 camp-session enumeration.

Writes to the 'session' logger (console + optional dedicated log file).
Every message explains what the scraper is doing and why, in simple terms.
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path

SEP = "=" * 72
THIN = "-" * 72

_log = logging.getLogger("session")
_initialized = False

# Plain-English descriptions of registration platforms parents encounter.
PLATFORM_EXPLAIN: dict[str, str] = {
    "webtrac": (
        "This site uses WebTrac (Vermont Systems). Camps are listed as individual "
        "weeks/sessions — each has its own registration link (iteminfo?FMID=...)."
    ),
    "woocommerce": (
        "This site uses a WordPress/WooCommerce shop. Each camp is a product page "
        "under /class/ or /product/. We walk category pages and pagination to find all of them."
    ),
    "catalog_grid": (
        "This site lists many camps on a course grid (e.g. iD Tech /courses). "
        "We collect each course URL from the catalog page instead of using LLM prose."
    ),
    "veracross": (
        "Registration runs through Veracross (common at private schools). "
        "We collect sport/summer program links from their ProgramRegistration portal."
    ),
    "discovery": (
        "Broad camp-like link scan: any URL/label that looks like summer camp, "
        "then each page is verified with rules + AI before saving."
    ),
    "myrec": (
        "This site uses MyRec.com (municipal recreation). Each program has a "
        "program_details.aspx?ProgramID= link on the activities listing."
    ),
    "sawyer": (
        "Registration runs through Sawyer (hisawyer.com). We try to pull individual "
        "activity links from their schedule page."
    ),
    "campbrain": (
        "Registration runs through CampBrain. We surface the portal link and any "
        "per-camp links we can see on the page."
    ),
    "arbitersports": (
        "Registration runs through ArbiterSports. We collect program/activity links "
        "from their catalog."
    ),
    "llm": (
        "No structured catalog found — we read the page text with AI (Ollama) to "
        "list camps described in prose."
    ),
    "custom": (
        "Custom or unknown website builder. We try AI extraction if nothing else works."
    ),
}

FOCUS_REASON_PLAIN: dict[str, str] = {
    "adult": "Looks like an adult or senior program — not in our youth-summer focus.",
    "non-program": "Not a registrable camp (membership, donation, lunch, league, etc.).",
    "adult-fitness": "Adult fitness class (yoga, cycling, boot camp) — skipping.",
    "off-season": "Fall/winter/spring program with no summer offering — skipping.",
    "no-signal": "Name doesn't clearly say camp/clinic/summer/youth — sent to AI for a second look.",
    "youth-summer": "Matches youth summer camp/clinic/workshop — keeping.",
    "camp-catalog": "From a camp-only registration catalog — keeping.",
    "empty": "No usable name or text — skipping.",
}


def init(log_file: Path | str | None = None) -> Path:
    """Attach a dedicated file handler for session enumeration logs."""
    global _initialized
    if log_file is None:
        log_file = Path("logs") / f"session_{datetime.now().strftime('%Y-%m-%d_%H%M')}.log"
    log_file = Path(log_file)
    log_file.parent.mkdir(parents=True, exist_ok=True)

    _log.setLevel(logging.INFO)
    if not _initialized:
        fmt = logging.Formatter("%(asctime)s  %(message)s", datefmt="%H:%M:%S")
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(fmt)
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt)
        _log.addHandler(fh)
        _log.addHandler(sh)
        _log.propagate = False
        _initialized = True
    return log_file


def _section(title: str) -> None:
    _log.info("")
    _log.info(SEP)
    _log.info(title)
    _log.info(THIN)


def _end_section() -> None:
    _log.info(SEP)
    _log.info("")


def run_start(
    *,
    town: str,
    provider_count: int,
    focus: str,
    session_log_path: str = "",
    csv_path: str = "",
    txt_path: str = "",
) -> None:
    _section(f"PHASE B.5 — FIND EVERY YOUTH SUMMER CAMP  |  town={town}")
    _log.info(
        "Goal: visit each camp provider's website, detect how they register "
        "campers, collect a direct link for every youth summer camp/clinic/workshop, "
        "and drop adult classes and non-camp noise."
    )
    _log.info("Providers to check: %d", provider_count)
    _log.info("Program focus: %s (child day camps, summer sports clinics, kid workshops only)", focus)
    if session_log_path or csv_path:
        _log.info("")
        _log.info("OUTPUT FILES (where scraped camp links are saved):")
        if session_log_path:
            _log.info("  This detailed log:  %s", session_log_path)
        if csv_path:
            _log.info("  Camp sessions CSV:  %s", csv_path)
        if txt_path:
            _log.info("  Camp sessions TXT:  %s", txt_path)
        _log.info(
            "  CSV/TXT update after each provider finishes. "
            "Each row = one camp with name + register_url."
        )
    _end_section()


def provider_start(*, url: str, host: str, index: int, total: int) -> None:
    _section(f"PROVIDER {index}/{total}  —  {host}")
    _log.info("Starting URL: %s", url)
    _log.info("Opening this page in a browser to see what registration system it uses...")


def fetch_done(*, chars: int, link_count: int) -> None:
    _log.info(
        "Page loaded. Read %d characters of camp-related text and found %d links on the page.",
        chars,
        link_count,
    )


def platform_detected(*, platform: str) -> None:
    explain = PLATFORM_EXPLAIN.get(platform.split("+")[0], PLATFORM_EXPLAIN["custom"])
    _log.info("")
    _log.info("Platform detected: %s", platform.upper())
    _log.info("  %s", explain)


def adapter_found(*, count: int, platform: str) -> None:
    if count:
        _log.info(
            "Structured catalog parser found %d camp/session link(s) using the %s adapter.",
            count,
            platform,
        )
    else:
        _log.info(
            "The %s adapter did not find camp links on this page — will try other methods.",
            platform,
        )


def discovery_found(*, count: int) -> None:
    if count:
        _log.info(
            "Broad discovery found %d additional camp-like page(s) after page verification.",
            count,
        )


def llm_extract_start(
    *,
    url: str,
    text_chars: int,
    link_count: int,
    model: str,
    step: str = "page prose",
) -> None:
    _log.info("")
    _log.info("AI EXTRACTION — %s", step)
    _log.info("  Page: %s", url)
    _log.info("  Input: %d characters of text, %d links on page", text_chars, link_count)
    _log.info("  Model: %s (Ollama)", model)
    _log.info("  Asking the model to list every youth summer camp described on this page...")


def llm_extract_waiting(*, model: str, timeout_s: int) -> None:
    _log.info("  Waiting for Ollama (%s, up to %ds)...", model, timeout_s)


def llm_extract_raw_camps(*, camps: list[dict]) -> None:
    if not camps:
        _log.info("  Model returned 0 camp name(s).")
        return
    _log.info("  Model returned %d camp name(s):", len(camps))
    for i, c in enumerate(camps, 1):
        name = (c.get("name") or "").strip() or "(unnamed)"
        ages = (c.get("ages") or "").strip()
        dates = (c.get("dates") or "").strip()
        ctype = (c.get("type") or "").strip()
        extra = []
        if ages:
            extra.append(f"ages {ages}")
        if dates:
            extra.append(dates)
        if ctype:
            extra.append(ctype)
        suffix = f" ({', '.join(extra)})" if extra else ""
        _log.info("    %d. \"%s\"%s", i, name[:100], suffix)


def llm_extract_link_match(*, name: str, register_url: str | None) -> None:
    if register_url:
        _log.info("    → matched register link for \"%s\": %s", name[:60], register_url)
    else:
        _log.info(
            "    → no register link matched for \"%s\" (name not found in page links)",
            name[:60],
        )


def llm_extract_kept(*, name: str, register_url: str) -> None:
    _log.info("  KEEP  \"%s\" → %s", name[:80], register_url)


def llm_extract_rejected(*, name: str, reason: str) -> None:
    _log.info("  SKIP  \"%s\" — %s", name[:80], reason)


def llm_extract_error(*, error: str) -> None:
    _log.info("  AI extraction failed: %s", error.split("\n")[0][:240])


def llm_page_extract(*, count: int) -> None:
    _log.info("")
    if count:
        _log.info(
            "AI extraction result: %d camp(s) kept with a usable registration link.",
            count,
        )
    else:
        _log.info(
            "AI extraction result: 0 camps kept (model found nothing, bad JSON, or no register links).",
        )


def trail_start(*, max_pages: int) -> None:
    _log.info("")
    _log.info(
        "TRAIL CRAWL — structured adapter found too few camps; following up to %d "
        "promising links on this site...",
        max_pages,
    )


def trail_done(*, pages_visited: int, links_found: int, best_url: str, seed_url: str) -> None:
    if best_url != seed_url:
        _log.info(
            "  Trail finished: %d page(s) visited, %d link(s) collected. "
            "Best registration candidate: %s",
            pages_visited,
            links_found,
            best_url,
        )
    else:
        _log.info(
            "  Trail finished: %d page(s) visited, %d link(s) collected. "
            "No better registration page than the seed URL.",
            pages_visited,
            links_found,
        )


def discovery_start(*, candidate_count: int, max_fetches: int) -> None:
    _log.info("")
    _log.info(
        "BROAD DISCOVERY — scanning %d camp-like link(s); will fetch up to %d "
        "for AI/rule verification...",
        candidate_count,
        max_fetches,
    )


def discovery_fetch(*, n: int, max_fetches: int, url: str, link_text: str) -> None:
    _log.info("  Fetch %d/%d: %s", n, max_fetches, url)
    if link_text.strip():
        _log.info("    link text: \"%s\"", link_text.strip()[:80])


def discovery_verdict(*, url: str, kept: bool, reason: str, stage: str = "") -> None:
    label = "KEEP" if kept else "SKIP"
    stage_bit = f" [{stage}]" if stage else ""
    _log.info("    %s%s — %s", label, stage_bit, reason[:120] or url)


def discovery_done(*, found: int, fetches: int) -> None:
    _log.info(
        "  Broad discovery done: %d camp(s) added after %d page fetch(es).",
        found,
        fetches,
    )


def agent_nav_start(*, seed_url: str, link_count: int) -> None:
    _log.info("")
    _log.info("AGENT NAVIGATION — surveying %d link(s) on landing page", link_count)
    _log.info("  seed: %s", seed_url)
    _log.info("  The AI will pick which pages list camps and where parents register.")


def agent_nav_link_option(*, n: int, url: str, text: str) -> None:
    if _trace_enabled():
        label = f' "{text[:60]}"' if text.strip() else ""
        _log.info("  option %d:%s %s", n, label, url)


def agent_nav_reasoning(*, reasoning: str) -> None:
    if reasoning.strip():
        _log.info("  AI reasoning: %s", reasoning.strip()[:500])


def agent_nav_pick(*, kind: str, url: str, label: str, why: str) -> None:
    _log.info("  PICK [%s] %s", kind.upper(), url)
    if label.strip():
        _log.info("    link text: \"%s\"", label[:80])
    if why.strip():
        _log.info("    because: %s", why[:200])


def agent_nav_fetch(*, kind: str, url: str) -> None:
    _log.info("  OPEN [%s] %s", kind.upper(), url)


def agent_nav_fetch_error(*, url: str, error: str) -> None:
    _log.info("  OPEN FAILED %s — %s", url, error[:160])


def agent_nav_verified(*, url: str, verdict: str, name: str = "") -> None:
    label = f" \"{name[:60]}\"" if name.strip() else ""
    _log.info("  VERIFY%s → %s (%s)", label, verdict or "?", url)


def agent_nav_failed(*, error: str) -> None:
    _log.info("  Agent navigation failed: %s", error[:200])


def agent_nav_done(*, session_count: int) -> None:
    _log.info("  Agent navigation done: %d camp link(s) found from chosen pages.", session_count)


def nav_start(*, seed_url: str, max_depth: int, max_fetches: int) -> None:
    _log.info("")
    _log.info(
        "NAVIGATOR v2 — bounded crawl from seed (depth≤%d, fetches≤%d)",
        max_depth,
        max_fetches,
    )
    _log.info("  seed: %s", seed_url)


def nav_fetch(*, role: str, url: str) -> None:
    _log.info("  OPEN [%s] %s", role.upper(), url)


def nav_fetch_error(*, url: str, error: str) -> None:
    _log.info("  OPEN FAILED %s — %s", url, error[:160])


def nav_role(*, url: str, role: str, depth: int) -> None:
    if _trace_enabled():
        _log.info("  ROLE [%s] depth=%d %s", role.upper(), depth, url)


def nav_fanout(*, catalog_url: str, detail_count: int) -> None:
    _log.info("  FAN-OUT %d camp detail link(s) from catalog %s", detail_count, catalog_url)


def nav_adapter_done(*, platform: str, count: int) -> None:
    _log.info("  ADAPTER [%s] → %d verified session(s)", platform, count)


def nav_verified(*, url: str, verdict: str, name: str = "") -> None:
    label = f" \"{name[:60]}\"" if name.strip() else ""
    _log.info("  VERIFY%s → %s (%s)", label, verdict or "?", url)


def nav_done(*, session_count: int, fetches: int) -> None:
    _log.info(
        "  Navigator done: %d camp(s) after %d page fetch(es).",
        session_count,
        fetches,
    )


def discovery_skip(*, url: str, reason: str) -> None:
    if _trace_enabled():
        _log.info("    SKIP candidate %s — %s", url, reason)


def discovery_keep(*, name: str, url: str, via: str) -> None:
    if _trace_enabled():
        _log.info("    KEEP candidate \"%s\" → %s [%s]", name[:80], url, via)


# --------------------------------------------------------------------------- #
# Full extraction trace (every fetch, crawl step, adapter call)
# --------------------------------------------------------------------------- #
_trace_enabled_cache: bool | None = None


def _trace_enabled() -> bool:
    global _trace_enabled_cache
    if _trace_enabled_cache is None:
        try:
            from config.settings import SETTINGS

            _trace_enabled_cache = bool(SETTINGS.get("b5_trace_verbose", True))
        except Exception:
            _trace_enabled_cache = True
    return _trace_enabled_cache


def trace(step: str, detail: str = "") -> None:
    if not _trace_enabled():
        return
    if detail:
        _log.info("  → %s — %s", step, detail)
    else:
        _log.info("  → %s", step)


def trace_fetch_start(*, url: str, caller: str) -> None:
    if _trace_enabled():
        _log.info("  FETCH [%s] %s", caller, url)


def trace_fetch_done(
    *, url: str, chars: int, link_count: int, error: str = ""
) -> None:
    if not _trace_enabled():
        return
    if error:
        _log.info("  FETCH FAIL %s — %s", url, error[:160])
    else:
        _log.info(
            "  FETCH OK %s — %d chars, %d links",
            url,
            chars,
            link_count,
        )


def trace_crawl_start(*, start_url: str, max_pages: int, max_depth: int, mode: str) -> None:
    if _trace_enabled():
        _log.info(
            "  CRAWL START [%s] seed=%s max_pages=%d max_depth=%d",
            mode,
            start_url,
            max_pages,
            max_depth,
        )


def trace_crawl_visit(
    *,
    n: int,
    max_pages: int,
    url: str,
    depth: int,
    score: int,
    link_text: str,
) -> None:
    if not _trace_enabled():
        return
    label = f"\"{link_text[:50]}\"" if link_text.strip() else "(no label)"
    _log.info(
        "  CRAWL VISIT %d/%d depth=%d score=%d %s",
        n,
        max_pages,
        depth,
        score,
        url,
    )
    if link_text.strip():
        _log.info("    via link: %s", label)


def trace_crawl_skip(*, url: str, reason: str) -> None:
    if _trace_enabled():
        _log.info("  CRAWL SKIP %s — %s", url, reason)


def trace_crawl_enqueue(*, url: str, depth: int, score: int, link_text: str) -> None:
    if not _trace_enabled():
        return
    label = f" \"{link_text[:50]}\"" if link_text.strip() else ""
    _log.info("  CRAWL QUEUE depth=%d score=%d %s%s", depth, score, url, label)


def trace_crawl_stop(*, url: str, reason: str) -> None:
    if _trace_enabled():
        _log.info("  CRAWL STOP at %s — %s", url, reason)


def trace_crawl_page_links(*, url: str, link_count: int) -> None:
    if _trace_enabled() and link_count:
        _log.info("  CRAWL found %d outbound link(s) on %s", link_count, url)


def trace_adapter(*, platform: str, url: str) -> None:
    if _trace_enabled():
        _log.info("  ADAPTER [%s] %s", platform.upper(), url)


def trace_probe(*, url: str, label: str) -> None:
    if _trace_enabled():
        _log.info("  PROBE [%s] %s", label, url)


def trace_llm_classify(*, url: str, stage: str, is_camp: bool, reason: str) -> None:
    if _trace_enabled():
        verdict = "CAMP" if is_camp else "NOT CAMP"
        _log.info("  LLM CLASSIFY [%s] %s — %s: %s", stage, verdict, url, reason[:100])


def ollama_call(
    *,
    purpose: str,
    model: str,
    input_summary: str,
    response: dict | None = None,
    error: str = "",
) -> None:
    import json as _json

    _log.info("")
    _log.info("OLLAMA CALL [%s]", purpose)
    _log.info("  model: %s", model)
    _log.info("  input: %s", input_summary)
    if error:
        _log.info("  result: ERROR — %s", error[:400])
    elif response is not None:
        raw = _json.dumps(response, ensure_ascii=False)
        if len(raw) > 600:
            _log.info("  result: %s…", raw[:600])
        else:
            _log.info("  result: %s", raw)
        reason = response.get("reason") or response.get("llm_reason")
        if reason:
            _log.info("  reasoning: %s", str(reason)[:300])
        if "keep" in response:
            _log.info("  verdict: %s", "KEEP" if response.get("keep") else "DROP")
        if "is_camp" in response:
            _log.info("  verdict: %s", "CAMP" if response.get("is_camp") else "NOT CAMP")
        if "follow" in response:
            _log.info("  verdict: %s", "FOLLOW LINK" if response.get("follow") else "SKIP LINK")
        if "confidence" in response:
            _log.info("  confidence: %s", response.get("confidence"))
        camps = response.get("camps")
        if isinstance(camps, list) and camps:
            _log.info("  camps returned: %d", len(camps))


def links_pool(*, seed_url: str, stage: str, link_count: int, sample: list[str] | None = None) -> None:
    _log.info("")
    _log.info("LINKS COLLECTED [%s] — %d total from %s", stage, link_count, seed_url)
    if sample:
        _log.info("  sample URLs:")
        for u in sample[:15]:
            _log.info("    • %s", u)
        if len(sample) > 15:
            _log.info("    … and %d more", len(sample) - 15)


def sessions_before_save(
    *,
    provider_url: str,
    platform: str,
    sessions: list[dict],
    dropped: list[dict],
    csv_path: str,
) -> None:
    _log.info("")
    _log.info("SESSIONS FOR THIS PROVIDER (will write to %s):", csv_path)
    _log.info("  provider: %s  platform: %s", provider_url, platform)
    if sessions:
        _log.info("  %d camp link(s) kept:", len(sessions))
        for s in sessions:
            name = (s.get("name") or "").strip()[:100] or "(unnamed)"
            reg = (s.get("register_url") or "").strip()
            _log.info("    • %s", name)
            _log.info("        register: %s", reg)
    else:
        _log.info("  0 camp links kept for this provider.")
    if dropped:
        _log.info("  %d item(s) filtered out (not youth-summer)", len(dropped))


def output_checkpoint(
    *,
    csv_path: str,
    txt_path: str,
    providers_done: int,
    total_sessions: int,
    added: int,
) -> None:
    _log.info("")
    _log.info(
        "CHECKPOINT WRITE — %d provider(s) done, %d total camp link(s) on disk",
        providers_done,
        total_sessions,
    )
    _log.info("  updated: %s", csv_path)
    _log.info("  updated: %s", txt_path)
    if added:
        _log.info("  +%d new row(s) from latest provider", added)


def dedupe(*, before: int, after: int) -> None:
    if before > after:
        _log.info("Removed %d duplicate link(s) (same URL listed more than once).", before - after)


def focus_filter_start(*, before: int) -> None:
    _log.info("")
    _log.info(
        "Applying youth-summer focus filter to %d candidate(s) — "
        "keeping kids' summer camps/clinics, dropping adult classes and memberships.",
        before,
    )


def focus_kept(*, name: str, reason: str) -> None:
    plain = FOCUS_REASON_PLAIN.get(reason, reason)
    _log.info("  KEEP  \"%s\" — %s", name[:80], plain)


def focus_dropped(*, name: str, reason: str) -> None:
    plain = FOCUS_REASON_PLAIN.get(reason, reason)
    _log.info("  DROP  \"%s\" — %s", name[:80], plain)


def focus_summary(*, kept: int, dropped: int, hard_drops: int, ambiguous_drops: int) -> None:
    _log.info("")
    _log.info(
        "Focus filter result: %d kept | %d dropped (%d obvious rejects, %d unclear names)",
        kept,
        dropped,
        hard_drops,
        ambiguous_drops,
    )


def llm_tiebreaker_start(*, ambiguous_count: int, budget: int) -> None:
    _log.info("")
    _log.info(
        "Sending up to %d unclear name(s) to AI (Ollama) for a second opinion "
        "(%d ambiguous total).",
        min(budget, ambiguous_count),
        ambiguous_count,
    )


def llm_tiebreaker_recovered(*, name: str, reason: str) -> None:
    _log.info("  AI SAYS KEEP  \"%s\" — %s", name[:80], reason[:120])


def llm_tiebreaker_confirmed_drop(*, name: str, reason: str) -> None:
    _log.info("  AI SAYS DROP  \"%s\" — %s", name[:80], reason[:120])


def llm_unavailable() -> None:
    _log.info("Ollama is not running — skipping AI second-opinion step for unclear names.")


def llm_budget_exhausted(*, remaining: int) -> None:
    _log.info(
        "AI review budget used up — %d unclear name(s) left as dropped (not sent to AI).",
        remaining,
    )


def llm_consecutive_drop_stop(*, consecutive: int, remaining: int) -> None:
    _log.info(
        "AI review stopped after %d consecutive DROP verdicts — %d unclear name(s) "
        "left as dropped (not sent to AI).",
        consecutive,
        remaining,
    )


def provider_done(
    *,
    url: str,
    platform: str,
    kept: int,
    dropped: int,
    sessions: list[dict] | None = None,
) -> None:
    _log.info("")
    if kept:
        _log.info(
            "DONE with this provider: %d youth summer camp(s) saved [%s].",
            kept,
            platform,
        )
        if sessions:
            _log.info("  Camps added (exactly as found on this site):")
            for s in sessions:
                name = (s.get("name") or "").strip()[:120] or "(unnamed)"
                date = (s.get("dates") or "").strip()
                reg_url = (s.get("register_url") or "").strip()
                _log.info("    • %s — %s", name, date or "date not listed")
                if reg_url:
                    _log.info("        register: %s", reg_url)
    else:
        _log.info(
            "DONE with this provider: no youth summer camps found (may need JS/Firecrawl or site blocked us).",
        )
    _log.info("  Source: %s", url)
    if dropped:
        _log.info("  (%d item(s) filtered out as not youth-summer)", dropped)
    _end_section()


def provider_error(*, url: str, error: str) -> None:
    _log.info("")
    _log.info("ERROR visiting this provider — skipping.")
    _log.info("  URL: %s", url)
    _log.info("  Problem: %s", error.split("\n")[0][:200])
    _end_section()


def run_summary(
    *,
    town: str,
    providers_checked: int,
    providers_with_camps: int,
    total_sessions: int,
    csv_path: str,
    txt_path: str,
    runtime_s: float,
) -> None:
    _section(f"PHASE B.5 COMPLETE  |  {town}")
    _log.info("Providers checked:        %d", providers_checked)
    _log.info("Providers with camps:     %d", providers_with_camps)
    _log.info("Total camp/session links: %d", total_sessions)
    _log.info("Runtime:                  %.0f seconds (%.1f minutes)", runtime_s, runtime_s / 60)
    _log.info("")
    _log.info("Output files (ready for Firecrawl detail extraction):")
    _log.info("  CSV: %s", csv_path)
    _log.info("  TXT: %s", txt_path)
    _end_section()
