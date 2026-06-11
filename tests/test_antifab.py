"""roadmap2 Phase 4: anti-fabrication (no LLM on thin/login) + anti-drift."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

from src.camp_validator import should_llm_extract
from src.navigator import _OFF_TOPIC_RE, extract_camp_links, extract_one_camp, find_register_link


# --- anti-fabrication: extraction guard -----------------------------------


def test_should_not_extract_login_or_thin():
    assert should_llm_extract("")[0] is False
    assert should_llm_extract("Please log in to register. Password:")[0] is False
    assert should_llm_extract("Members only")[1] == "login_wall"
    thin = "Loading..."
    assert should_llm_extract(thin)[0] is False


def test_should_extract_substantive_page():
    html = (
        "# Summer Soccer Camp\n"
        "A full week of youth soccer for ages 6-12 in July. Daily drills, "
        "scrimmages, and skills training. Register online. Program fee $250. "
        "Camp runs July 7 through July 11 at the town fields. " * 3
    )
    ok, why = should_llm_extract(html)
    assert ok is True
    assert why == ""


def test_extract_one_camp_does_not_fabricate_from_login_page():
    # 92-char login shell, no register link -> must not invent ages/dates.
    login_html = "Sign in to your account. Username and password required to continue."

    async def _run():
        # extract_camp_sessions must NOT be called for a thin login page.
        with patch(
            "src.camp_validator.extract_camp_sessions",
            side_effect=AssertionError("LLM extraction ran on a login page"),
        ):
            return await extract_one_camp(
                "https://hancocknurseryschool.org/hns-summer", login_html, []
            )

    s = asyncio.run(_run())
    assert s["ages"] == ""
    assert s["dates"] == ""
    assert s.get("extract_status") in {"login_wall", "needs_js"}


# --- anti-drift: off-topic fan-out + off-host register --------------------


def test_off_topic_regex_matches_research_paths():
    assert _OFF_TOPIC_RE.search("/psychiatry/research/cardiac-psychiatry-research-program")
    assert _OFF_TOPIC_RE.search("/careers/openings")
    assert not _OFF_TOPIC_RE.search("/programs/summer-soccer-camp")


def test_extract_camp_links_skips_research_sections():
    page = "https://massgeneral.org/aspire"
    links = [
        {"url": "https://massgeneral.org/psychiatry/research/program", "text": "Research Program"},
        {"url": "https://massgeneral.org/programs/summer-social-skills-camp", "text": "Summer Camp"},
    ]
    found = extract_camp_links(page, links)
    assert not any("research" in u for u in found)


def test_find_register_link_rejects_offhost_research_url():
    page = "https://massgeneral.org/psychiatry/research/program"
    links = [{"url": "https://ncbi.nlm.nih.gov/pubmed/26933943", "text": "Register"}]
    assert find_register_link(page, links) == ""


def test_find_register_link_keeps_same_host_and_allowlisted():
    page = "https://camp.org/soccer"
    assert find_register_link(
        page, [{"url": "https://camp.org/soccer/register", "text": "Register"}]
    ) == "https://camp.org/soccer/register"
    assert find_register_link(
        page, [{"url": "https://form.jotform.com/2345", "text": "Register Now"}]
    ) == "https://form.jotform.com/2345"
