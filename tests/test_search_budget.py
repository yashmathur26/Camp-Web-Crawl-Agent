"""Discovery-expansion roadmap: population-scaled budget, adaptive yield-stop,
prioritized query pool, and institution-camps output."""

from __future__ import annotations

from phase_c.institution_output import institution_kind, write_institution_camps_txt
from phase_a.search_budget import (
    YieldStopper,
    institution_queries,
    prioritized_queries,
    population_of,
    town_budget,
)


# --- population + ceilings ---------------------------------------------------

def test_population_lookup_includes_extra_cities():
    assert population_of("Waltham") == 65218
    assert population_of("Boston") == 675647            # extra (non-Middlesex) city
    assert population_of("Nowheresville") == 23000      # unknown -> county-median default


def test_ceilings_scale_with_population():
    a = town_budget("Ashby")["phase_a"]          # ~3k
    w = town_budget("Waltham")["phase_a"]         # ~65k + institutions
    b = town_budget("Boston")["phase_a"]          # ~676k + institutions
    assert a < w < b
    # operator anchors: small ~floor, Boston ~5x, all under the hard cap
    assert 25 <= a <= 40
    assert b <= 400
    # Waltham earns an institution boost (Bentley + Brandeis + schools)
    assert town_budget("Waltham")["institutions"] > 0


def test_curated_institution_queries_present_for_waltham():
    q = institution_queries("Waltham")
    joined = " ".join(q).lower()
    assert any("bentley" in x.lower() for x in q)
    assert any("brandeis" in x.lower() for x in q)
    assert "gann academy" in joined          # private school
    assert "waltham high school" in joined   # public high


def test_prioritized_pool_orders_curated_first_then_tail():
    must, tail = prioritized_queries("Waltham", "MA")
    assert must and tail
    # curated institution queries are the must-run slice
    assert any("Bentley" in m for m in must)
    # core keywords + generic institution + activity expansions live in the tail
    assert any("community education" in t for t in tail)
    assert any("private school summer camp" in t for t in tail)
    # no overlap between must and tail
    assert not (set(m.lower() for m in must) & set(t.lower() for t in tail))


def test_small_town_has_no_curated_must_but_still_has_generic_tail():
    must, tail = prioritized_queries("Ashby", "MA")
    assert must == []                                  # no curated institutions
    assert any("high school summer camp" in t for t in tail)  # generic discovery still runs


# --- adaptive yield-stop -----------------------------------------------------

def test_yield_stopper_stops_when_dry_after_floor():
    s = YieldStopper(floor=3, window=3)
    # 3 productive searches (each a new host), then 3 dry
    for h in ("a.org", "b.org", "c.org"):
        s.record({h})
        assert not s.should_stop()           # window not full of zeros yet
    for _ in range(3):
        s.record(set())
    assert s.should_stop()                    # last 3 searches found nothing new


def test_yield_stopper_keeps_going_while_productive():
    s = YieldStopper(floor=2, window=3)
    for i in range(10):
        s.record({f"host{i}.org"})            # always a new host
    assert not s.should_stop()


def test_yield_stopper_respects_floor():
    s = YieldStopper(floor=5, window=2)
    s.record(set()); s.record(set())          # dry, but below floor
    assert not s.should_stop()


# --- institution-camps output ------------------------------------------------

def test_institution_kind_classification():
    assert institution_kind("bentley.edu", "Waltham") == "college"
    assert institution_kind("gann.org", "Waltham") is None         # not curated/heuristic
    assert institution_kind("gannacademy.org", "Waltham") == "private"
    assert institution_kind("walthampublicschools.org", "Waltham") == "public"
    # dynamic heuristics for uncurated towns
    assert institution_kind("mit.edu", "Somerville") == "college"
    assert institution_kind("watertown.k12.ma.us", "Watertown") == "public"
    assert institution_kind("randomcamp.com", "Waltham") is None


def test_write_institution_camps_txt(tmp_path):
    rows = [
        {"name": "Bentley Pre-College Business", "info_url": "https://bentley.edu/pre-college",
         "register_url": "", "dates": "July 6-17", "ages": "grades 10-12", "price": "$2500"},
        {"name": "Gann Summer Arts", "info_url": "https://gannacademy.org/summer",
         "register_url": "", "dates": "", "ages": "11-14", "price": ""},
        {"name": "Some Rec Camp", "info_url": "https://walthamrec.org/camp",  # not an institution
         "register_url": "", "dates": "", "ages": "", "price": ""},
    ]
    out = write_institution_camps_txt("Waltham", rows, tmp_path / "WALTHAM_INSTITUTION_CAMPS.txt")
    text = out.read_text()
    assert "COLLEGES & UNIVERSITIES" in text and "Bentley Pre-College Business" in text
    assert "PRIVATE / PREP SCHOOLS" in text and "Gann Summer Arts" in text
    assert "Some Rec Camp" not in text          # non-institution row excluded
    assert "Institution-hosted camps found: 2" in text
