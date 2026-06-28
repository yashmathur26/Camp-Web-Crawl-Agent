"""Phase P3: bounded recursive navigator."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from phase_b.navigator import (
    PageRole,
    classify_role,
    extract_camp_links,
    find_register_link,
    navigate_provider,
)

SEED = "https://example-camps.org/summer-programs"
CAMPS = [
    ("soccer-camp", "Soccer Summer Camp"),
    ("basketball-camp", "Basketball Summer Camp"),
    ("art-camp", "Art Summer Camp"),
    ("science-camp", "Science Summer Camp"),
    ("dance-camp", "Dance Summer Camp"),
]


def _catalog_html() -> str:
    lines = ["# Summer Programs", "Choose your camp:", ""]
    for slug, name in CAMPS:
        lines.append(f"- [{name}](https://example-camps.org/programs/{slug})")
    return "\n".join(lines)


def _catalog_links() -> list[dict]:
    links = []
    for slug, name in CAMPS:
        links.append(
            {
                "url": f"https://example-camps.org/programs/{slug}",
                "text": name,
            }
        )
    return links


def _detail_html(name: str) -> str:
    return f"""# {name}
Ages 8-12. June 15 - June 19.
Program fee $425.
<a href="https://register.example-camps.org/enroll/{name.lower().replace(' ', '-')}">Register Now</a>
"""


def _register_html(name: str) -> str:
    return f"""# Enroll — {name}
