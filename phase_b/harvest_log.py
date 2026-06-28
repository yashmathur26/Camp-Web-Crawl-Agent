"""Human-readable structured logging for Phase B harvest."""

import logging

from phase_b import harvest_activity

SEP = "=" * 72
THIN = "-" * 72

_harvest = logging.getLogger("harvest")


def section(title: str) -> None:
    _harvest.info("")
    _harvest.info(SEP)
    _harvest.info(title)
    _harvest.info(THIN)


def end_section() -> None:
    _harvest.info(SEP)
    _harvest.info("")


def source_start(*, url: str, kind: str, town: str, title: str = "") -> None:
    harvest_activity.set_context(town=town, source_kind=kind, source_url=url)
    section(f"SOURCE  [{kind.upper()}]  town={town}")
    _harvest.info("URL:")
    _harvest.info("  %s", url)
    if title:
        _harvest.info("Title: %s", title)
    harvest_activity.record(
        "source_start",
        town=town,
        source_kind=kind,
        source_url=url,
        detail=title[:200] if title else "",
    )


def duplicate_seed_skipped(url: str, kept_url: str | None = None) -> None:
    _harvest.info("")
    _harvest.info("Skipped duplicate seed")
    _harvest.info("  %s", url)
    if kept_url:
        _harvest.info("  (kept instead: %s)", kept_url)
    harvest_activity.record(
        "duplicate_seed_skipped",
        url=url,
        status="skipped",
        detail=f"kept={kept_url}" if kept_url else "",
    )


def camp_host_seed_kept(url: str) -> None:
    _harvest.info("")
    _harvest.info("Camp-host seed (always crawled):")
    _harvest.info("  %s", url)
    harvest_activity.record("camp_host_seed", url=url, status="queued")


def crawl_failed(url: str, error: str) -> None:
    _harvest.info("")
    _harvest.info("CRAWL FAILED (will retry on next run)")
    _harvest.info("  URL: %s", url)
    short = error.split("\n")[0][:200]
    _harvest.info("  Error: %s", short)
    harvest_activity.record(
        "crawl_failed",
        source_url=url,
        url=url,
        status="failed",
        detail=short,
    )


def crawl_stats(*, pages: int, links_found: int, heuristic_kept: int) -> None:
    _harvest.info("")
    _harvest.info(
        "Crawl: %d pages visited | %d links found | %d passed rules",
        pages,
        links_found,
        heuristic_kept,
    )
    harvest_activity.record(
        "crawl_stats",
        pages=pages,
        links_found=links_found,
        rule_kept=heuristic_kept,
    )


def link_rule_rejected(url: str, link_text: str = "") -> None:
    _harvest.info("")
    _harvest.info("RULES  reject")
    _harvest.info("  URL: %s", url)
    if link_text:
        _harvest.info("  Text: %s", link_text.strip()[:120])
    harvest_activity.record(
        "link_rule_rejected",
        url=url,
        link_text=link_text,
        status="rejected",
    )


def link_llm_verdict(*, url: str, kept: bool, reason: str, cached: bool = False) -> None:
    tag = "KEEP" if kept else "REJECT"
    cache_note = " (cached)" if cached else ""
    _harvest.info("")
    _harvest.info("LLM     %s%s", tag, cache_note)
    _harvest.info("  URL: %s", url)
    _harvest.info("  Why: %s", reason)
    harvest_activity.record(
        "link_llm_keep" if kept else "link_llm_reject",
        url=url,
        status="kept" if kept else "rejected",
        detail=f"{reason}{' (cached)' if cached else ''}",
    )


def link_follow_decision(*, url: str, follow: bool) -> None:
    tag = "FOLLOW" if follow else "SKIP"
    _harvest.info("")
    _harvest.info("LINK    %s (llm)", tag)
    _harvest.info("  URL: %s", url)
    harvest_activity.record(
        "link_follow" if follow else "link_no_follow",
        url=url,
        status="follow" if follow else "skip",
        detail="llm link-follow gate",
    )


def llm_cap_reached(*, max_calls: int, skipped: int) -> None:
    _harvest.info("")
    _harvest.info(
        "LLM cap reached (%d calls/source) — skipped %d unchecked link(s)",
        max_calls,
        skipped,
    )
    harvest_activity.record(
        "llm_cap_reached",
        status="capped",
        detail=f"max={max_calls} skipped={skipped}",
    )


def geo_skipped(*, url: str, reason: str, town: str = "") -> None:
    _harvest.info("")
    _harvest.info("SKIPPED  [geo]  %s", reason)
    _harvest.info("  URL: %s", url)
    harvest_activity.record(
        "geo_skipped",
        town=town,
        source_url=url,
        url=url,
        status="skipped",
        detail=reason,
    )


def link_saved(url: str, link_text: str = "", source_type: str = "") -> None:
    _harvest.info("")
    _harvest.info("SAVED   [%s]", source_type or "link")
    _harvest.info("  URL: %s", url)
    if link_text:
        _harvest.info("  Text: %s", link_text.strip()[:120])
    harvest_activity.record(
        "link_saved",
        url=url,
        link_text=link_text,
        source_type=source_type,
        status="saved",
    )


def source_summary(
    *,
    url: str,
    added: int,
    rule_kept: int,
    llm_rejected: int,
    llm_kept: int,
    is_guide: bool,
) -> None:
    kind = "guide" if is_guide else "directory"
    _harvest.info("")
    _harvest.info(
        "DONE    %s | +%d new links | rules:%d | llm kept:%d | llm rejected:%d",
        kind,
        added,
        rule_kept,
        llm_kept,
        llm_rejected,
    )
    _harvest.info("  Source URL: %s", url)
    end_section()
    harvest_activity.record(
        "source_done",
        source_kind=kind,
        source_url=url,
        rule_kept=rule_kept,
        llm_kept=llm_kept,
        llm_rejected=llm_rejected,
        added=added,
        status="done",
    )


def run_banner(
    *,
    phase: str,
    town: str | None,
    llm: bool,
    already_crawled: int | None = None,
    pending: int | None = None,
) -> None:
    section(f"PHASE {phase} HARVEST")
    _harvest.info("Town filter: %s", town or "all")
    _harvest.info("LLM camp filter: %s", "on" if llm else "off")
    if already_crawled is not None and pending is not None:
        if already_crawled:
            _harvest.info(
                "Resume: %d source(s) already crawled, %d remaining this pass",
                already_crawled,
                pending,
            )
        else:
            _harvest.info("Sources to crawl this pass: %d", pending)
    end_section()
    harvest_activity.record(
        "run_start",
        town=town or "",
        detail=f"phase={phase} llm={'on' if llm else 'off'}",
    )


def run_summary(**kwargs: int | float) -> None:
    harvest_activity.record("run_summary", detail=" ".join(f"{k}={v}" for k, v in kwargs.items()))


def llm_funnel_metrics(**kwargs: int) -> None:
    harvest_activity.record(
        "llm_funnel",
        detail=" ".join(f"{k}={v}" for k, v in kwargs.items()),
    )


def robots_disallow(url: str, *, source_url: str = "", town: str = "") -> None:
    _harvest.info("Robots disallow: %s", url)
    harvest_activity.record(
        "robots_disallow",
        town=town,
        source_url=source_url or url,
        url=url,
        status="blocked",
    )


def guide_failed(url: str, error: str, *, town: str = "") -> None:
    _harvest.info("Guide harvest failed for %s: %s", url, error)
    harvest_activity.record(
        "guide_failed",
        town=town,
        source_url=url,
        url=url,
        status="failed",
        detail=error.split("\n")[0][:200],
    )
