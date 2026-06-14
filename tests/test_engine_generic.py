"""Phase 5: LLM guard + generic path — offline."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from engine.extract.generic import GenericExtractor, jsonld_events, score_follow_links
from engine.extract.llm import extract_programs
from engine.model import Provider


def test_llm_guard_raises_under_400_chars():
    with pytest.raises(ValueError, match="R3.2"):
        extract_programs("x" * 399, "https://x.org", "Lexington")


def test_llm_failure_returns_none():
    with patch("requests.post", side_effect=Exception("down")):
        with patch("engine.extract.llm.requests.post", side_effect=__import__("requests").RequestException("down")):
            assert extract_programs("y" * 500, "https://x.org", "Lexington") is None


class _Stub:
    def __init__(self, pages):
        self.pages = pages
        self.log = []

        class _C:
            def fetched_this_run(self):
                return {}

            def put(self, *a, **k):
                pass

            def get(self, url):
                return None

        self.cache = _C()

    def fetch_text(self, url, *, budget=None):
        return self.pages.get(url, ("", [], ""))


def _prov(seed):
    return Provider(name="x", host="camp.org", town="Lexington", seed_url=seed, vendor="unknown")


def test_generic_empty_site_gaps_with_zero_llm_calls(monkeypatch):
    calls = []
    monkeypatch.setattr("engine.extract.llm.extract_programs",
                        lambda *a, **k: calls.append(1))

    async def fake_render(url, **kw):
        return ("", [], "")

    import engine.fetch.render as rm

    monkeypatch.setattr(rm, "fetch_rendered", fake_render)
    res = asyncio.run(GenericExtractor().extract(_prov("https://camp.org/x"), _Stub({})))
    assert res.gap is not None and res.gap.reason in ("empty", "blocked")
    assert calls == []                       # R3.2: no LLM on thin pages


def test_generic_marketing_site_yields_candidates(monkeypatch):
    seed = "https://camp.org/summer"
    text = ("Welcome to Camp Maple! Our youth summer programs: Soccer Camp ages 6-12 "
            "July 7-11 $300. Art Camp ages 5-10 July 14-18 $280. " * 8)
    pages = {seed: (text, [], "<html>no jsonld</html>")}

    monkeypatch.setattr(
        "engine.extract.llm.extract_programs",
        lambda t, u, town: [{"name": "Soccer Camp", "dates": "July 7-11", "ages": "6-12", "price": "$300"},
                            {"name": "Art Camp", "dates": "July 14-18", "ages": "5-10", "price": "$280"}],
    )
    res = asyncio.run(GenericExtractor().extract(_prov(seed), _Stub(pages)))
    assert res.gap is None
    names = {p.name for p in res.programs}
    assert names == {"Soccer Camp", "Art Camp"}
    assert all(not p.camp_scoped for p in res.programs)   # generic earns evidence


def test_jsonld_and_follow_scoring():
    html = ('<script type="application/ld+json">{"@type":"Event","name":"Nature Camp",'
            '"startDate":"2026-07-06"}</script>')
    evs = jsonld_events(html)
    assert evs and evs[0]["name"] == "Nature Camp"
    links = [{"url": "https://camp.org/summer-camp", "text": "Summer Camp"},
             {"url": "https://camp.org/about", "text": "About"},
             {"url": "https://other.org/camp", "text": "Camp"},
             {"url": "https://camp.org/brochure.pdf", "text": "Camp PDF"}]
    follows = score_follow_links("https://camp.org/", links)
    assert follows == ["https://camp.org/summer-camp"]


def test_activity_menu_demoted():
    """Camp Middlesex finding: activity areas on one page are not programs."""
    from engine.extract.generic import demote_activity_menus

    menu = [{"name": n, "info_url": "https://camp.org/program-areas",
             "ages": "ages 8", "dates": "", "price": ""}
            for n in ["Archery", "Gaga", "Soccer", "Swimming", "Ceramics",
                      "Dance", "Nature", "Riflery", "Boating", "Cooking"]]
    real = [{"name": "Junior Camp", "info_url": "https://camp.org/about-us/program",
             "ages": "Ages 8-12", "dates": "June 28 - July 10", "price": ""},
            {"name": "Teen Camp", "info_url": "https://camp.org/about-us/program",
             "ages": "Ages 13-15", "dates": "June 28 - July 10", "price": ""}]
    out = demote_activity_menus(menu + real)
    names = {r["name"] for r in out}
    assert "Junior Camp" in names and "Teen Camp" in names
    assert "Archery" not in names and "Gaga" not in names


def test_catalog_multipage_enumerates_all_camps(monkeypatch):
    """Running Brook finding: a site with one page per camp (incl. keyword-less
    sub-camp slugs under a section) must enumerate ALL of them, not just the
    first few — and with ZERO LLM calls (deterministic per-page extraction)."""
    pad = " Summer camp fun for kids in Waltham. " * 20
    seed = "https://camp.org/"
    pages = {
        seed: (
            "Welcome to Running Brook." + pad,
            [{"url": "https://camp.org/adventures", "text": "Adventures"},
             {"url": "https://camp.org/day-camp/day-camp", "text": "Day Camp"}],
            "<html><h1>Running Brook</h1></html>",
        ),
        # Section page: no own age/date -> not itself a camp record; links to subs.
        "https://camp.org/adventures": (
            "Our Adventures programs for older campers." + pad,
            [{"url": "https://camp.org/adventures/trekkers-grades-5-6", "text": "Trekkers"},
             {"url": "https://camp.org/adventures/voyagers-grades-7-8", "text": "Voyagers"},
             {"url": "https://camp.org/adventures/adventures-faqs", "text": "FAQs"}],
            "<html><h1>Adventures</h1></html>",
        ),
        "https://camp.org/adventures/trekkers-grades-5-6": (
            "Trekkers is for ages 10-12 exploring the outdoors. June 23 - June 27." + pad,
            [], "<html><h1>Trekkers (Grades 5-6) - Running Brook</h1></html>",
        ),
        "https://camp.org/adventures/voyagers-grades-7-8": (
            "Voyagers is for ages 13-14 on extended trips. July 7 - July 11." + pad,
            [], "<html><h1>Voyagers (Grades 7-8) - Running Brook</h1></html>",
        ),
        "https://camp.org/adventures/adventures-faqs": (
            "Frequently asked questions about adventures." + pad, [],
            "<html><h1>Adventures FAQs</h1></html>",
        ),
        "https://camp.org/day-camp/day-camp": (
            "Day Camp for ages 4-12 all summer. June 23 - August 21." + pad,
            [], "<html><h1>Day Camp - Running Brook</h1></html>",
        ),
    }

    # LLM listing-pass returns nothing here; the camps must come from the
    # deterministic per-page detail extraction (incl. depth-2 sub-camps).
    monkeypatch.setattr("engine.extract.llm.extract_programs", lambda *a, **k: [])
    res = asyncio.run(GenericExtractor().extract(_prov(seed), _Stub(pages)))
    names = {p.name for p in res.programs}
    assert "Trekkers" in names                    # keyword-less sub-camp, depth-2
    assert "Voyagers" in names
    assert "Day Camp" in names
    assert "Adventures FAQs" not in names         # non-detail leaf skipped
    assert "Adventures" not in names              # section page (no own evidence)


def test_slug_name_and_age():
    """Detail-page name/age come from the slug (reliable), not the banner <h1>."""
    from engine.extract.generic import slug_age, slug_name

    assert slug_name("https://x.org/creative-arts/creative-arts-camp") == "Creative Arts Camp"
    assert slug_name("https://x.org/adventures/trekkers-grades-5-6") == "Trekkers"
    assert slug_name("https://x.org/excursions-ages-4-12") == "Excursions"
    assert slug_name("https://x.org/programs/1728207") == ""  # id-like -> heading
    assert slug_age("https://x.org/a/trekkers-grades-5-6") == "Grades 5-6"
    assert slug_age("https://x.org/a/explorers-ages-7-12") == "Ages 7-12"
    assert slug_age("https://x.org/a/day-camp") == ""


def test_detail_name_prefers_slug_over_banner_h1():
    """Running Brook finding: the page <h1> is a repeated site banner; the camp's
    real name is its slug."""
    from engine.extract.generic import _detail_record

    rec = _detail_record(
        "https://runningbrook.org/creative-arts/creative-arts-camp",
        "Creative Arts program for campers completed grades 3-8.",
        "<html><h1>Running Brook Camps</h1></html>",   # banner, not the camp name
    )
    assert rec and rec["name"] == "Creative Arts Camp"


def test_gate_adult_fitness_class_rejected():
    """'Active Agers' finding: adult fitness-class pages don't publish."""
    from engine.model import Program, Session
    from engine.validate.gate import gate_program

    text = ("Active Agers with Carolyn Gregoire. In this class we will have fun "
            "while increasing our strength, bone health, balance, flexibility, and "
            "cardiovascular fitness. Muscle conditioning, Yoga and Pilates postures. "
            "Personal trainer for over 12 years. June sessions. " * 6)
    sess = Session(name="Active Agers", info_url="https://x/p", dates="June 9")
    prog = Program(name="Active Agers", provider_id="p", info_url="https://x/p")
    prog.sessions = [sess]
    res = gate_program(prog, fetched_text={"https://x/p": text})
    assert not res.published