Summer day camp for youth ages 8-12.
Program fee $425.
<button>Add to Cart</button>
<a href="#">Proceed to checkout</a>
"""


def _mock_pages() -> dict[str, tuple[str, list[dict]]]:
    pages: dict[str, tuple[str, list[dict]]] = {
        SEED: (_catalog_html(), _catalog_links()),
    }
    for slug, name in CAMPS:
        detail_url = f"https://example-camps.org/programs/{slug}"
        reg_url = f"https://register.example-camps.org/enroll/{name.lower().replace(' ', '-')}"
        pages[detail_url] = (
            _detail_html(name),
            [{"url": reg_url, "text": "Register Now"}],
        )
        pages[reg_url] = (_register_html(name), [])
    return pages


async def _mock_fetch(url: str, *args, **kwargs):
    pages = _mock_pages()
    return pages.get(url, ("", []))


def test_classify_role_catalog_from_rules():
    html = _catalog_html()
    links = _catalog_links()
    role = classify_role(SEED, html, links)
    assert role == PageRole.CATALOG


def test_extract_camp_links_finds_all_programs():
    links = _catalog_links()
    found = extract_camp_links(SEED, links)
    assert len(found) == 5


def test_find_register_link_on_detail_page():
    slug, name = CAMPS[0]
    detail_url = f"https://example-camps.org/programs/{slug}"
    reg_url = f"https://register.example-camps.org/enroll/{name.lower().replace(' ', '-')}"
    links = [{"url": reg_url, "text": "Register Now"}]
    assert find_register_link(detail_url, links) == reg_url


def _role_for_url(url: str, html: str, links: list[dict], **kw) -> PageRole:
    if url == SEED:
        return PageRole.CATALOG
    if "/programs/" in url:
        return PageRole.DETAIL
    return PageRole.REGISTER


def test_navigate_provider_flat_multicamp_yields_all_camps():
    async def _run():
        with patch("phase_b.platforms._fetch", side_effect=_mock_fetch):
            with patch("phase_b.platforms.detect_platform", return_value="custom"):
                with patch("phase_b.navigator.classify_role", side_effect=_role_for_url):
                    return await navigate_provider(
                        SEED,
                        town_hint="Burlington",
                        max_depth=3,
                        max_fetches=30,
                    )

    sessions = asyncio.run(_run())
    assert len(sessions) == 5
    info_urls = {s["info_url"] for s in sessions}
    reg_urls = {s["register_url"] for s in sessions}
    assert len(info_urls) == 5
    assert len(reg_urls) == 5
    assert all(s.get("info_url") for s in sessions)
    assert all(s.get("register_url") for s in sessions)
    assert all(s.get("parent_verdict") == "parent_ready" for s in sessions)
    assert all(s.get("parent_can_register") for s in sessions)


def test_enumerate_provider_v2_flag_uses_navigator():
    from config import settings
    from phase_b.platforms import enumerate_provider

    async def _run():
        with patch("phase_b.platforms._fetch", side_effect=_mock_fetch):
            with patch("phase_b.platforms.detect_platform", return_value="custom"):
                with patch("phase_b.navigator.classify_role", side_effect=_role_for_url):
                    original = dict(settings.SETTINGS)
                    settings.SETTINGS.update(
                        {
                            "b5_navigator_v2": True,
                            "filter_to_focus": False,
                        }
                    )
                    try:
                        return await enumerate_provider(SEED, town_hint="Burlington")
                    finally:
                        settings.SETTINGS.clear()
                        settings.SETTINGS.update(original)

    result = asyncio.run(_run())
    assert result["platform"] == "navigator_v2"
    assert len(result["sessions"]) == 5


# ---------------------------------------------------------------------------
# Phase 4 — loosen goal-fighting rules
# ---------------------------------------------------------------------------


def test_p41_rank_links_keeps_cross_host_register_form():
    """P4.1: an external Jotform/Google-Form register link is down-weighted,
    not dropped, so it still reaches the navigator model."""
    from phase_b.camp_navigator import _rank_links_for_agent

    seed = "https://lakeside-camp.org/summer"
    links = [
        {"url": "https://lakeside-camp.org/about", "text": "About Us"},
        {"url": "https://form.jotform.com/2345", "text": "Register Now"},
        {"url": "https://docs.google.com/forms/d/e/abc/viewform", "text": "Sign up now"},
    ]
    ranked = _rank_links_for_agent(seed, links, cap=60)
    urls = {item["url"] for item in ranked}
    assert "https://form.jotform.com/2345" in urls
    assert "https://docs.google.com/forms/d/e/abc/viewform" in urls


def test_p42_adapter_llm_keeps_info_page_with_cta():
    """P4.2: an info page whose only register link is itself is kept (with a
    verdict) when it carries an on-page register CTA."""
    from phase_b import platforms

    url = "https://maplewood-arts.org/summer-art-camp"
    page_text = (
        "# Summer Art Camp\n"
        "Day camp for kids ages 6-12. Week of July 7.\n"
        "Program fee $425.\n"
        "Register Now and add to cart to reserve your spot."
    )
    fake_camp = {
        "name": "Summer Art Camp",
        "ages": "6-12",
        "dates": "July 7",
        "register_urls": [url],
    }

    async def _run():
        with patch(
            "phase_b.camp_validator.extract_camp_sessions", return_value=[fake_camp]
        ):
            return await platforms.adapter_llm(url, [], page_text, town_hint="Burlington")

    sessions = asyncio.run(_run())
    assert len(sessions) == 1
    s = sessions[0]
    assert s["register_url"].rstrip("/") == url.rstrip("/")
    assert s["info_url"].rstrip("/") == url.rstrip("/")
    assert s.get("parent_verdict") == "parent_ready"
    assert s.get("parent_can_register") is True


def test_p42_adapter_llm_still_rejects_brochure_only():
    """P4.2: a same-page link with no register CTA is still rejected."""
    from phase_b import platforms

    url = "https://townrec.org/camp-info"
    page_text = (
        "# Summer Camp\n"
        "Day camp for kids ages 6-12.\n"
        "Registration opens soon — contact us to register. Learn more."
    )
    fake_camp = {"name": "Summer Camp", "register_urls": [url]}

    async def _run():
        with patch(
            "phase_b.camp_validator.extract_camp_sessions", return_value=[fake_camp]
        ):
            return await platforms.adapter_llm(url, [], page_text)

    assert asyncio.run(_run()) == []


def test_p43_chat_with_repair_retries_on_bad_json():
    """P4.3: chat_with_repair retries once when the first call can't parse JSON."""
    from shared import llm
    from shared.llm import OllamaError, chat_with_repair

    calls: list[dict] = []

    def _fake_chat(system, user, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise OllamaError("Could not parse JSON from model output: <garbage>")
        return {"role": "catalog"}

    with patch.object(llm, "chat", side_effect=_fake_chat):
        result = chat_with_repair("sys", "usr", purpose="navigator_role")

    assert result == {"role": "catalog"}
    assert len(calls) == 2  # first failed, repaired retry succeeded


def test_p43_chat_with_repair_does_not_retry_other_errors():
    """P4.3: non-parse errors (e.g. Ollama down) are not retried."""
    from shared import llm
    from shared.llm import OllamaError, chat_with_repair

    calls: list[int] = []

    def _fake_chat(system, user, **kwargs):
        calls.append(1)
        raise OllamaError("Ollama unavailable at http://localhost:11434")

    with patch.object(llm, "chat", side_effect=_fake_chat):
        try:
            chat_with_repair("sys", "usr")
            assert False, "expected OllamaError"
        except OllamaError:
            pass
    assert len(calls) == 1


def test_p44_agent_nav_no_double_fetch_catalog():
    """P4.4: the same catalog URL is fetched at most once, even if it appears
    twice in the model's picks (catalog/register sets no longer conflated)."""
    from phase_b import camp_navigator

    seed = "https://townrec.org/camps"
    catalog_url = "https://townrec.org/programs/summer"
    picks = {
        "catalog_urls": [
            {"url": catalog_url, "label": "Summer", "why": ""},
            {"url": catalog_url, "label": "Summer (dup)", "why": ""},
        ],
        "register_urls": [],
        "reasoning": "",
    }
    fetched: list[str] = []

    async def _fake_fetch(url, *args, **kwargs):
        fetched.append(url)
        return ("", [])

    async def _empty_adapter_llm(url, links, text, town_hint=""):
        return []

    async def _run():
        with patch("phase_b.camp_navigator._pick_agent_urls", return_value=picks):
            with patch("phase_b.platforms._fetch", side_effect=_fake_fetch):
                with patch("phase_b.platforms.detect_platform", return_value="custom"):
                    with patch(
                        "phase_b.platforms.adapter_llm", side_effect=_empty_adapter_llm
                    ):
                        return await camp_navigator.agent_navigate_provider(
                            seed, "", [], town_hint="Burlington"
                        )

    asyncio.run(_run())
    assert fetched.count(catalog_url) == 1
