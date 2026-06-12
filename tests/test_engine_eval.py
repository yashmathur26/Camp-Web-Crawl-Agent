"""Engine v3 task 0.4: eval harness — fuzzy matcher, date windows, scoring."""

from __future__ import annotations

from engine.eval.score import (
    PublishedRow,
    names_match,
    normalize_name,
    parse_date_window,
    score,
    token_set_ratio,
    windows_overlap,
)

# --- fuzzy matcher (DoD: exact, dated-variant, near-miss) ------------------


def test_match_exact():
    assert names_match("Lower Camp", "Lower Camp")


def test_match_dated_variant():
    # Week/session labels and date fragments must not block a match.
    assert names_match("Lower Camp Week 3", "Lower Camp")
    assert names_match("Lower Camp (June 29 - July 2)", "Lower Camp")
    assert names_match("Soccer Camp Session 2 7/14", "Soccer Camp")


def test_match_word_order_and_noise():
    assert names_match("Summer Art Camp", "Art Camp - Summer")
    assert names_match("LEGO Robotics — Week One", "Lego Robotics")


def test_near_miss_does_not_match():
    assert not names_match("Soccer Camp", "Basketball Camp")
    assert not names_match("Lower Camp", "Upper Camp")
    assert not names_match("Chess Club", "Art Studio")


def test_normalize_strips_dates_and_weeks():
    assert normalize_name("Lower Camp Week 3 (June 29 – July 2)") == "lower camp"
    assert normalize_name("Art Camp 2026") == "art camp"


def test_token_set_ratio_bounds():
    assert token_set_ratio("", "") == 0.0
    assert token_set_ratio("Camp", "Camp") == 1.0


# --- date windows -----------------------------------------------------------


def test_parse_date_window_formats():
    assert parse_date_window("June 29 – July 2") is not None
    assert parse_date_window("6/29-7/2") is not None
    assert parse_date_window("2026-07-06 – 2026-07-10") is not None
    assert parse_date_window("") is None
    assert parse_date_window("no dates here") is None


def test_windows_overlap():
    a = parse_date_window("July 7 - July 11")
    b = parse_date_window("July 10 - July 14")
    c = parse_date_window("August 3 - August 7")
    assert windows_overlap(a, b)
    assert not windows_overlap(a, c)
    assert not windows_overlap(a, None)


# --- scoring end-to-end ------------------------------------------------------


GT = [
    {"provider_host": "jwhayden.org", "program_name": "Lower Camp",
     "session_dates": "July 7 - July 11", "true_info_url": "https://x/1"},
    {"provider_host": "jwhayden.org", "program_name": "Upper Camp",
     "session_dates": "", "true_info_url": "https://x/2"},
    {"provider_host": "munroecenter.org", "program_name": "Art Adventure",
     "session_dates": "", "true_info_url": "https://x/3"},
]


def _pub(host, name, dates=""):
    return PublishedRow(provider_host=host, name=name, info_url="https://x/i", dates=dates)


def test_score_recall_precision():
    published = [
        _pub("jwhayden.org", "Lower Camp Week 1", "July 7 - July 11"),
        _pub("jwhayden.org", "Lower Camp Week 5", "August 4 - August 8"),
        _pub("jwhayden.org", "Upper Camp"),
        _pub("jwhayden.org", "Back Office Junk Row"),  # unmatched -> hurts precision
    ]
    m = score(published, GT)
    assert m["gt_programs"] == 3
    assert m["matched_programs"] == 2          # Lower + Upper; Art Adventure missed
    assert abs(m["program_recall"] - 2 / 3) < 1e-3
    assert m["gt_sessions"] == 1
    assert m["matched_sessions"] == 1          # Lower Camp window overlaps
    assert m["precision"] == 0.75              # 3 of 4 rows matched GT
    assert any("Art Adventure" in s for s in m["unmatched_gt_programs"])


def test_score_host_alias_tolerance():
    # gov funnel host should still match the myrec-host GT provider.
    gt = [{"provider_host": "lexrecma.myrec.com", "program_name": "Clay Camp",
           "session_dates": "", "true_info_url": "https://x/4"}]
    published = [_pub("lexrecma.myrec.com", "Clay Camp")]
    assert score(published, gt)["program_recall"] == 1.0


def test_score_info_url_validity_with_stub_fetch():
    published = [_pub("jwhayden.org", "Lower Camp")]
    good_text = "Lower Camp at Hayden. " * 30  # >400 chars, contains name tokens
    m = score(published, GT, check_info_urls=True, fetch_fn=lambda url: good_text)
    assert m["info_url_validity"] == 1.0
    m2 = score(published, GT, check_info_urls=True, fetch_fn=lambda url: "short")
    assert m2["info_url_validity"] == 0.0
