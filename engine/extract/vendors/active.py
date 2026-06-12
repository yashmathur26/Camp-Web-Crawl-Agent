"""ACTIVE (campscui.active.com) extractor — NEW (task 3.6).

The org page is a SPA whose session data loads from
  /external/json/seasons                     (org context via the page session)
  /external/json/seasons/{id}/sessions      ({count, sessions:[...]})
Direct HTTP and even in-page fetch are NotAllowed; the working data path is to
load the org page once with Playwright and CAPTURE the SPA's own /sessions
response (discovered in the 3.6 spike; fixture: tests/fixtures/active/munroe.json).

Season selection: registry may pin a season id; otherwise pick seasons whose
name matches camp/summer. info_url: the org page with ?season= anchor — the
rendered season page lists every session (content-rich); per-session ACTIVE
detail pages require checkout context, so the season catalog page is the
content-rich page a parent sees right before registration.
"""

from __future__ import annotations

import asyncio
import re

from engine.extract.base import ExtractResult, Extractor, group_sessions_into_programs
from engine.fetch.client import Budget, FetchClient
from engine.model import Gap, Program, Provider, Session

_CAMP_SEASON_RE = re.compile(r"camp|summer", re.I)


def _fmt_date(d: dict | None) -> str:
    if not isinstance(d, dict) or not d.get("month"):
        return ""
    return f"{int(d['month']):02d}/{int(d.get('day', 1)):02d}/{d.get('year', '')}"


def _ages(sess: dict) -> str:
    # `restrictions` is a LIST of restriction dicts in the live payload.
    restrictions: dict = {}
    raw = sess.get("restrictions")
    if isinstance(raw, dict):
        restrictions = raw
    elif isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                restrictions.update({k: v for k, v in item.items() if v not in (None, "")})
    lo = restrictions.get("minAge") or sess.get("minAge")
    hi = restrictions.get("maxAge") or sess.get("maxAge")
    if lo or hi:
        try:
            if lo and int(lo) >= 18:
                return "ages 18+"  # adult program — gate's adult check keys off this
        except (TypeError, ValueError):
            pass
        return f"ages {lo or '?'}-{hi or '?'}"
    glo = restrictions.get("minGrade") or sess.get("minGrade")
    ghi = restrictions.get("maxGrade") or sess.get("maxGrade")
    if glo or ghi:
        return f"grades {glo or '?'}-{ghi or '?'}"
    return ""


def _price(sess: dict) -> str:
    tuitions = sess.get("tuitions") or []
    for t in tuitions:
        amount = t.get("amount") or t.get("price")
        if amount:
            return f"${amount}"
    return ""


def map_sessions(payload: dict, *, season_url: str, extractor: str) -> list[Session]:
    out = []
    for raw in payload.get("sessions") or []:
        name = re.sub(r"\s+", " ", str(raw.get("name") or "")).strip()
        if not name:
            continue
        start, end = _fmt_date(raw.get("startDate")), _fmt_date(raw.get("endDate"))
        dates = f"{start} - {end}" if start and end else start or end
        out.append(
            Session(
                name=name, info_url=season_url, register_url=season_url,
                dates=dates, ages=_ages(raw), price=_price(raw),
                extractor=extractor,
            )
        )
    return out


