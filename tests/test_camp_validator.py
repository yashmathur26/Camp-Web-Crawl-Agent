"""Tests for Ollama camp link validation helpers."""

import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from phase_b.camp_validator import (  # noqa: E402
    filter_rows_with_llm,
    should_require_llm,
    should_skip_llm,
)


class CampValidatorTests(unittest.IsolatedAsyncioTestCase):
    def test_skip_llm_for_myrec_program(self):
        self.assertTrue(
            should_skip_llm(
                "https://lexrecma.myrec.com/info/activities/program_details.aspx?ProgramID=30941"
            )
        )

    def test_require_llm_for_town_gov_noise(self):
        self.assertTrue(
            should_require_llm("https://lexingtonma.gov/1566/Senior-Parking-Program")
        )

    def test_skip_llm_not_for_generic_gov_hub(self):
        self.assertFalse(
            should_skip_llm("https://lexingtonma.gov/511/Recreation-Community-Programs")
        )

    async def test_filter_disabled_returns_all(self):
        rows = [{"url": "https://example.com/camp", "link_text": "Camp", "town_hint": "Lexington"}]
        with patch("phase_b.camp_validator.SETTINGS", {"ollama_validate_links": False}):
            kept, rejected = await filter_rows_with_llm(rows, {}, fetch_page_text=AsyncMock())
        self.assertEqual(kept, rows)
        self.assertEqual(rejected, 0)

    async def test_filter_rejects_via_llm(self):
        rows = [
            {
                "url": "https://lexingtonma.gov/1566/Senior-Parking-Program",
                "link_text": "Senior Parking",
                "town_hint": "Lexington",
            }
        ]
        with (
            patch(
                "phase_b.camp_validator.SETTINGS",
                {
                    "ollama_validate_links": True,
                    "ollama_validate_max_fetches_per_source": 5,
                    "ollama_validate_max_calls_per_source": 30,
                    "ollama_validate_max_chars": 1000,
                    "ollama_validate_timeout_s": 10,
                    "ollama_model": "llama3.2:1b",
                    "ollama_filter_model": "llama3.2:1b",
                },
            ),
            patch("phase_b.camp_validator.is_available", return_value=True),
            patch("phase_b.camp_validator._load_verdict_cache", return_value={}),
            patch("phase_b.camp_validator._save_verdict_cache"),
            patch(
                "phase_b.camp_validator.classify_camp_page",
                return_value=(False, "Senior parking is not a youth camp"),
            ),
        ):
            kept, rejected = await filter_rows_with_llm(
                rows,
                {},
                fetch_page_text=AsyncMock(return_value="Senior resident parking permits"),
            )
        self.assertEqual(kept, [])
        self.assertEqual(rejected, 1)

    async def test_filter_caps_llm_calls(self):
        rows = [
            {
                "url": f"https://example.org/community/page-{n}",
                "link_text": f"Program {n}",
                "town_hint": "Lexington",
            }
            for n in range(5)
        ]
        with (
            patch(
                "phase_b.camp_validator.SETTINGS",
                {
                    "ollama_validate_links": True,
                    "ollama_validate_max_fetches_per_source": 5,
                    "ollama_validate_max_calls_per_source": 2,
                    "ollama_validate_max_chars": 1000,
                    "ollama_validate_timeout_s": 10,
                    "ollama_model": "llama3.2:1b",
                    "ollama_filter_model": "llama3.2:1b",
                },
            ),
            patch("phase_b.camp_validator.is_available", return_value=True),
            patch("phase_b.camp_validator._load_verdict_cache", return_value={}),
            patch("phase_b.camp_validator._save_verdict_cache"),
            patch(
                "phase_b.camp_validator.classify_camp_page",
                return_value=(True, "youth camp"),
            ),
        ):
            kept, rejected = await filter_rows_with_llm(rows, {}, fetch_page_text=AsyncMock())
        self.assertEqual(len(kept), 2)
        self.assertEqual(rejected, 3)


if __name__ == "__main__":
    unittest.main()