def test_camp_page_priority_scoping():
    """YMCA/JCC/LifeTime feedback: keep camp-page records, drop fitness/
    after-school/enrichment sections."""
    from engine.extract.generic import scope_to_camp_pages

    recs = [
        {"name": "Camp Chickami", "info_url": "https://y.org/camps", "ages": "", "dates": ""},
        {"name": "LIT Sessions", "info_url": "https://y.org/camp-pikati", "ages": "grades 6-9", "dates": "June 22-26"},
        {"name": "Kettlebell Foundations", "info_url": "https://y.org/fitness-programs", "ages": "age 18", "dates": ""},
        {"name": "Crafty Kids", "info_url": "https://y.org/programs/education-care-camp/enrichment", "ages": "4-9", "dates": ""},
        {"name": "Wells Family Camp", "info_url": "https://y.org/find-program", "ages": "", "dates": ""},
        {"name": "Summer at the J", "info_url": "https://j.org/summer-camp", "ages": "", "dates": "June 22"},
        {"name": "Spinning Core", "info_url": "https://j.org/health-wellness/fitness-class-descriptions", "ages": "", "dates": ""},
    ]
    names = {r["name"] for r in scope_to_camp_pages(recs)}
    assert names == {"Camp Chickami", "LIT Sessions", "Summer at the J"}


