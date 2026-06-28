"""roadmap2 Phase 3: evidence-based filtering + fail-open tie-breaker."""

from __future__ import annotations

from unittest.mock import patch

from shared import llm
from phase_b.platforms import _apply_focus_llm_tiebreaker
from phase_a.relevance import classify_session


def test_registrable_evidence_keeps_keywordless_program():
    # "Super Soccer Stars" has no camp/summer keyword but sits on a registration
    # platform with age evidence — keep it via the registrable-evidence path.
    keep, reason = classify_session(
        "Super Soccer Stars",
        ages="3-5",
        register_url="https://lexrecma.myrec.com/programs/program_details.aspx?id=9",
    )
    assert keep is True
    assert reason == "registrable-evidence"


def test_no_evidence_no_keyword_still_dropped():
    keep, reason = classify_session(
        "Empathy and Relational Science Program",
        dates="",
        register_url="https://massgeneral.org/psychiatry/research/program",
    )
    assert keep is False
    assert reason == "no-signal"


def test_adult_still_hard_dropped_even_with_evidence():
    keep, reason = classify_session(
        "Adult Yoga",
        ages="18+",
        dates="July 7",
        price="$80",
        register_url="https://lexrecma.myrec.com/programs/program_details.aspx?id=1",
    )
    assert keep is False
    assert reason in {"adult", "adult-fitness"}


def test_empty_name_with_evidence_not_dropped_as_empty():
    # Phase 1 may blank a chrome name; evidence should still carry the row to the
    # registrable-evidence keep rather than an "empty" drop.
    keep, reason = classify_session(
        "",
        ages="6-12",
        register_url="https://lexrecma.myrec.com/programs/program_details.aspx?id=2",
    )
    assert keep is True
    assert reason == "registrable-evidence"


def test_tiebreaker_fail_open_recovers_camp_context_when_llm_down():
    from config import settings

    dropped = [
        {  # camp-context: has evidence -> recovered on fail-open
            "name": "Mystic Valley Music Together",
            "ages": "0-5",
            "dates": "",
            "price": "$220",
            "register_url": "https://example.org/music",
            "_focus_reason": "no-signal",
        },
        {  # no evidence, not a platform -> stays dropped
            "name": "Some Page",
            "register_url": "https://example.org/about",
            "_focus_reason": "no-signal",
        },
    ]
    orig = dict(settings.SETTINGS)
    settings.SETTINGS.update(
        {"ollama_focus_verify": True, "b5_focus_verify_fail_open": True}
    )
    try:
        # Force the model-unavailable path so the fail-open branch is exercised
        # deterministically (Ollama may or may not be running on the host).
        with patch.object(llm, "is_available", return_value=False):
            kept, still = _apply_focus_llm_tiebreaker([], dropped, town_hint="Lexington")
    finally:
        settings.SETTINGS.clear()
        settings.SETTINGS.update(orig)

    kept_names = {s["name"] for s in kept}
    assert "Mystic Valley Music Together" in kept_names
    assert "Some Page" not in kept_names
