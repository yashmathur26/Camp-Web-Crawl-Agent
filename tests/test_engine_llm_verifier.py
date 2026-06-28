"""v3 Phase 4 — LLM page-role verifier + weak-name normalizer.

The model is mocked (offline) so these assert the CONTRACT: ≥400-char answerable
gate, JSON parse, value validation, and fail-open (None) — never a raised error,
never a deletion.
"""

from __future__ import annotations

import engine.extract.llm as llm


def test_role_thin_text_makes_no_call(monkeypatch):
    called = {"n": 0}

    def _spy(*a, **k):
        called["n"] += 1
        return '{"role":"info"}'

    monkeypatch.setattr(llm, "_chat", _spy)
    assert llm.verify_page_role("too short") is None     # < 400 chars → no call
    assert called["n"] == 0


def test_role_parsed_and_validated(monkeypatch):
    text = "x" * 500
    monkeypatch.setattr(llm, "_chat", lambda *a, **k: '{"role":"registration"}')
    assert llm.verify_page_role(text) == "registration"
    monkeypatch.setattr(llm, "_chat", lambda *a, **k: '{"role":"nonsense"}')
    assert llm.verify_page_role(text) is None            # invalid value → None
    monkeypatch.setattr(llm, "_chat", lambda *a, **k: None)
    assert llm.verify_page_role(text) is None            # model down → fail open


def test_role_extracts_json_from_noise(monkeypatch):
    text = "x" * 500
    monkeypatch.setattr(llm, "_chat", lambda *a, **k: 'here you go: {"role":"peripheral"} ok')
    assert llm.verify_page_role(text) == "peripheral"


def test_name_normalizer_cleans_or_flags(monkeypatch):
    monkeypatch.setattr(llm, "_chat", lambda *a, **k: '{"name":"Homeschool Camp"}')
    assert llm.normalize_name_llm("homeschool.html") == "Homeschool Camp"
    monkeypatch.setattr(llm, "_chat", lambda *a, **k: '{"name":""}')
    assert llm.normalize_name_llm("nav-menu-toggle") == ""   # judged not-a-name
    monkeypatch.setattr(llm, "_chat", lambda *a, **k: None)
    assert llm.normalize_name_llm("anything") is None        # fail open


def test_offline_real_call_is_fail_open():
    # No mock: a real Ollama call to a down server must return None, never raise.
    assert llm.verify_page_role("y" * 500) is None or isinstance(llm.verify_page_role("y" * 500), str)
