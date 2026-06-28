"""Tests for agentic gap hole search dedupe and dynamic sizing."""

from datetime import datetime, timezone

from phase_c.agentic_gap import _hole_recently_searched, plan_round_searches


def test_hole_cache_recent():
    cache = {"ymca_webtrac": datetime.now(timezone.utc).isoformat()}
    assert _hole_recently_searched("ymca_webtrac", cache, days=7) is True
    assert _hole_recently_searched("other_hole", cache, days=7) is False


def test_plan_round_searches_uses_hole_count():
    holes = [
        {"hole_id": f"h{i}", "search_query": f"query {i}", "priority": i}
        for i in range(12)
    ]
    plan = plan_round_searches(holes, cache={}, searched_ids=set(), max_ceiling=100)
    assert plan["ideal_searches"] == 12
    assert plan["planned_searches"] == 12
    assert plan["deferred_over_ceiling"] == 0


def test_plan_round_searches_respects_ceiling():
    holes = [
        {"hole_id": f"h{i}", "search_query": f"query {i}"}
        for i in range(25)
    ]
    plan = plan_round_searches(holes, cache={}, searched_ids=set(), max_ceiling=10)
    assert plan["ideal_searches"] == 25
    assert plan["planned_searches"] == 10
    assert plan["deferred_over_ceiling"] == 15


def test_plan_skips_cached_and_searched():
    holes = [
        {"hole_id": "done", "search_query": "q1"},
        {"hole_id": "cached", "search_query": "q2"},
        {"hole_id": "fresh", "search_query": "q3"},
    ]
    cache = {"cached": datetime.now(timezone.utc).isoformat()}
    plan = plan_round_searches(
        holes, cache=cache, searched_ids={"done"}, max_ceiling=100
    )
    assert plan["ideal_searches"] == 1
    assert plan["searchable_holes"][0]["hole_id"] == "fresh"
