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
