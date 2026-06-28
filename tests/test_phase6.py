"""roadmap2 Phase 6: fetch cache, cross-provider dedupe, MyRec verdict policy."""

from __future__ import annotations

from config import settings
from shared import fetch_cache
from phase_b.sessions import _dedupe_across_providers
from phase_b.verdict_policy import apply_verdict_policy


def test_fetch_cache_put_get_and_reset():
    fetch_cache.reset()
    assert fetch_cache.get("https://x.org/a", kind="page") is None
    fetch_cache.put("https://x.org/a", "hello", [{"url": "https://x.org/b"}], kind="page")
    hit = fetch_cache.get("https://x.org/a", kind="page")
    assert hit is not None
    text, links = hit
    assert text == "hello"
    # Mutating returned links must not corrupt the cache (copies returned).
    links.append({"url": "mutated"})
    text2, links2 = fetch_cache.get("https://x.org/a", kind="page")
    assert len(links2) == 1
    fetch_cache.reset()
    assert fetch_cache.get("https://x.org/a", kind="page") is None


def test_fetch_cache_skips_empty():
    fetch_cache.reset()
    fetch_cache.put("https://x.org/empty", "", [], kind="page")
    assert fetch_cache.get("https://x.org/empty", kind="page") is None


def test_cross_provider_dedupe_merges_funnel_duplicates():
    reg = "https://lexrecma.myrec.com/programs/program_details.aspx?id=9"
    results = [
        {"url": "https://lexingtonma.gov", "platform": "myrec",
         "sessions": [{"name": "Soccer", "register_url": reg}]},
        {"url": "https://lexrecma.myrec.com", "platform": "myrec",
         "sessions": [
             {"name": "Soccer", "register_url": reg},  # duplicate funnel
             {"name": "Art", "register_url": reg.replace("id=9", "id=10")},
         ]},
    ]
    orig = settings.SETTINGS.get("b5_cross_provider_dedupe", True)
    settings.SETTINGS["b5_cross_provider_dedupe"] = True
    try:
        deduped = _dedupe_across_providers(results)
    finally:
        settings.SETTINGS["b5_cross_provider_dedupe"] = orig
    total = sum(len(r["sessions"]) for r in deduped)
    assert total == 2  # Soccer once + Art once, not 3


def test_myrec_verdict_policy_ships_needs_js():
    s = {"platform": "myrec", "parent_verdict": "unverified", "parent_can_register": True}
    out = apply_verdict_policy(s)
    assert out["parent_verdict"] == "needs_js"
    assert out["parent_can_register"] is False


def test_myrec_verdict_policy_keeps_confirmed_parent_ready():
    s = {"platform": "myrec", "parent_verdict": "parent_ready", "parent_can_register": True}
    out = apply_verdict_policy(s)
    assert out["parent_verdict"] == "parent_ready"


def test_verdict_policy_ignores_other_platforms():
    s = {"platform": "webtrac", "parent_verdict": "unverified"}
    assert apply_verdict_policy(s) == s