async def capture_season_sessions(
    org_id: str, *, season_id: str = "", timeout_s: float = 25.0
) -> tuple[list[dict], dict[str, dict], str]:
    """Load the org page once; capture the SPA's seasons + sessions responses.
    Returns (seasons, {season_id: sessions_payload}, rendered_text)."""
    from playwright.async_api import async_playwright

    seasons: list[dict] = []
    payloads: dict[str, dict] = {}
    url = f"https://campscui.active.com/orgs/{org_id}"
    if season_id:
        url += f"?season={season_id}"
    text = ""

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page()

            async def on_resp(resp):
                u = resp.url
                try:
                    if u.endswith("/external/json/seasons"):
                        data = await resp.json()
                        if isinstance(data, list):
                            seasons.extend(data)
                    else:
                        m = re.search(r"/external/json/seasons/(\d+)/sessions", u)
                        if m:
                            data = await resp.json()
                            sid = m.group(1)
                            prev = payloads.get(sid)
                            if prev:
                                # paginated responses: merge sessions by id
                                by_id = {
                                    str(s.get("id")): s
                                    for s in (prev.get("sessions") or [])
                                }
                                for s in data.get("sessions") or []:
                                    by_id[str(s.get("id"))] = s
                                data = {**prev, **data, "sessions": list(by_id.values())}
                            payloads[sid] = data
                except Exception:  # noqa: BLE001 — non-JSON bodies are irrelevant
                    pass

            page.on("response", on_resp)
            await page.goto(url, wait_until="domcontentloaded", timeout=int(timeout_s * 1000))
            for _ in range(int(timeout_s * 2)):
                if payloads and seasons:
                    break
                await asyncio.sleep(0.5)
            # The sessions endpoint paginates (count > page size); scrolling
            # makes the SPA fetch the remaining pages — merge them by id.
            for _ in range(8):
                done = all(
                    len(p.get("sessions") or []) >= int(p.get("count") or 0)
                    for p in payloads.values()
                )
                if done and payloads:
                    break
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await asyncio.sleep(1.0)
            text = await page.evaluate("document.body ? document.body.innerText : ''")
        finally:
            await browser.close()
    return seasons, payloads, text


class ActiveExtractor(Extractor):
    vendor = "active"

    async def extract(self, provider: Provider, fetch: FetchClient) -> ExtractResult:
        budget = Budget()
        if not provider.org_id:
            return ExtractResult(
                gap=Gap(provider_id=provider.provider_id, reason="needs_review",
                        evidence="active vendor without org_id in registry",
                        suggested_action="resolve org_id from the marketing site"),
            )

        # Pass 1: discover seasons (and whatever sessions the default loads).
        budget.check()
        seasons, payloads, text = await capture_season_sessions(provider.org_id)
        camp_seasons = [s for s in seasons if _CAMP_SEASON_RE.search(str(s.get("name", "")))]

        if not camp_seasons and not payloads:
            return ExtractResult(
                gap=Gap(provider_id=provider.provider_id, reason="empty",
                        evidence=f"no camp/summer season on org {provider.org_id}; "
                                 f"seasons={[s.get('name') for s in seasons]}",
                        suggested_action="re-check when the season catalog publishes"),
            )

        sessions: list[Session] = []
        scoped_sessions: list[Session] = []
        for season in camp_seasons:
            sid = str(season.get("id"))
            # R4.2 applies only to a true CAMP season; a "Summer Classes &
            # Workshops" season carries adult offerings and must earn evidence
            # (Phase-3 live finding: adult ceramics published via camp-scope).
            is_camp_season = "camp" in str(season.get("name", "")).lower()
            season_url = f"https://campscui.active.com/orgs/{provider.org_id}?season={sid}"
            payload = payloads.get(sid)
            if payload is None:
                budget.check()
                _s, more, season_text = await capture_season_sessions(
                    provider.org_id, season_id=sid
                )
                payload = more.get(sid) or {}
                if season_text.strip():
                    fetch.cache.put(season_url, season_text, [])
            else:
                if text.strip():
                    fetch.cache.put(season_url, text, [])
            mapped = map_sessions(payload, season_url=season_url, extractor=self.vendor)
            (scoped_sessions if is_camp_season else sessions).extend(mapped)

        if not sessions and not scoped_sessions:
            return ExtractResult(
                gap=Gap(provider_id=provider.provider_id, reason="render_failed",
                        evidence=f"camp season(s) present but sessions payload not captured "
                                 f"({[s.get('name') for s in camp_seasons]})",
                        suggested_action="retry; inspect SPA endpoint changes"),
            )

        # True camp seasons → camp-scoped (R4.2); class/workshop seasons earn
        # publication through per-row evidence at the gate.
        programs = group_sessions_into_programs(provider, scoped_sessions, camp_scoped=True)
        programs += group_sessions_into_programs(provider, sessions, camp_scoped=False)
        return ExtractResult(programs=programs, fetch_log=fetch.log)
