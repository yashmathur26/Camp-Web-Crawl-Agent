"""Task 1.1: granularity column round-trips through write_session_outputs."""

from __future__ import annotations

import csv
import shutil

from config import settings
from src.data_layout import DATA_ROOT, town_slug
from src.platforms import make_session
from src.sessions import SESSION_CSV_COLUMNS, write_session_outputs

TOWN = "Zz_granularity_test"


def teardown_module(_module=None):
    shutil.rmtree(DATA_ROOT / town_slug(TOWN), ignore_errors=True)


def test_granularity_is_last_column():
    # Rule 6: .txt mirrors are positional — only append at the END.
    assert SESSION_CSV_COLUMNS[-1] == "granularity"


def test_make_session_defaults_to_session():
    s = make_session("Art Camp", "https://camp.org/register", dates="July 7")
    assert s["granularity"] == "session"


def test_write_outputs_round_trip_granularity():
    plain = make_session(
        "Art Camp",
        "https://camp.org/register",
        info_url="https://camp.org/art",
        ages="6-12",
        dates="July 7",
    )
    plain.pop("granularity")  # legacy row constructed without the key
    program = make_session(
        "Camp Org — Summer Program",
        "https://camp.org/signup",
        info_url="https://camp.org/summer",
        dates="June-Aug",
        granularity="program",
    )
    results = [
        {"url": "https://camp.org", "platform": "custom", "sessions": [plain, program]}
    ]
    orig = settings.SETTINGS.get("b5_validation_gate", True)
    settings.SETTINGS["b5_validation_gate"] = True
    try:
        csv_path, _txt, total = write_session_outputs(TOWN, results)
        assert total == 2
        with open(csv_path, newline="", encoding="utf-8") as f:
            rows = {r["name"]: r for r in csv.DictReader(f)}
        assert rows["Art Camp"]["granularity"] == "session"
        assert rows["Camp Org — Summer Program"]["granularity"] == "program"
    finally:
        settings.SETTINGS["b5_validation_gate"] = orig
