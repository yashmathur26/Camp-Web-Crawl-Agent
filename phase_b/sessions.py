"""Phase B.5: enumerate per-camp session links for a town's providers."""

from __future__ import annotations

import asyncio
import csv
import logging
import re
import time
from pathlib import Path
from urllib.parse import urlparse

from config.community_ed import default_catalog_seed, is_community_ed_host
from config.settings import SETTINGS
from shared import session_log
from shared.data_layout import (
    camp_links_csv,
    camp_sessions_csv,
    candidates_csv,
    refresh_town_index,
    town_phase_dir,
)
from shared.geo_filter import is_out_of_state_url
from phase_b.platforms import enumerate_provider
from shared.urls import normalize_url

logger = logging.getLogger(__name__)

GUIDE_HOSTS = {
    "macaronikid.com",
    "mommypoppins.com",
    "bostoncentral.com",
    "teenlife.com",
    "activityhero.com",
    "kidsoutandabout.com",
    "bostonparentspaper.com",
    "communitykangaroo.com",
    "masscamps.com",
    "thebestcamps.com",
    "bgca.org",
    "bostontechmom.com",
    "bostonmoms.com",
    "getfamilyhq.com",
    "tourlexington.us",
    "metrowestmom.com",
    "walthamplaygroup.org",
    "jewishboston.com",
    "mass.gov",
    "usasportgroup.com",
}

SESSION_CSV_COLUMNS = [
    "name",
    "register_url",
    "info_url",
    "platform",
    "dates",
    "ages",
    "price",
    "kind",
    "source_url",
    "granularity",
]


def host_of(url: str) -> str:
    h = urlparse(url).netloc.lower()
    return h[4:] if h.startswith("www.") else h


def _locality_score(url: str, town: str) -> int:
    """Boost municipal / town-named hosts when picking provider seeds."""
    t = town.lower().replace(" ", "")
    u = url.lower()
    if not t:
        return 0
    if any(x in u for x in (f"{t}ma.myrec", f"townof{t}", f"{t}recreation", f"{t}rec")):
        return 4
    if t in u and not any(bad in u for bad in (f"{t}vt", f"{t}nc", f"{t}nj", f"{t}ia")):
        return 2
    return 0


def _rank_seed_url(u: str, preferred: bool) -> int:
    """Higher rank = better seed. Catalog/listing pages beat bare landings."""
    lu = u.lower()
    path = urlparse(u).path.strip("/")
    segments = [s for s in path.split("/") if s]

    # 0 — per-item detail pages (never use as town-wide seed)
    if "program_details" in lu or "iteminfo" in lu:
        return 0

    # 5 — explicit catalog / registration listing
    if re.search(
        r"find-a-class|class-category|product-category|/shop(/|$)|"
        r"activities\.aspx|search\.html.*type=camp",
        lu,
    ):
        return 5
    if re.search(r"/programs(/|$)|/camps?(/|$)|/info/activities", lu):
        return 5

    # 4 — deeper path with camp/program keyword (not bare landing)
    if len(segments) >= 2 and re.search(
        r"lexplorations|summer-camp|summer-camps|day-camp|camp", lu
    ):
        return 4

    # 3 — generic preferred directory candidate
    if preferred:
        return 3

    # 2 — bare single-segment landing (e.g. /lexplorations, /education)
    if len(segments) <= 1:
        return 2

    return 1


