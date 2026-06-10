import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.filter_links import is_likely_camp_link  # noqa: E402
from src.link_quality import drop_reason, is_quality_camp_link  # noqa: E402


def test_class_category_is_not_likely_camp_link():
    assert not is_likely_camp_link(
        "https://lexingtoncommunityed.org/class-category/cooking",
        "Food, COOKING & Nutrition",
    )


def test_lexplorations_class_is_likely_camp_link():
    assert is_likely_camp_link(
        "https://lexingtoncommunityed.org/class/lexplorations-2026",
        "Lexplorations 2026",
    )


def test_aca_national_is_slop():
    assert drop_reason("https://www.acacamps.org/membership", "Membership")


def test_guide_referral_camp_kept():
    assert is_quality_camp_link("https://campneoc.com/", "NEOC")


def test_kentucky_jcc_is_slop():
    assert drop_reason("https://jcc.jewishva.org/camp-jcc", "Camp JCC")
