"""Engine v3 Phase 1: model round-trip, registry loader, signals, gate, runner."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from engine.model import Gap, Program, Provider, Session, read_output, write_output
from engine.registry.schema import RegistryError, load_registry, load_town
from engine.validate.gate import bad_name_reason, gate_program, is_out_of_state
from engine.validate.signals import verify_registrable

# --- 1.1 model round-trip ----------------------------------------------------


def test_model_roundtrip(tmp_path):
    prov = Provider(name="Hayden", host="jwhayden.org", town="Lexington",
                    seed_url="https://www.jwhayden.org/summer-camp", vendor="webtrac",
                    org_id="majwhaydenweb")
    prog = Program(name="Lower Camp", provider_id=prov.provider_id,
                   info_url="https://x/iteminfo?FMID=1", camp_scoped=True)
    prog.sessions = [
        Session(name="Lower Camp", info_url="https://x/iteminfo?FMID=1",
                register_url="https://x/iteminfo?FMID=1", dates="07/06/2026 - 07/10/2026",
                verdict="parent_ready", evidence={"k": "v"}, extractor="webtrac",
                content_chars=1800, program_id=prog.program_id),
    ]
    gap = Gap(provider_id=prov.provider_id, reason="blocked", evidence="queue-it")

    counts = write_output(tmp_path, [prov], [prog], [gap])
    assert counts == {"providers.csv": 1, "programs.csv": 1, "sessions.csv": 1, "gaps.csv": 1}

    loaded = read_output(tmp_path)
    assert loaded["providers"][0].host == "jwhayden.org"
    assert loaded["providers"][0].provider_id == prov.provider_id
    assert loaded["programs"][0].name == "Lower Camp"
    s = loaded["sessions"][0]
    assert s.verdict == "parent_ready" and s.evidence == {"k": "v"} and s.content_chars == 1800
    assert loaded["gaps"][0].reason == "blocked"


def test_gap_rejects_unknown_reason():
    with pytest.raises(ValueError):
        Gap(provider_id="p", reason="whoops")


def test_session_ids_stable():
    a = Session(name="X", info_url="https://x/1", program_id="prog_1")
    b = Session(name="X", info_url="https://x/1", program_id="prog_1")
    assert a.session_id == b.session_id


# --- 1.2 registry loader -----------------------------------------------------


def test_registry_rejects_malformed(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("town: X\nstate: MA\nproviders:\n  - name: A\n    host: a.org\n")
    with pytest.raises(RegistryError, match="seed"):
        load_registry(bad)

    bad2 = tmp_path / "bad2.yaml"
    bad2.write_text(
        "town: X\nstate: MA\nproviders:\n"
        "  - {name: A, host: a.org, seed: 'https://a.org', vendor: madeup}\n"
    )
    with pytest.raises(RegistryError, match="unknown vendor"):
        load_registry(bad2)


def test_registry_accepts_lexington():
    reg = load_town("lexington")
    assert reg.town == "Lexington"
    hosts = {e.host for e in reg.providers}
    # 1.3 DoD: every ground-truth provider host appears.
    import csv

    gt_hosts = set()
    with open("engine/eval/ground_truth/lexington.csv", newline="") as f:
        for r in csv.DictReader(f):
            gt_hosts.add(r["provider_host"])
    missing = gt_hosts - hosts
    assert not missing, f"GT hosts missing from registry: {missing}"
    lexrec = next(e for e in reg.providers if e.host == "lexrecma.myrec.com")
    assert "lexingtonma.gov" in lexrec.aliases


# --- 1.4 signals (ported) ----------------------------------------------------


def test_signals_webtrac_iteminfo_parent_ready():
    url = "https://majwhaydenweb.myvscloud.com/webtrac/web/iteminfo.html?FMID=50801580&Module=AR"
    html = "Lower Camp. Ages 5-7. Add To Cart. $390. webtrac"
    assert verify_registrable(url, html).auto_verdict == "parent_ready"


def test_signals_adult_page_wrong_audience():
    sig = verify_registrable("https://x.org/program", "A summer camp for adults who play an instrument")
    assert sig.auto_verdict == "wrong_audience"


def test_signals_empty_page_blocker():
    sig = verify_registrable("https://x.org/p", "")
    assert "empty_page" in sig.blockers and sig.auto_verdict is None


# --- 1.5 gate: table-driven DoD cases -----------------------------------------

RICH = ("Lower Camp at Hayden. Youth summer day camp, ages 5-7. "
        "Add To Cart. $390 per week. June and July sessions. " * 12)


def _program(name, info_url, *, sessions=None, camp_scoped=False):
    p = Program(name=name, provider_id="prov_x", info_url=info_url, camp_scoped=camp_scoped)
    if sessions:
        p.sessions = sessions
    return p


def test_gate_chrome_name_gaps():
    res = gate_program(_program("Back to Top", "https://x/i"), fetched_text={"https://x/i": RICH})
    assert not res.published and res.gaps[0].reason == "needs_review"
    assert "chrome name" in res.gaps[0].evidence


def test_gate_empty_info_page_gaps():
    res = gate_program(
        _program("Lower Camp", "https://x/i", camp_scoped=True),
        fetched_text={"https://x/i": "171 char shell"},
    )
    assert not res.published and res.gaps[0].reason == "empty"


def test_gate_unfetched_info_url_gaps():
    res = gate_program(_program("Lower Camp", "https://x/i", camp_scoped=True), fetched_text={})
    assert not res.published
    assert "not fetched this run" in res.gaps[0].evidence


def test_gate_pdf_name_never_publishes():
    res = gate_program(_program("schedule.pdf", "https://x/i"), fetched_text={"https://x/i": RICH})
    assert not res.published and "filename" in res.gaps[0].evidence


def test_gate_adult_program_gaps():
    text = ("Phoenix Project: a summer camp for adults only who play an instrument. "
            "Adults only, 18+. Register today. " * 10)
    sess = Session(name="Phoenix Project", info_url="https://x/p", ages="18+")
    res = gate_program(
        _program("Phoenix Project", "https://x/p", sessions=[sess]),
        fetched_text={"https://x/p": text},
    )
    assert not res.published
    assert "adult" in res.gaps[0].evidence.lower()


def test_gate_real_webtrac_row_parent_ready():
    url = "https://majwhaydenweb.myvscloud.com/webtrac/web/iteminfo.html?FMID=1&Module=AR"
    sess = Session(name="Lower Camp", info_url=url, register_url=url,
                   dates="07/06/2026 - 07/10/2026", ages="5-7")
    res = gate_program(
        _program("Lower Camp", url, sessions=[sess], camp_scoped=True),
        fetched_text={url: RICH},
    )
    assert res.published and res.published[0].verdict == "parent_ready"
    assert res.published[0].content_chars == len(RICH)


def test_gate_myrec_listing_row_info_confirmed():
    # Listing evidence (dates+ages) but no fetched register page -> publishable
    # info_confirmed; register non-confirmation NEVER blocks (plan §2/§8.4).
    info = "https://lexrecma.myrec.com/info/activities/default.aspx?type=camps"
    text = ("Chess Summer Clinic - August 10-14. Youth ages 8-12. LexRec summer "
            "programs listing with many camps. " * 12)
    sess = Session(name="Chess Summer Clinic", info_url=info,
                   dates="August 10-14", ages="8-12")
    res = gate_program(
        _program("Chess Summer Clinic", info, sessions=[sess]),
        fetched_text={info: text},
    )
    assert res.published and res.published[0].verdict == "info_confirmed"


def test_gate_out_of_state_gaps():
    assert is_out_of_state("https://ussportscamps.com/basketball/new-hampshire/somecamp")
    sess = Session(name="Hoops Camp", info_url="https://x.com/camps/new-hampshire/hoops")
    res = gate_program(
        _program("Hoops Camp", sess.info_url, sessions=[sess]),
        fetched_text={sess.info_url: RICH},
    )
    assert not res.published and "out-of-state" in res.gaps[0].evidence


# --- 1.6 runner v0 -------------------------------------------------------------


def test_runner_counts_match_csvs(tmp_path, monkeypatch):
    """R6.1: counts in the narration == rows in the CSVs; un-extractable
    providers are diagnosed gaps, never silent zeros. (Dispatch stubbed so the
    test stays offline — vendor extractors have their own fixture tests.)"""
    import engine.run.runner as runner_mod

    async def _stub(provider):
        from engine.model import Gap

        return [], Gap(
            provider_id=provider.provider_id, reason="needs_adapter",
            evidence="offline test stub", suggested_action="n/a",
        ), {}

    monkeypatch.setattr(runner_mod, "_resolve_extractor", lambda: _stub)
    counts = asyncio.run(runner_mod.run_town("lexington", out_root=tmp_path))
    assert counts["providers.csv"] == 21
    assert counts["programs.csv"] == 0 and counts["sessions.csv"] == 0
    assert counts["gaps.csv"] == 21  # every provider a diagnosed gap
    out = read_output(Path(tmp_path) / "lexington" / "engine")
    assert len(out["providers"]) == 21 and len(out["gaps"]) == 21
    assert all(g.reason == "needs_adapter" for g in out["gaps"])
    narration = (Path(tmp_path) / "lexington" / "engine" / "narration.log").read_text()
    assert "21 provider(s)" in narration

def test_checkpoint_resume_skips_finished_providers(tmp_path, monkeypatch):
    """7.2 DoD: rerun completes without re-extracting finished providers."""
    import engine.run.runner as runner_mod
    from engine.model import Gap

    calls = []

    async def _stub(provider):
        calls.append(provider.host)
        return [], Gap(provider_id=provider.provider_id, reason="needs_adapter",
                       evidence="stub", suggested_action="n/a"), {}

    monkeypatch.setattr(runner_mod, "_resolve_extractor", lambda: _stub)
    asyncio.run(runner_mod.run_town("lexington", out_root=tmp_path))
    first = len(calls)
    assert first == 21
    asyncio.run(runner_mod.run_town("lexington", out_root=tmp_path))
    assert len(calls) == first          # zero re-extractions on resume
    calls.clear()
    asyncio.run(runner_mod.run_town("lexington", out_root=tmp_path, fresh=True))
    assert len(calls) == 21             # --fresh reruns everything
