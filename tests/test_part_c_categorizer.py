"""Part C Stage 2: categorizer — rules, cache, fallback (offline)."""

from unittest.mock import patch

from src.categorizer import _rule_categories, categorize_sessions, coverage_by_category


def test_rules_catch_majority():
    assert "soccer" in _rule_categories("super soccer stars ages 3-5")
    assert "magic" in _rule_categories("wizards & wands camp")          # synonym
    assert "robotics" in _rule_categories("battling robot inventors with vex iq")
    assert "teen_leadership" in _rule_categories("leader in training - application")
    assert "pottery" in _rule_categories("clay, play, and crochet")     # synonym
    assert _rule_categories("zzqx unknowable") == []


def test_specific_beats_generic():
    cats = _rule_categories("lego robotics summer stem camp")
    assert cats[0] in ("robotics", "lego_robotics", "coding")


def test_categorize_offline_no_llm(tmp_path, monkeypatch):
    import src.categorizer as cz

    monkeypatch.setattr(cz, "_CACHE_PATH", tmp_path / "c.json")
    sessions = [
        {"name": "Viking Basketball Camp", "register_url": "https://x.org/1"},
        {"name": "Totally Unknowable Name", "register_url": "https://x.org/2"},
    ]
    out = categorize_sessions(sessions, use_llm=False)
    assert out[0]["category"] == "basketball"
    assert out[1]["categories"] == [] and out[1]["category"] is None
    cov = coverage_by_category(out)
    assert "basketball" in cov


def test_cache_prevents_rework(tmp_path, monkeypatch):
    import src.categorizer as cz

    monkeypatch.setattr(cz, "_CACHE_PATH", tmp_path / "c.json")
    s = [{"name": "Chess Summer Clinic", "register_url": "https://x.org/9"}]
    categorize_sessions(s, use_llm=False)
    calls = []
    with patch.object(cz, "_rule_categories", side_effect=lambda b: calls.append(1) or []):
        out = categorize_sessions(s, use_llm=False)
    assert calls == []                       # cache hit, rules not re-run
    assert out[0]["category"] == "chess"