def test_gate_off_season_and_field_evidence_only():
    """Round-2 feedback: winter/april clinics drop; page-text 'June' no longer
    rescues adult rows without field evidence."""
    from engine.model import Program, Session
    from engine.validate.gate import gate_program

    rich = "Soccer clinics all year. Registration June hours. " * 20
    winter = Session(name="Winter Skills Clinics", info_url="https://x/w", dates="Jan 5 - Mar 9")
    taichi = Session(name="Tai Chi w/Constance", info_url="https://x/t")
    blue = Session(name="Blue Sox Baseball Camp", info_url="https://x/b",
                   dates="July 7-11", ages="7-10")
    for sess, ok in ((winter, False), (taichi, False), (blue, True)):
        prog = Program(name=sess.name, provider_id="p", info_url=sess.info_url)
        prog.sessions = [sess]
        res = gate_program(prog, fetched_text={sess.info_url: f"{sess.name}. {rich}"})
        assert bool(res.published) is ok, sess.name


def test_nav_card_batches_dropped():
    """US Sports finding: same-page records with identical dates+ages are nav cards."""
    from engine.extract.generic import demote_activity_menus

    cards = [{"name": n, "info_url": "https://u.com/nike-euro-camps",
              "dates": "August 26", "ages": "age 5", "price": ""}
             for n in ["Euro Sports Camps", "Nike - Chelsea Football Camp",
                       "Nike Total Football Camp", "Bill Pilat's Goalie School"]]
    real = [{"name": f"Summer Week #{i} Multi-Sports Camp", "info_url": "https://v.com/camps",
             "dates": d, "ages": "5-13", "price": ""}
            for i, d in enumerate(["Jun 15-19", "Jun 22-26", "Jul 6-10"], 1)]
    out = demote_activity_menus(cards + real)
    names = {r["name"] for r in out}
    assert not any("Euro" in n or "Chelsea" in n for n in names)
    assert sum(1 for n in names if "Multi-Sports" in n) == 3  # distinct dates kept


def test_gate_adult_min_age_rejected():
    """Round-2: extracted 'Ages: 18 and up' is adult evidence."""
    from engine.model import Program, Session
    from engine.validate.gate import gate_program

    sess = Session(name="Line Dance with Paul", info_url="https://x/d",
                   dates="June 22 - August 10", ages="Ages: 18 - 99")
    prog = Program(name="Line Dance with Paul", provider_id="p", info_url="https://x/d")
    prog.sessions = [sess]
    res = gate_program(prog, fetched_text={"https://x/d": "Line Dance with Paul. " * 40})
    assert not res.published


def test_gate_clinical_program_rejected():
    """MGH Aspire finding: hospital group programming is not a camp."""
    from engine.model import Program, Session
    from engine.validate.gate import gate_program

    text = ("Aspire Group Programming. Our clinicians provide social-skills "
            "group therapy for children ages 5-13. Referral required; treatment "
            "plans reviewed with families. Summer groups run June-August. " * 8)
    sess = Session(name="Aspire Group Programming", info_url="https://h.org/a",
                   ages="ages 5-13", dates="June - August")
    prog = Program(name="Aspire Group Programming", provider_id="p", info_url="https://h.org/a")
    prog.sessions = [sess]
    res = gate_program(prog, fetched_text={"https://h.org/a": text})
    assert not res.published
    assert "clinical" in res.gaps[0].evidence
