"""Phase P: parent enrollment verification with rules-first + two-model LLM."""

from __future__ import annotations

import asyncio
import csv
import json
import logging
from pathlib import Path
from config.prompts import PARENT_VERIFY_FAST_SYSTEM, PARENT_VERIFY_SYSTEM
from config.settings import SETTINGS
from src.crawl import fetch_page_text, fetch_wait_until
from src.enrollment_signals import extract_enrollment_signals, verdict_from_signals
from src.llm import OllamaError, chat, is_available
from src.llm_pool import run_batch
from src.data_layout import (
    camp_sessions_csv,
    quality_tier_csv,
    refresh_town_index,
    sessions_verified_csv,
)
from src.session_quality import (
    classify_session_tier,
    split_sessions,
    write_parent_verify_csvs,
)
from src.sessions import SESSION_CSV_COLUMNS
from src.urls import normalize_url

logger = logging.getLogger(__name__)


def _normalize_register_url(url: str) -> str:
    return normalize_url(url or "").rstrip("/")


async def _fetch_verify_page(url: str) -> str:
    """Fetch page text; JS-heavy hosts wait for networkidle."""
    if not url:
        return ""
    try:
        return await fetch_page_text(url, wait_until=fetch_wait_until(url, kind="register"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("parent verify fetch failed %s: %s", url, exc)
        return ""


def _needs_llm(
    session: dict,
    signals,
    *,
    verify_all: bool = False,
) -> bool:
    if verify_all:
        return True
    if signals.auto_verdict:
        return False
    tier = session.get("quality_tier", "")
    platform = session.get("platform", "")
    if platform == "llm":
        return True
    if tier == "needs_trail":
        return True
    if signals.blockers and "empty_page" in signals.blockers:
        return False
    if signals.auto_verdict is None:
        return True
    return False


def _llm_verify_one(item: tuple) -> dict:
    session, url, page_text, signals = item
    fast_model = SETTINGS.get("ollama_fast_model", "qwen2.5:3b")
    verify_model = SETTINGS.get("ollama_verify_model") or SETTINGS.get("ollama_model")
    max_chars = int(SETTINGS.get("ollama_validate_max_chars", 3000))
    user = json.dumps(
        {
            "session_name": session.get("name", ""),
            "register_url": url,
            "platform": session.get("platform", ""),
            "page_excerpt": (page_text or "")[:max_chars],
            "signals": signals.to_dict(),
        },
        ensure_ascii=False,
    )
    try:
        fast = chat(
            PARENT_VERIFY_FAST_SYSTEM,
            user,
            model=fast_model,
            temperature=0.0,
            timeout=SETTINGS.get("ollama_validate_timeout_s", 45),
        )
        verdict = fast.get("verdict", "unverified")
        confidence = fast.get("confidence", "low")
        if confidence == "high" and verdict in (
            "parent_ready",
            "brochure_only",
            "wrong_audience",
        ):
            return {
                "verdict": verdict,
                "reason": fast.get("reason", "fast model"),
                "confidence": 0.85,
            }
        full = chat(
            PARENT_VERIFY_SYSTEM,
            user,
            model=verify_model,
            temperature=0.0,
            timeout=SETTINGS.get("ollama_session_timeout_s", 60),
        )
        return {
            "verdict": full.get("verdict", verdict),
            "reason": "; ".join(full.get("evidence", [])[:3]) or full.get("missing_for_parent", [""])[0],
            "confidence": float(full.get("confidence", 0.7)),
        }
    except OllamaError as exc:
        logger.warning("parent verify LLM failed for %s: %s", url, exc)
        return {"verdict": "unverified", "reason": str(exc), "confidence": 0.0}


def _already_verified(session: dict) -> bool:
    return bool(session.get("parent_verdict"))


def _floor_program_verdict(session: dict, verdict: str) -> str:
    """Task 1.3: provider-level program rows are verified like any row, but a
    missing cart/price must not demote them below brochure_only — the row only
    claims "this provider runs a summer program", not "you can enroll here"."""
    if (session.get("granularity") or "") == "program" and verdict == "unverified":
        return "brochure_only"
    return verdict


async def verify_sessions(
    sessions: list[dict],
    *,
    verify_all: bool = False,
    max_llm: int | None = None,
) -> list[dict]:
    """Verify sessions; returns rows with parent_verdict columns."""
    max_llm = max_llm if max_llm is not None else int(SETTINGS.get("parent_verify_max_llm", 80))
    concurrency = int(SETTINGS.get("parent_verify_concurrency", 4))

    # Attach quality tier if missing
    enriched: list[dict] = []
    for s in sessions:
        if "quality_tier" not in s:
            tier, reason = classify_session_tier(s)
            s = {**s, "quality_tier": tier, "quality_reason": reason}
        if s.get("quality_tier") == "rejected":
            enriched.append(
                {
                    **s,
                    "parent_verdict": "wrong_audience",
                    "enrollment_signals": "{}",
                    "parent_verify_reason": s.get("quality_reason", "rejected in Phase Q"),
                }
            )
            continue
        enriched.append(s)

    work = [s for s in enriched if s.get("quality_tier") != "rejected"]
    pending = [s for s in work if not _already_verified(s)]

    url_to_sessions: dict[str, list[dict]] = {}
    for s in pending:
        reg = s.get("register_url") or s.get("source_url", "")
        key = _normalize_register_url(reg)
        if key:
            url_to_sessions.setdefault(key, []).append(s)

    unique_urls = list(url_to_sessions.keys())
    sem = asyncio.Semaphore(concurrency)

    async def fetch_one(u: str) -> tuple[str, str]:
        async with sem:
            text = await _fetch_verify_page(u)
            return u, text

    fetched = dict(await asyncio.gather(*[fetch_one(u) for u in unique_urls]))

    url_results: dict[str, dict] = {}
    llm_queue: list[tuple] = []

    for url, page_text in fetched.items():
        sample = url_to_sessions[url][0]
        signals = extract_enrollment_signals(
            url,
            page_text,
            session_name=sample.get("name", ""),
        )
        auto = verdict_from_signals(signals, page_text)
        entry = {
            "signals": signals,
            "page_text": page_text,
            "auto_verdict": auto,
            "llm": None,
        }
        if auto and auto != "unverified":
            entry["final_verdict"] = auto
            entry["reason"] = auto
        elif _needs_llm(sample, signals, verify_all=verify_all):
            llm_queue.append((sample, url, page_text, signals))
        else:
            entry["final_verdict"] = signals.auto_verdict or "unverified"
            entry["reason"] = signals.blockers[0] if signals.blockers else "rules inconclusive"
        url_results[url] = entry

    if llm_queue and is_available():
        capped = llm_queue[:max_llm]
        if len(llm_queue) > max_llm:
            logger.warning("parent verify LLM cap: %d of %d", max_llm, len(llm_queue))
        llm_out = await run_batch(capped, _llm_verify_one, concurrency=concurrency)
        for item, result in zip(capped, llm_out):
            _, url, _, _ = item
            url_results[url]["llm"] = result
            url_results[url]["final_verdict"] = result.get("verdict", "unverified")
            url_results[url]["reason"] = result.get("reason", "")
    elif llm_queue:
        for sample, url, _, signals in llm_queue:
            url_results[url]["final_verdict"] = signals.auto_verdict or "unverified"
            url_results[url]["reason"] = "ollama unavailable"

    out: list[dict] = []
    for s in enriched:
        if s.get("quality_tier") == "rejected":
            out.append(s)
            continue
        if _already_verified(s):
            out.append(s)
            continue
        reg = _normalize_register_url(s.get("register_url") or s.get("source_url", ""))
        res = url_results.get(reg, {})
        signals = res.get("signals")
        verdict = _floor_program_verdict(s, res.get("final_verdict", "unverified"))
        reason = res.get("reason", "")
        row = {
            **s,
            "parent_verdict": verdict,
            "parent_can_register": verdict == "parent_ready",
            "enrollment_signals": json.dumps(signals.to_dict() if signals else {}),
            "parent_verify_reason": reason,
        }
        out.append(row)

    # Rejected rows already in out from enriched loop - need to fix: rejected were appended to enriched but work loop skipped them. They're only in enriched with parent_verdict set. Let me trace...

    # Actually rejected sessions were appended to enriched with parent_verdict, but work only has non-rejected. 
    # The final loop only processes enriched - good.

    return out


def load_sessions_for_verify(
    town: str,
    *,
    sessions_csv: Path | str | None = None,
) -> list[dict]:
    path = Path(sessions_csv) if sessions_csv else camp_sessions_csv(town)
    if path.exists():
        with open(path, encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))
    rows: list[dict] = []
    for tier in ("registrable", "needs_trail"):
        p = quality_tier_csv(town, tier)
        if p.exists():
            with open(p, encoding="utf-8", newline="") as f:
                rows.extend(csv.DictReader(f))
    return rows


async def run_parent_verify(
    town: str,
    *,
    sessions: list[dict] | None = None,
    verify_all: bool = False,
    max_llm: int | None = None,
    output_dir: Path | str | None = None,
) -> dict:
    _ = output_dir
    sessions = sessions or load_sessions_for_verify(town)
    verified = await verify_sessions(sessions, verify_all=verify_all, max_llm=max_llm)
    paths = write_parent_verify_csvs(town, verified)
    refresh_town_index(town)

    counts: dict[str, int] = {}
    for s in verified:
        v = s.get("parent_verdict", "unverified")
        counts[v] = counts.get(v, 0) + 1

    return {
        "town": town,
        "total": len(verified),
        "counts": counts,
        "paths": {k: str(v) for k, v in paths.items()},
    }
