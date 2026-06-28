"""Unified runner — workspace, merge, and archive tests. No network."""

from __future__ import annotations

import csv
from pathlib import Path

from orchestrator.unified_run import (
    UNIFIED_FIELDS,
    archive_clutter,
    build_registry_from_discovery,
    create_workspace,
    ensure_registry,
    merge_run_catalog,
    write_merged,
)


def _write_csv(path: Path, header: list[str], rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        w.writerows(rows)


def test_merge_normalizes_and_dedupes(tmp_path):
    data = tmp_path / "data"
    # engine source
    _write_csv(data / "lexington" / "engine" / "sessions.csv",
               ["name", "info_url", "register_url", "dates", "ages", "price", "verdict"],
               [{"name": "Robotics Camp", "info_url": "", "register_url":
                 "https://lexrecma.myrec.com/info/activities/program_details.aspx?ProgramID=100",
                 "dates": "7/6/2026", "ages": "8-12", "price": "$300", "verdict": "parent_ready"}])
    # pipeline phase_p — same ProgramID as engine -> must collapse
    _write_csv(data / "lexington" / "phase_p" / "all_verified.csv",
               ["name", "register_url", "platform", "dates", "ages", "price", "parent_verdict"],
               [{"name": "Robotics Camp", "register_url":
                 "https://lexrecma.myrec.com/info/activities/program_details.aspx?ProgramID=100&utm=x",
                 "platform": "myrec", "dates": "7/6/2026", "ages": "8-12", "price": "$300",
                 "parent_verdict": "parent_ready"}])
    # part_d
    _write_csv(data / "part_d" / "part_d_ma_camps.csv",
               ["name", "platform", "geo_town", "geo_city", "geo_state", "geo_zip",
                "start_date", "dates", "ages", "price", "register_url", "info_url",
                "serving_towns", "discovered_via", "session_uid"],
               [{"name": "Nike Basketball", "platform": "ussportscamps", "geo_town": "Waltham",
                 "geo_city": "Waltham", "geo_state": "MA", "geo_zip": "02451",
                 "start_date": "2026-07-06", "dates": "7/6/2026", "ages": "8-14", "price": "",
                 "register_url": "https://www.ussportscamps.com/x", "info_url": "",
                 "serving_towns": "Lexington", "discovered_via": "ussportscamps", "session_uid": ""}])

    rows = merge_run_catalog(data)
    # engine + pipeline collapsed into one (same ProgramID); + 1 part_d = 2 total
    assert len(rows) == 2
    sources = {r["source"] for r in rows}
    assert "part_d" in sources
    merged = next(r for r in rows if "myrec" in r["register_url"])
    assert "engine" in merged["discovered_via"] and any("myrec" in v or "pipeline" in v for v in merged["discovered_via"])
    assert all(set(UNIFIED_FIELDS) <= set(r.keys()) for r in rows)


def test_write_merged_produces_csv_and_txt(tmp_path):
    rows = [{"source": "part_d", "town": "Waltham", "name": "Camp X", "platform": "idtech",
             "geo_town": "Waltham", "geo_state": "MA", "dates": "7/6/2026", "ages": "7-9",
             "price": "$100", "register_url": "https://x", "serving_towns": ["Waltham"],
             "discovered_via": ["idtech"], "session_uid": "u1"}]
    csv_path, txt_path = write_merged(rows, tmp_path)
    assert csv_path.exists() and txt_path.exists()
    with csv_path.open() as f:
        out = list(csv.DictReader(f))
    assert out[0]["geo_state"] == "MA"
    assert out[0]["serving_towns"] == "Waltham"
    assert "Camp X" in txt_path.read_text()


def test_create_workspace_symlinks_and_env(tmp_path):
    ctx = create_workspace(["Lexington"], runs_root=tmp_path / "runs", ts="2026-06-15_120000")
    assert ctx.data_dir.is_dir() and ctx.logs_dir.is_dir()
    assert ctx.env["FIREFLY_DATA_ROOT"] == str(ctx.data_dir)
    assert ctx.env["FIREFLY_LOGS_ROOT"] == str(ctx.logs_dir)
    # symlinks created for shared dirs
    assert (ctx.data_dir / "_baseline").exists()
    assert (ctx.data_dir / "_snapshots").exists()


def test_archive_clutter_moves_clutter_keeps_essentials(tmp_path):
    repo = tmp_path / "repo"
    (repo / "data" / "lexington" / "engine").mkdir(parents=True)
    (repo / "data" / "lexington" / "engine" / "sessions.csv").write_text("x")
    (repo / "data" / "_baseline").mkdir(parents=True)
    (repo / "data" / "_baseline" / "keep.json").write_text("{}")
    (repo / "data" / "cache").mkdir(parents=True)
    (repo / "data" / "junk_audit.csv").write_text("a")
    (repo / "data" / "part_d").mkdir(parents=True)
    (repo / "logs").mkdir(parents=True)
    (repo / "logs" / "run.log").write_text("log")
    (repo / "trash").mkdir(parents=True)

    res = archive_clutter(repo_root=repo, dry_run=False, ts="2026-06-15_130000")
    # essentials kept
    assert (repo / "data" / "_baseline" / "keep.json").exists()
    assert (repo / "data" / "cache").exists()
    assert (repo / "data" / "junk_audit.csv").exists()
    # clutter moved
    assert not (repo / "data" / "lexington").exists()
    assert not (repo / "data" / "part_d").exists()
    assert not (repo / "trash").exists()
    dest = Path(res["dest"])
    assert (dest / "data" / "lexington" / "engine" / "sessions.csv").exists()
    assert (dest / "logs" / "run.log").exists()
    assert (dest / "trash").exists()
    assert "data/lexington" in res["moved"]


def test_engine_registry_autobuilt_for_any_town(tmp_path):
    from engine.registry.schema import load_registry

    data = tmp_path / "data"
    reg = tmp_path / "reg"
    reg.mkdir()
    _write_csv(data / "shared" / "phase_a" / "candidates.csv", ["url", "town"],
               [{"url": "https://natickrec.myrec.com/info/activities/activities.aspx", "town": "Natick"},
                {"url": "https://www.facebook.com/x", "town": "Natick"},
                {"url": "https://somegym.com/camps", "town": "Natick"}])
    _write_csv(data / "shared" / "phase_b" / "camp_links.csv", ["url", "town_hint"],
               [{"url": "https://manatick.myvscloud.com/webtrac/web/search.html?Module=AR", "town_hint": "Natick"}])
    out = build_registry_from_discovery("Natick", data, reg)
    assert out is not None
    tr = load_registry(out)
    vendors = {p.vendor for p in tr.providers}
    assert {"myrec", "webtrac"} <= vendors
    assert not any("facebook" in p.host for p in tr.providers)  # deny-listed dropped


def test_ensure_registry_uses_committed_else_builds(tmp_path):
    ctx = create_workspace(["Natick"], runs_root=tmp_path / "runs", ts="2026-06-15_140000")
    # committed Lexington registry copied into the run registry dir at creation
    assert (ctx.registry_dir / "lexington.yaml").exists()
    # no discovery yet for Natick -> ensure_registry returns False (engine skips)
    assert ensure_registry(ctx, "Natick") is False
    # add discovery, then it builds
    _write_csv(ctx.data_dir / "shared" / "phase_a" / "candidates.csv", ["url", "town"],
               [{"url": "https://natickrec.myrec.com/x", "town": "Natick"}])
    assert ensure_registry(ctx, "Natick") is True
    assert (ctx.registry_dir / "natick.yaml").exists()


def test_parallel_orchestration_plumbing(tmp_path):
    # Skip every stage so no subprocess/network runs; this exercises the
    # town_parallelism threadpool branch and the town-ordered result aggregation.
    from orchestrator.unified_run import run_unified

    res = run_unified(
        ["Lexington", "Burlington", "Waltham", "Watertown"],
        skip={"A", "B", "engine", "D", "C"},
        town_parallelism=2,
        runs_root=tmp_path / "runs",
        ts="2026-06-15_150000",
    )
    m = res["manifest"]
    assert m["town_parallelism"] == 2
    # 3 per-town stages x 4 towns + D + C = 14 stage records, all skipped
    assert len(m["stages"]) == 14
    assert all(s["status"].startswith("skipped") for s in m["stages"])
    # town order preserved in results
    town_stage_keys = [s["key"] for s in m["stages"] if ":" in s["key"]]
    assert town_stage_keys[0].endswith("Lexington")
    assert (Path(res["ctx"].run_dir) / "manifest.json").exists()


def test_resume_reuses_run_dir_without_wiping(tmp_path):
    from orchestrator.unified_run import create_workspace

    runs = tmp_path / "runs"
    ctx1 = create_workspace(["Lexington"], runs_root=runs, ts="2026-06-16_100000")
    # drop a marker file that must survive a resume
    marker = ctx1.data_dir / "_towns" / "lexington" / "marker.txt"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("keep me")

    ctx2 = create_workspace(["Lexington"], runs_root=runs, resume_dir=ctx1.run_dir)
    assert ctx2.run_dir == ctx1.run_dir
    assert marker.exists() and marker.read_text() == "keep me"  # nothing deleted


def test_b_stage_is_harvest_only():
    # The B stage must skip B5 enumeration (the slow agent-nav path) — the engine
    # does enumeration and the merge doesn't read phase_b5.
    from orchestrator.unified_run import _town_stage_specs, create_workspace

    ctx = create_workspace(["Lexington"], runs_root=Path("/tmp/x_unused_ts"), ts="zz")
    b = next(s for s in _town_stage_specs(ctx, "Lexington") if s["stage"] == "B")
    assert "--no-enumerate-sessions" in b["cmd"]


def test_archive_dry_run_moves_nothing(tmp_path):
    repo = tmp_path / "repo"
    (repo / "data" / "waltham").mkdir(parents=True)
    res = archive_clutter(repo_root=repo, dry_run=True)
    assert (repo / "data" / "waltham").exists()  # untouched
    assert "data/waltham" in res["moved"]