def load_provider_urls(
    town: str,
    candidates_path: Path | str | None = None,
    camp_links_path: Path | str | None = None,
) -> list[str]:
    """Pick one best seed URL per provider host from candidates + camp_links."""
    candidates_path = candidates_path or candidates_csv()
    camp_links_path = camp_links_path or camp_links_csv()
    path = Path(candidates_path)
    by_host: dict[str, str] = {}

    if path.exists():
        with open(path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("town") != town:
                    continue
                url = row.get("url", "")
                if not url:
                    continue
                h = host_of(url)
                if not h or any(h.endswith(g) for g in GUIDE_HOSTS):
                    continue
                if row.get("classified_as") == "guide":
                    continue
                oos, _ = is_out_of_state_url(url, title=row.get("title", ""))
                if oos:
                    continue
                preferred = row.get("preferred") == "true"
                if is_community_ed_host(url):
                    url = default_catalog_seed(h)
                rank = _rank_seed_url(url, preferred) + _locality_score(url, town)
                prev = by_host.get(h)
                prev_rank = (
                    _rank_seed_url(prev, False) + _locality_score(prev, town) if prev else -1
                )
                if h not in by_host or rank > prev_rank:
                    by_host[h] = url

    links_path = Path(camp_links_path)
    if links_path.exists():
        with open(links_path, encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                if row.get("town_hint") and row.get("town_hint") != town:
                    continue
                url = row.get("url", "")
                if not url:
                    continue
                h = host_of(url)
                if not h or h in by_host or any(h.endswith(g) for g in GUIDE_HOSTS):
                    continue
                oos, _ = is_out_of_state_url(url, title=row.get("link_text", ""))
                if oos:
                    continue
                if is_community_ed_host(url):
                    url = default_catalog_seed(h)
                rank = _rank_seed_url(url, False) + _locality_score(url, town)
                prev = by_host.get(h)
                prev_rank = (
                    _rank_seed_url(prev, False) + _locality_score(prev, town) if prev else -1
                )
                if rank > prev_rank:
                    by_host[h] = url

    from config.sources import TOWN_REC_SEEDS

    town_seed = TOWN_REC_SEEDS.get(town)
    if town_seed:
        h = host_of(town_seed)
        if h and h not in by_host:
            by_host[h] = town_seed

    return list(_filter_b5_providers(by_host.values()))


_B5_BLOCKED_HOST_SUBSTRINGS = (
    "mail.google.com",
    "accounts.google.com",
    "printfriendly.com",
    "gmail.com",
)


def _filter_b5_providers(urls: list[str]) -> list[str]:
    """Drop share/mail/utility hosts that are never camp providers."""
    kept: list[str] = []
    for url in urls:
        host = host_of(url).lower()
        if any(block in host for block in _B5_BLOCKED_HOST_SUBSTRINGS):
            continue
        if host in {"google.com", "facebook.com", "instagram.com"}:
            continue
        kept.append(url)
    return kept


# --------------------------------------------------------------------------- #
# Task 1.2 — provider-level fallback rows
# --------------------------------------------------------------------------- #
def _known_provider_hosts(town: str) -> set[str]:
    """Hosts we have independent evidence are camp providers: Phase B harvest
    hosts + committed baseline providers for the town."""
    from shared.data_layout import DATA_ROOT, town_slug
    from phase_b.parent_auditor import _load_camp_link_hosts

    hosts = set(_load_camp_link_hosts(town))
    baseline = DATA_ROOT / "_baseline" / town_slug(town) / "baseline.json"
    if baseline.exists():
        try:
            import json

            data = json.loads(baseline.read_text(encoding="utf-8"))
            for p in data.get("providers", []):
                h = (p.get("host") or "").lower()
                if h.startswith("www."):
                    h = h[4:]
                if h:
                    hosts.add(h)
        except Exception as exc:  # noqa: BLE001 — baseline is observability input
            logger.warning("could not read baseline providers: %s", exc)
    return hosts


def _is_known_camp_provider(url: str, known_hosts: set[str]) -> bool:
    from phase_a.camp_hosts import is_camp_host_seed_url

    return host_of(url) in known_hosts or is_camp_host_seed_url(url)


def _provider_display_name(seed_url: str, result: dict | None = None) -> str:
    """Page <title> first segment when captured, else host minus TLD."""
    title = ((result or {}).get("title") or "").strip()
    if title:
        return re.split(r"\s*[|—–-]\s+", title)[0].strip() or title
    import tldextract

    host = host_of(seed_url)
    ext = tldextract.extract(host)
    stem = ".".join(p for p in (ext.subdomain, ext.domain) if p) or host
    return stem.replace(".", " ").title()


_REGISTERISH_PATH_RE = re.compile(r"regist|enroll|signup|sign-up", re.I)


def _best_register_url(result: dict, seed_url: str) -> str:
    from phase_b.registration import is_registration_platform_url

    links = result.get("links") or []
    for l in links:
        u = l.get("url", "")
        if u and is_registration_platform_url(u):
            return u
    seed_host = host_of(seed_url)
    for l in links:
        u = l.get("url", "")
        if u and host_of(u) == seed_host and _REGISTERISH_PATH_RE.search(urlparse(u).path):
            return u
    return seed_url


def _fallback_program_row(seed_url: str, result: dict) -> dict:
    return {
        "name": f"{_provider_display_name(seed_url, result)} — Summer Program",
        "register_url": _best_register_url(result, seed_url),
        "info_url": "",
        "platform": result.get("platform") or "fallback",
        "dates": "",
        "ages": "",
        "price": "",
        "kind": "session",
        "source_url": seed_url,
        "granularity": "program",
        "name_source": "fallback",
        "name_status": "ok",
    }


def apply_provider_fallbacks(
    results: list[dict],
    town: str,
    *,
    known_hosts: set[str] | None = None,
) -> list[dict]:
    """Known camp providers that enumerated 0 sessions still publish one
    provider-level row (granularity="program") so the catalog covers them.
    Unknown hosts stay empty — precision guard."""
    hosts = _known_provider_hosts(town) if known_hosts is None else known_hosts
    out: list[dict] = []
    for res in results:
        seed = res.get("url", "")
        if not res.get("sessions") and seed and _is_known_camp_provider(seed, hosts):
            row = _fallback_program_row(seed, res)
            session_log.trace(
                "fallback_row", f"provider-level row for {host_of(seed)} -> {row['register_url']}"
            )
            res = {**res, "sessions": [row]}
        out.append(res)
    return out


async def enumerate_town(
    town: str,
    *,
    urls: list[str] | None = None,
    concurrency: int = 3,
    candidates_path: Path | str = "data/candidates.csv",
    log_file: Path | str | None = None,
) -> list[dict]:
    """Run platform-aware enumeration for every provider in a town."""
    from shared import fetch_cache
    from phase_b.platforms import reset_render_budget

    fetch_cache.reset()  # one run = one fresh cache
    reset_render_budget()  # Task 2.2: per-run rendered-fetch budget
    provider_urls = urls or load_provider_urls(town, candidates_path)
    log_path = session_log.init(log_file)
    logger.info("Session enumeration log: %s", log_path)

    focus = SETTINGS.get("program_focus", "youth_summer")
    csv_out = camp_sessions_csv(town)
    txt_out = csv_out.with_suffix(".txt")
    session_log.run_start(
        town=town,
        provider_count=len(provider_urls),
        focus=focus,
        session_log_path=str(log_path),
        csv_path=str(csv_out),
        txt_path=str(txt_out),
    )

    concurrency = int(SETTINGS.get("b5_default_concurrency", concurrency))
    sem = asyncio.Semaphore(concurrency)
    total = len(provider_urls)
    counter = {"n": 0}
    t0 = time.monotonic()

    async def run_one(u: str) -> dict:
        async with sem:
            counter["n"] += 1
            idx = counter["n"]
            h = host_of(u)
            session_log.provider_start(url=u, host=h, index=idx, total=total)
            try:
                res = await enumerate_provider(u, town_hint=town)
            except Exception as exc:  # noqa: BLE001
                logger.warning("enumerate failed for %s: %s", u, exc)
                session_log.provider_error(url=u, error=str(exc))
                return {"url": u, "platform": "ERROR", "sessions": [], "dropped": []}

            session_log.sessions_before_save(
                provider_url=u,
                platform=res.get("platform", "?"),
                sessions=res.get("sessions", []),
                dropped=res.get("dropped", []),
                csv_path=str(csv_out),
            )
            session_log.provider_done(
                url=u,
                platform=res.get("platform", "?"),
                kept=len(res.get("sessions", [])),
                dropped=len(res.get("dropped", [])),
                sessions=res.get("sessions", []),
            )
            return res

    results: list[dict] = []
    if concurrency <= 1:
        for u in provider_urls:
            res = await run_one(u)
            results.append(res)
            try:
                added = len(res.get("sessions", []))
                csv_path, txt_path, session_count = write_session_outputs(town, results)
                session_log.output_checkpoint(
                    csv_path=str(csv_path),
                    txt_path=str(txt_path),
                    providers_done=len(results),
                    total_sessions=session_count,
                    added=added,
                )
                logger.info(
                    "B.5 checkpoint: %d providers, %d sessions -> %s",
                    len(results),
                    session_count,
                    csv_path,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("B.5 checkpoint write failed: %s", exc)
    else:
        results = list(await asyncio.gather(*[run_one(u) for u in provider_urls]))

    if SETTINGS.get("b5_cross_provider_dedupe", True):
        results = _dedupe_across_providers(results)

    results = apply_provider_fallbacks(results, town)

    elapsed = time.monotonic() - t0
    total_sessions = sum(len(r.get("sessions", [])) for r in results)
    with_camps = sum(1 for r in results if r.get("sessions"))
    session_log.run_summary(
        town=town,
        providers_checked=len(results),
        providers_with_camps=with_camps,
        total_sessions=total_sessions,
        csv_path=str(camp_sessions_csv(town)),
        txt_path=str(camp_sessions_csv(town).with_suffix(".txt")),
        runtime_s=elapsed,
    )
    return results


def _dedupe_across_providers(results: list[dict]) -> list[dict]:
    """roadmap2 Phase 6: drop funnel duplicates across providers.

    Two providers (lexingtonma.gov and lexrecma.myrec.com) often surface the
    same registration catalog, so the same register_url appears under both. Keep
    the first provider to claim each register_url; drop the duplicate from later
    providers so the town's count isn't inflated by the same camp twice."""
    seen_reg: set[str] = set()
    out: list[dict] = []
    removed = 0
    for res in results:
        kept_sessions = []
        for s in res.get("sessions", []):
            key = normalize_url(s.get("register_url") or s.get("info_url") or "")
            if key and key in seen_reg:
                removed += 1
                continue
            if key:
                seen_reg.add(key)
            kept_sessions.append(s)
        out.append({**res, "sessions": kept_sessions})
    if removed:
        logger.info("Cross-provider dedupe removed %d funnel-duplicate session(s).", removed)
    return out


_TIER_RANK = {"registrable": 2, "needs_trail": 1, "rejected": 0}


def _dedupe_published_rows(rows: list[dict]) -> list[dict]:
    """Task 4.1: canonicalize register URLs and collapse duplicates.

    Identity, in priority order: platform ID (FMID/ProgramID), canonical URL,
    (host, norm_name, dates). Higher quality tier wins a collision."""
    from phase_b.session_quality import classify_session_tier
    from shared.textnorm import norm_name
    from shared.urls import canonical_register_url, register_platform_id

    kept: list[dict] = []
    ranks: list[int] = []
    key_to_idx: dict[tuple, int] = {}
    for row in rows:
        canon = canonical_register_url(
            row.get("register_url", ""), row.get("platform", "")
        )
        row = {**row, "register_url": canon or row.get("register_url", "")}

        keys: list[tuple] = []
        pid = register_platform_id(canon)
        if pid:
            keys.append(("pid", pid))
        if canon:
            keys.append(("url", canon))
        norm = norm_name(row.get("name", ""))
        if norm:
            host = host_of(canon or row.get("source_url", ""))
            keys.append(("hnd", host, norm, (row.get("dates") or "").strip()))

        hit = next((k for k in keys if k in key_to_idx), None)
        if hit is None:
            idx = len(kept)
            kept.append(row)
            ranks.append(_TIER_RANK.get(classify_session_tier(row)[0], 0))
            for k in keys:
                key_to_idx[k] = idx
            continue
        idx = key_to_idx[hit]
        rank = _TIER_RANK.get(classify_session_tier(row)[0], 0)
        if rank > ranks[idx]:
            kept[idx] = row
            ranks[idx] = rank
        for k in keys:
            key_to_idx.setdefault(k, idx)
    return kept


def write_session_outputs(
    town: str,
    results: list[dict],
    *,
    output_dir: Path | str | None = None,
) -> tuple[Path, Path, int]:
    """Write camp_sessions CSV + human-readable TXT. Returns (csv_path, txt_path, total)."""
    _ = output_dir
    town_phase_dir(town, "phase_b5")
    csv_path = camp_sessions_csv(town)
    txt_path = csv_path.with_suffix(".txt")
    quarantine_path = csv_path.with_name("camp_sessions_quarantine.csv")

    # roadmap2 Phase 5: validation gate. Every published row must pass
    # validate_session; failures go to the quarantine CSV with a reason, never
    # the deliverable. Gated by b5_validation_gate (default on).
    from config.settings import SETTINGS
    from phase_c.junk_audit import is_fabrication_blocked, validate_session

    gate_on = bool(SETTINGS.get("b5_validation_gate", True))

    # Task 1.2 dedup guard: a host with >=1 real session row drops its stale
    # provider-level (granularity="program") fallback rows.
    hosts_with_sessions: set[str] = set()
    for res in results:
        for s in res.get("sessions", []):
            if (s.get("granularity") or "session") == "session":
                hosts_with_sessions.add(host_of(s.get("source_url") or res.get("url", "")))

    quarantined: list[dict] = []
    fabricated_blocked = 0
    program_rows_dropped = 0
    publishable: list[dict] = []
    for res in results:
        for s in res.get("sessions", []):
            # granularity: "session" (a specific registrable camp) unless an
            # upstream stage marked the row "program" (provider-level).
            s = {**s, "granularity": s.get("granularity") or "session"}
            if (
                s["granularity"] == "program"
                and host_of(s.get("source_url") or res.get("url", "")) in hosts_with_sessions
            ):
                program_rows_dropped += 1
                continue
            ok, reasons = (True, []) if not gate_on else validate_session(s)
            if not ok:
                if is_fabrication_blocked(s):
                    fabricated_blocked += 1
                quarantined.append({**s, "_quarantine_reason": ";".join(reasons)})
                continue
            publishable.append(s)

    publishable = _dedupe_published_rows(publishable)

    total = 0
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=SESSION_CSV_COLUMNS)
        w.writeheader()
        for s in publishable:
            w.writerow({c: s.get(c, "") for c in SESSION_CSV_COLUMNS})
            total += 1

    if quarantined:
        with open(quarantine_path, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(
                f, fieldnames=[*SESSION_CSV_COLUMNS, "name_status", "extract_status", "_quarantine_reason"]
            )
            w.writeheader()
            for s in quarantined:
                w.writerow(
                    {
                        **{c: s.get(c, "") for c in SESSION_CSV_COLUMNS},
                        "name_status": s.get("name_status", ""),
                        "extract_status": s.get("extract_status", ""),
                        "_quarantine_reason": s.get("_quarantine_reason", ""),
                    }
                )

    try:
        session_log.validation_gate_summary(
            town=town,
            published=total,
            quarantined=len(quarantined),
            fabricated_blocked=fabricated_blocked,
        )
    except Exception:  # noqa: BLE001 — logging must never break the write
        pass

    lines = [
        f"{town.upper()} — CAMP SESSIONS (youth summer focus)",
        f"Providers: {len(results)}   Total camps/sessions: {total}",
        "=" * 70,
        "",
        "## COVERAGE SUMMARY",
        f"{'Host':<40} {'Platform':<16} {'Kept':>5} {'Dropped':>8}",
        "-" * 70,
    ]
    for res in sorted(results, key=lambda r: host_of(r["url"])):
        kept = len(res.get("sessions", []))
        dropped = len(res.get("dropped", []))
        lines.append(
            f"{host_of(res['url']):<40} {res.get('platform', '?'):<16} {kept:>5} {dropped:>8}"
        )
    lines.extend(["", "=" * 70, ""])

    for res in sorted(results, key=lambda r: -len(r.get("sessions", []))):
        sessions = res.get("sessions", [])
        if not sessions:
            continue
        lines.append(f"\n## {host_of(res['url'])}  [{res['platform']}]  ({len(sessions)})")
        lines.append(f"   source: {res['url']}")
        dropped = res.get("dropped", [])
        if dropped:
            lines.append(f"   dropped (off-focus): {len(dropped)}")
        for s in sessions:
            meta = " | ".join(x for x in [s.get("dates", ""), s.get("ages", ""), s.get("price", "")] if x)
            tag = "" if s.get("kind") == "session" else "  (portal)"
            lines.append(f"   - {s['name']}{tag}" + (f"  [{meta}]" if meta else ""))
            lines.append(f"     {s['register_url']}")

    empties = [r for r in results if not r.get("sessions")]
    if empties:
        lines.append("\n\n## 0 camps — needs JS/Firecrawl or blocked:")
        for r in empties:
            plat = r.get("platform", "?")
            dropped = len(r.get("dropped", []))
            drop_note = f"  ({dropped} dropped off-focus)" if dropped else ""
            lines.append(f"   - {host_of(r['url'])}  [{plat}]{drop_note}")
            lines.append(f"     seed: {r['url']}")

    txt_path.write_text("\n".join(lines), encoding="utf-8")
    refresh_town_index(town)
    return csv_path, txt_path, total


def print_enumeration_summary(results: list[dict]) -> int:
    """Console summary; returns total session count."""
    total = 0
    for res in results:
        n = len(res.get("sessions", []))
        d = len(res.get("dropped", []))
        drop_note = f"  (-{d} off-focus)" if d else ""
        print(f"  [{res.get('platform', '?'):16}] {n:3} camps{drop_note}  <- {res['url']}")
        total += n
    return total
