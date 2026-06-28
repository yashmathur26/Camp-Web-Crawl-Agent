"""Part C Stages 3-6: matrix, exhausted memory, geo registry, orchestrator, manifest."""

from unittest.mock import patch

from config.town_geo import distance_between, towns_by_population, towns_within
from phase_c.agentic_gap import _hole_recently_searched, _record_attempt, exhausted_categories
from phase_c.coverage_matrix import build_matrix, coverage_summary


def test_geo_radius_and_population_order():
    assert "Arlington" in towns_within("Lexington", 10)
    assert "Lowell" not in towns_within("Lexington", 10)      # ~15 mi away
    d = distance_between("Lexington", "Arlington")
    assert 2 < d < 8
    assert towns_by_population()[0] == "Cambridge"
    assert len(towns_by_population()) == 54


def test_exhausted_state_memory():
    cache = {}
    for _ in range(2):                       # 2 rounds x 3 variants, no hosts
        _record_attempt(cache, "missing_category_fencing", found_host=False, variants_tried=3)
    e = cache["missing_category_fencing"]
    assert e["status"] == "exhausted" and e["attempts"] == 6
    assert "fencing" in exhausted_categories(cache)
    # exhausted entries stay quiet for the long TTL
    assert _hole_recently_searched("missing_category_fencing", cache, days=7)
    # success resets to filled
    _record_attempt(cache, "missing_category_pottery", found_host=True, variants_tried=1)
    assert cache["missing_category_pottery"]["status"] == "filled"


def test_v1_cache_entries_migrate():
    cache = {"missing_category_chess": "2026-06-01T00:00:00+00:00"}
    assert not _hole_recently_searched("missing_category_chess", cache, days=7)


def test_coverage_matrix_statuses(tmp_path, monkeypatch):
    import phase_c.categorizer as cz

    monkeypatch.setattr(cz, "_CACHE_PATH", tmp_path / "c.json")
    sessions = [
        {"name": "Super Soccer Stars", "parent_verdict": "parent_ready",
         "register_url": "https://x.org/1"},
        {"name": "Pottery Wheel Camp", "parent_verdict": "brochure_only",
         "register_url": "https://y.org/2"},
    ]
    rows = build_matrix(
        "Lexington", sessions,
        exhausted={"fencing"},
        shared_coverage={"gymnastics": "Woburn"},
        use_llm=False,
    )
    by_cat = {r["category"]: r for r in rows}
    assert by_cat["soccer"]["status"] == "covered"
    assert by_cat["pottery"]["status"] == "hole"           # brochure-only != covered
    assert by_cat["fencing"]["status"] == "exhausted"
    assert by_cat["gymnastics"]["status"] == "covered_via:Woburn"
    s = coverage_summary(rows)
    assert s["core_total"] == 17 and s["covered"] >= 2


def test_registry_share_and_skip(tmp_path, monkeypatch):
    import phase_c.categorizer as cz
    import phase_c.provider_registry as pr

    monkeypatch.setattr(cz, "_CACHE_PATH", tmp_path / "c.json")
    monkeypatch.setattr(pr, "REGISTRY_PATH", tmp_path / "reg.json")
    sessions = [{"name": "Gymnastics Camp", "parent_verdict": "parent_ready",
                 "register_url": "https://gym.com/reg"}]
    pr.register_sessions("Woburn", sessions, use_llm=False)
    cov = pr.registry_coverage("Lexington")                 # Woburn ~5mi away
    assert cov.get("gymnastics") == "Woburn"
    assert not pr.registry_coverage("Lowell").get("gymnastics")  # out of radius
    holes = [{"hole_id": "missing_category_gymnastics", "category": "gymnastics",
              "search_query": "q", "query_variants": ["q"]}]
    keep, skipped = pr.skippable_holes("Lexington", holes)
    assert keep == [] and skipped == {"gymnastics": "Woburn"}


def test_part_c_resume_skips_done(tmp_path, monkeypatch):
    import phase_c.part_c as pc

    monkeypatch.setattr(pc, "PROGRESS_PATH", tmp_path / "p.json")
    monkeypatch.setattr(pc, "LEDGER_PATH", tmp_path / "l.csv")
    calls = []
    monkeypatch.setattr(pc, "load_sessions_for_verify",
                        lambda t, **k: [{"name": "x"}])
    monkeypatch.setattr(pc, "run_agentic_gap",
                        lambda t, **k: calls.append(t) or
                        {"total_searches": 1, "new_sessions": 0, "coverage": {"core_pct": 90}})
    pc.run_part_c(towns=["Lexington", "Arlington"], resume=True)
    assert calls == ["Lexington", "Arlington"]
    calls.clear()
    pc.run_part_c(towns=["Lexington", "Arlington"], resume=True)
    assert calls == []                                      # checkpoint resume


def test_manifest_dedup_and_tags(tmp_path, monkeypatch):
    import phase_c.categorizer as cz
    import shared.handoff as ho
    import phase_c.provider_registry as pr

    monkeypatch.setattr(cz, "_CACHE_PATH", tmp_path / "c.json")
    monkeypatch.setattr(pr, "REGISTRY_PATH", tmp_path / "reg.json")
    monkeypatch.setattr(ho, "MANIFEST_CSV", tmp_path / "m.csv")
    monkeypatch.setattr(ho, "MANIFEST_JSON", tmp_path / "m.json")
    pr.register_sessions("Lexington", [
        {"name": "Chess Summer Clinic", "parent_verdict": "parent_ready",
         "register_url": "https://chess.org/reg"},
        {"name": "Chess Camp Week 2", "parent_verdict": "parent_ready",
         "register_url": "https://chess.org/reg2"},
    ], use_llm=False)
    rows = ho.build_manifest()
    assert len(rows) == 1                                   # deduped by host
    assert rows[0]["priority"] == 1 and "chess" in rows[0]["categories"]
    assert "Lexington" in rows[0]["towns_served"]
    ho.write_manifest()
    assert (tmp_path / "m.csv").exists()


def test_demand_ranker_orders_holes(tmp_path, monkeypatch):
    """Operator request: searches attack high-demand holes first."""
    import phase_a.demand_ranker as dr

    monkeypatch.setattr(dr, "_CACHE_PATH", tmp_path / "d.json")
    holes = [
        {"hole_id": "missing_category_curling", "category": "curling", "priority": 3},
        {"hole_id": "missing_category_swim", "category": "swim", "priority": 3},
        {"hole_id": "missing_category_quidditch", "category": "quidditch", "priority": 3},
        {"hole_id": "missing_category_lacrosse", "category": "lacrosse", "priority": 3},
    ]
    ranked = dr.rank_holes(holes, use_llm=False)     # deterministic prior
    assert ranked[0]["category"] == "swim"           # core beats all
    assert ranked[1]["category"] == "lacrosse"       # mainstream beats niche
    assert {ranked[2]["category"], ranked[3]["category"]} == {"curling", "quidditch"}
    assert all("demand" in h for h in ranked)
