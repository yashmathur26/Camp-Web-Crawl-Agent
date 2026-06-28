"""Tests for data/log folder layout."""

from shared.data_layout import (
    camp_links_csv,
    camp_sessions_csv,
    candidates_csv,
    data_root_readme,
    quality_tier_csv,
    session_log_path,
    town_phase_dir,
)


def test_shared_phase_paths():
    assert candidates_csv().parts[-3:] == ("shared", "phase_a", "candidates.csv")
    assert camp_links_csv().parts[-3:] == ("shared", "phase_b", "camp_links.csv")


def test_town_phase_paths():
    p = camp_sessions_csv("Lexington")
    assert p == town_phase_dir("Lexington", "phase_b5") / "camp_sessions.csv"
    q = quality_tier_csv("Burlington", "registrable")
    assert "burlington" in str(q) and q.name == "registrable.csv"


def test_readme_and_logs():
    data_root_readme()
    log = session_log_path("Lexington")
    assert "lexington" in str(log)
    assert log.parent.name == "lexington"
