"""Tests for catalog-grid platform detection and adapter."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.platforms import (  # noqa: E402
    CATALOG_GRID,
    adapter_catalog_grid,
    detect_platform,
)


def _links(*pairs: tuple[str, str]) -> list[dict]:
    return [{"url": u, "text": t} for u, t in pairs]


def test_detect_catalog_grid_for_idtech_style_catalog():
    links = _links(
        *[
            (f"https://idtech.com/courses/camp-{i}", f"Camp {i}")
            for i in range(8)
        ]
    )
    platform = detect_platform(
        "https://idtech.com/courses",
        links,
        "Results: 72 courses",
    )
    assert platform == CATALOG_GRID


def test_detect_catalog_grid_from_link_density():
    links = _links(
        *[
            (f"https://example.com/courses/camp-{i}", f"Camp {i}")
            for i in range(8)
        ]
    )
    platform = detect_platform("https://example.com/courses", links, "")
    assert platform == CATALOG_GRID


async def _run_adapter():
    links = _links(
        (
            "https://www.idtech.com/courses/battlebots-camp-junior",
            "BattleBots® Camp Junior",
        ),
        (
            "https://www.idtech.com/courses/coding-101-camp",
            "Coding 101 Camp",
        ),
        (
            "https://www.idtech.com/courses/virtual-coding-with-scratch",
            "Virtual",
        ),
        ("https://www.idtech.com/courses", "Courses"),
    )
    return await adapter_catalog_grid("https://idtech.com/courses", links, "Results: 72")


def test_catalog_grid_rejects_nested_program_paths():
    """UNH /health/programs/foo must not match — only top-level /programs/slug."""
    from src.platforms import _is_catalog_grid_item

    seed = "https://mail.google.com/"
    assert not _is_catalog_grid_item(
        seed,
        {"url": "https://extension.unh.edu/health/programs/mental-health-first-aid", "text": "MHFA"},
    )
    assert _is_catalog_grid_item(
        "https://idtech.com/courses",
        {"url": "https://idtech.com/courses/battlebots-camp-junior", "text": "Camp"},
    )


def test_adapter_catalog_grid_collects_course_urls():
    import asyncio

    sessions = asyncio.run(_run_adapter())
    urls = {s["register_url"] for s in sessions}
    assert len(sessions) >= 2
    assert any("battlebots-camp-junior" in u for u in urls)
    assert all(s["platform"] == CATALOG_GRID for s in sessions)
    assert all(s["register_url"] != "https://idtech.com/why-id" for s in sessions)
