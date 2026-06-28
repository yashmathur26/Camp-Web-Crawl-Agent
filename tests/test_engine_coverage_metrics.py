"""v3 Phase 6 — coverage rollup, link metrics (incl. the register==info
regression split), and the eval floor."""

from __future__ import annotations

from engine.model import Program, Provider, Session
from engine.run.metrics import (
    coverage_rollup,
    enforce_eval_floor,
    link_metrics,
    summary_lines,
)


def _prov(host):
    return Provider(name=host, host=host, town="Lexington", seed_url=f"https://{host}/")


def _prog(provider_id, sessions):
    p = Program(name="P", provider_id=provider_id, sessions=sessions)
    return p


def test_coverage_reached_vs_missed():
    p1, p2 = _prov("a.org"), _prov("b.org")
    progs = [
        _prog(p1.provider_id, [Session(name="A", info_url="https://a.org/c",
                                       register_url="https://reg.capturepoint.com/x",
                                       register_confidence="high")]),
        _prog(p2.provider_id, [Session(name="B", info_url="https://b.org/c")]),  # no signup
    ]
    cov = {c.host: c for c in coverage_rollup([p1, p2], progs)}
    assert cov["a.org"].registration_reached and not cov["a.org"].missed_signup
    assert not cov["b.org"].registration_reached and cov["b.org"].missed_signup


def test_link_metrics_regression_split():
    p = _prov("a.org")
    iteminfo = "https://x.myvscloud.com/webtrac/web/iteminfo.html?FMID=1&Module=AR"
    progs = [_prog(p.provider_id, [
        # legit combined platform page: register==info WITH the flag
        Session(name="Real", info_url=iteminfo, register_url=iteminfo,
                register_is_info=True, register_confidence="high",
                homepage_url="https://a.org/", page_role="registration"),
        # the OLD aliasing bug: register==info WITHOUT the flag
        Session(name="Bug", info_url="https://a.org/camp", register_url="https://a.org/camp",
                register_is_info=False, homepage_url="https://a.org/", page_role="info"),
    ])]
    m = link_metrics(progs, [])
    assert m.register_eq_info_real == 1
    assert m.register_eq_info_regression == 1
    assert m.confirmed == 2 and m.register_found == 2
    lines = summary_lines(m)
    assert any("REGRESSION" in ln for ln in lines)


def test_link_metrics_rung_distribution():
    p = _prov("a.org")
    progs = [_prog(p.provider_id, [
        Session(name="own", info_url="https://a.org/camps/x", page_role="info",
                nearest_hub="https://a.org/camps", homepage_url="https://a.org/"),
        Session(name="hubonly", info_url="https://a.org/summer-camps", page_role="info",
                nearest_hub="https://a.org/programs/summer", homepage_url="https://a.org/"),
    ])]
    m = link_metrics(progs, [])
    assert m.rung_dist.get("rung1") == 1
    assert m.rung_dist.get("rung2") == 1


def test_eval_floor_skips_when_no_ground_truth(tmp_path):
    (tmp_path / "sessions.csv").write_text("name,info_url\n", encoding="utf-8")
    assert enforce_eval_floor("zz_nonexistent_town", tmp_path / "sessions.csv", 0.95) is None


def test_eval_floor_flags_low_precision(tmp_path):
    # A junk confirmed row against real Lexington GT → precision 0 → floor fails.
    sessions = tmp_path / "sessions.csv"
    sessions.write_text(
        "name,info_url,register_url,dates\n"
        "Totally Made Up Row,https://nowhere.example/x,,\n",
        encoding="utf-8",
    )
    res = enforce_eval_floor("lexington", sessions, 0.95)
    assert res is not None and not res.ok
    assert "precision" in res.reason
