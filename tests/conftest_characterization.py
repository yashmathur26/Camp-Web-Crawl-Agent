"""Shared helpers for characterization tests (imported by test modules)."""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import patch

from tests.fixture_helpers import fixture_fetch

# Keep enumerate_provider offline: no agent nav, no LLM trail, no focus filter.
OFFLINE_SETTINGS = {
    "b5_agent_navigation": False,
    "b5_trail_before_llm": False,
    "b5_trail_min_sessions": 0,
    "b5_broad_discovery": False,
    "filter_to_focus": False,
}


async def mock_fetch(u: str, *args, **kwargs):
    return await fixture_fetch(u)


@contextmanager
def patch_offline_fetch():
    """Mock only network fetch; leave adapters and enumerate logic untouched."""
    async def _fetch(u, *a, **k):
        return await fixture_fetch(u)

    with patch("src.platforms._fetch", side_effect=_fetch):
        from config import settings

        original = dict(settings.SETTINGS)
        settings.SETTINGS.update(OFFLINE_SETTINGS)
        try:
            yield
        finally:
            settings.SETTINGS.clear()
            settings.SETTINGS.update(original)
