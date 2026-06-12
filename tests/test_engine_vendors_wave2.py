"""Engine v3 Phase 4 (wave 2): communityed store-API + sawyer — offline fixtures."""

from __future__ import annotations

import json
from pathlib import Path

from engine.extract.vendors.communityed import parse_products
from engine.extract.vendors.sawyer import pair_headings_to_sets

FIXTURES = Path("tests/fixtures")


def test_communityed_store_api_products():
    items = json.loads((FIXTURES / "communityed/store_products.json").read_text())
    products = parse_products(items)
    assert len(products) == 129                      # full Lexplorations camp set
    by_name = {p["name"]: p for p in products}
    food = next(p for p in products if p["name"].startswith("Food for Thought"))
    assert food["permalink"].endswith("/class/food-for-thought-june-29-july-2/")
    assert "june 29" in food["dates"].lower()
    assert all("/class/" in p["permalink"] for p in products)
    # after-school-care-only items excluded
    assert not any("after-school" in p["name"].lower() for p in products)


def test_sawyer_marketing_page_pairs():
    html = (FIXTURES / "sawyer/therobohub.com.html").read_text(errors="ignore")
    rows = pair_headings_to_sets(html)
    names = {r["name"] for r in rows}
    assert len(rows) >= 14                           # the robohub program roster
    assert "Robot Explorers" in names
    assert "Battling Robot Inventors with VEX IQ" in names
    robot = next(r for r in rows if r["name"] == "Robot Explorers")
    assert robot["info_url"].endswith("/activity-set/1687198")
    gr = next(r for r in rows if "Gr. 2-3" in r["name"])
    assert gr["ages"]                                 # grades extracted as evidence
