"""roadmap2 Phase 2: schema.org JSON-LD extraction (Sawyer/active.com style)."""

from __future__ import annotations

from src.structured_extract import extract_jsonld_events, structured_summary

# A Sawyer-style page: visible DOM is "See Details" chrome, real data is JSON-LD.
SAWYER_HTML = """
<html><body>
<a href="#">See Details</a><a href="#">Register</a>
<script type="application/ld+json">
{"@context":"https://schema.org","@graph":[
  {"@type":"Event","name":"Robotics Summer Camp — Week 1","startDate":"2026-07-06T09:00",
   "endDate":"2026-07-10T15:00","offers":{"@type":"Offer","price":"425","priceCurrency":"USD",
   "url":"https://the-robo-hub.hisawyer.com/enroll/1687373"}},
  {"@type":"Course","name":"LEGO Engineering — Week 2","startDate":"2026-07-13",
   "offers":{"price":"399"}}
]}
</script>
</body></html>
"""

GENERIC_EVENT_HTML = """
<script type="application/ld+json">
[{"@type":"ChildrensEvent","name":"Art Adventure Camp","startDate":"2026-08-03"}]
</script>
"""

NO_JSONLD_HTML = "<html><body><h1>Welcome</h1><a>Back to Top</a></body></html>"


def test_extracts_event_and_course_names_dates_price():
    events = extract_jsonld_events(SAWYER_HTML)
    names = [e["name"] for e in events]
    assert "Robotics Summer Camp — Week 1" in names
    assert "LEGO Engineering — Week 2" in names
    robo = next(e for e in events if e["name"].startswith("Robotics"))
    assert robo["dates"] == "2026-07-06 – 2026-07-10"
    assert robo["price"] == "$425"
    assert robo["register_url"] == "https://the-robo-hub.hisawyer.com/enroll/1687373"


def test_handles_single_object_and_currency():
    events = extract_jsonld_events(GENERIC_EVENT_HTML)
    assert len(events) == 1
    assert events[0]["name"] == "Art Adventure Camp"
    assert events[0]["dates"] == "2026-08-03"


def test_no_jsonld_returns_empty():
    assert extract_jsonld_events(NO_JSONLD_HTML) == []
    assert extract_jsonld_events("") == []


def test_malformed_jsonld_is_ignored():
    bad = '<script type="application/ld+json">{not valid json,,}</script>'
    assert extract_jsonld_events(bad) == []


def test_structured_summary_lists_programs():
    events = extract_jsonld_events(SAWYER_HTML)
    summary = structured_summary(events)
    assert "STRUCTURED PROGRAMS" in summary
    assert "Robotics Summer Camp" in summary
    assert "$425" in summary
    assert structured_summary([]) == ""
