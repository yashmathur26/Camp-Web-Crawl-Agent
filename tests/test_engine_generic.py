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
