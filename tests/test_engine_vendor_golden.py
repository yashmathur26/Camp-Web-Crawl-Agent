"""Phase 0 vendor golden: the clean WebTrac / CommunityEd / MyRec rows that are
accurate TODAY must keep publishing to the confirmed tier through every gate
change the accuracy roadmap makes (guardrail: "don't touch what works").

These assert the GATE contract for representative vendor sessions — that a real
catalog/listing row still lands in `published` with the right verdict, its bare
identity name is untouched, and the provider-prefixed label rides in
display_name. They are characterization locks: if a Phase 1–5 change starts
sending vendor rows to review/gap, one of these fails.
"""

from __future__ import annotations

from engine.model import Program, Session
from engine.validate.gate import gate_program

RICH = ("{name}. Youth summer day camp, ages 5-12. Add To Cart. $390 per week. "
        "June, July and August sessions for kids and children. " * 10)


def _gate(sess: Session, *, camp_scoped: bool, provider_name: str,
          provider_host: str, text: str | None = None):
    prog = Program(name=sess.name, provider_id="p", info_url=sess.info_url,
                   camp_scoped=camp_scoped)
    prog.sessions = [sess]
    body = text if text is not None else RICH.format(name=sess.name)
    return gate_program(
        prog, fetched_text={sess.info_url: body},
        provider_name=provider_name, provider_host=provider_host,
    )


def test_webtrac_iteminfo_row_confirmed_parent_ready():
    url = "https://majwhaydenweb.myvscloud.com/webtrac/web/iteminfo.html?FMID=1&Module=AR"
    sess = Session(name="Lower Camp", info_url=url, register_url=url,
                   dates="07/06/2026 - 07/10/2026", ages="5-7", extractor="webtrac")
    res = _gate(sess, camp_scoped=True, provider_name="J.W. Hayden Center",
                provider_host="jwhayden.org")
    assert res.published and not res.review
    s = res.published[0]
    assert s.verdict == "parent_ready"
    assert s.name == "Lower Camp"                       # identity untouched
    assert s.display_name == "J.W. Hayden Center — Lower Camp"


def test_myrec_listing_row_confirmed_info_confirmed():
    info = "https://lexrecma.myrec.com/info/activities/default.aspx?type=camps"
    text = ("Chess Summer Clinic - August 10-14. Youth ages 8-12. LexRec summer "
            "programs listing with many camps for kids. " * 12)
    sess = Session(name="Chess Summer Clinic", info_url=info,
                   dates="August 10-14", ages="8-12", extractor="myrec")
    res = _gate(sess, camp_scoped=False, provider_name="Lexington Recreation",
                provider_host="lexrecma.myrec.com", text=text)
    assert res.published and not res.review
    assert res.published[0].verdict == "info_confirmed"
    assert res.published[0].name == "Chess Summer Clinic"


def test_communityed_class_row_confirmed():
    info = "https://lexingtoncommunityed.org/class/lego-robotics-camp"
    text = ("LEGO Robotics Camp. A youth summer camp for ages 7-11. Build and "
            "program robots. Add to cart. $295. Week of July 14. " * 8)
    sess = Session(name="LEGO Robotics Camp", info_url=info, register_url=info,
                   dates="July 14 - July 18", ages="7-11", extractor="communityed")
    res = _gate(sess, camp_scoped=True, provider_name="Lexington Community Ed",
                provider_host="lexingtoncommunityed.org", text=text)
    assert res.published and not res.review
    assert res.published[0].name == "LEGO Robotics Camp"


def test_vendor_row_on_platform_host_not_blocked_by_same_host_rule():
    """A vendor row's info_url lives on the platform domain (myvscloud), NOT the
    provider's registrable domain — the same-host rule must NOT touch it (it only
    applies to generic-path rows)."""
    url = "https://townxweb.myvscloud.com/webtrac/web/iteminfo.html?FMID=9&Module=AR"
    sess = Session(name="Robotics Camp", info_url=url, register_url=url,
                   dates="July 7-11", ages="8-12", extractor="webtrac")
    res = _gate(sess, camp_scoped=True, provider_name="Town X Rec",
                provider_host="townx.gov")
    assert res.published and not res.review


def test_fixture_set_tier_accuracy_is_100pct():
    """The labeled gate-tier fixtures all route to their hand-labeled tier."""
    from engine.eval.fixtures import report

    rep = report()
    misrouted = [(label, exp, got) for label, exp, got, ok in rep.rows if not ok]
    assert rep.tier_accuracy == 1.0, f"misrouted fixtures: {misrouted}"
    assert rep.confirmed_precision == 1.0
