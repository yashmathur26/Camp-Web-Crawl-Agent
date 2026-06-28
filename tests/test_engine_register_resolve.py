"""v3 Phase 2 — register_url resolver: confidence tiers, no aliasing, link
equality. Each case is an edge from the roadmap's link-layer table."""

from __future__ import annotations

from engine.extract.register import resolve_register, verdict_ceiling
from engine.fetch.urls import canonical_register_url, register_platform_id, normalize_url
from engine.model import Program, Session
from engine.validate.gate import gate_program


def _link(url, text=""):
    return {"url": url, "text": text}


# --- link equality (§2.3) ----------------------------------------------------

def test_canonical_collapses_webtrac_to_fmid_module():
    a = "https://x.myvscloud.com/webtrac/web/iteminfo.html?FMID=50801580&Module=AR"
    b = "https://x.myvscloud.com/webtrac/web/iteminfo.html?Module=AR&FMID=50801580&_csrf_token=z"
    assert canonical_register_url(a) == canonical_register_url(b)
    assert register_platform_id(a) == "x.myvscloud.com|fmid|50801580"


# --- Tier HIGH ---------------------------------------------------------------

def test_high_known_platform_outbound_link_cross_domain():
    own = [_link("https://communitykangaroo.com/about"),
           _link("https://register.capturepoint.com/cart?prog=5", "Register")]
    rr = resolve_register("https://abce.abschools.org/camp", own_links=own, own_html="")
    assert rr.register_url == "https://register.capturepoint.com/cart?prog=5"
    assert rr.confidence == "high" and not rr.register_is_info


def test_high_prefers_own_page_over_hub_and_item_id_over_root():
    own = [_link("https://x.myvscloud.com/webtrac/web/search.html?Module=AR")]
    hub = [_link("https://x.myvscloud.com/webtrac/web/iteminfo.html?FMID=9&Module=AR")]
    # own-page link wins on placement even though hub's carries an item id...
    rr = resolve_register("https://prov.org/camp", own_links=own, own_html="",
                          nearest_hub="https://prov.org/camps", hub_links=hub)
    assert rr.confidence == "high"
    assert "search.html" in rr.register_url      # own-page placement scored higher


def test_high_rejects_bad_register_targets():
    own = [_link("https://x.myvscloud.com/webtrac/web/account/login.html", "Login")]
    rr = resolve_register("https://prov.org/camp", own_links=own, own_html="")
    assert not rr.found        # login dead-end filtered → falls through to NONE


# --- Tier MEDIUM -------------------------------------------------------------

def test_medium_on_page_cart_affordance_is_combined_page():
    html = "Robotics Camp. Ages 7-12. Add To Cart. $295. Week of July 14." * 6
    rr = resolve_register("https://prov.org/robotics", own_links=[], own_html=html)
    assert rr.confidence == "medium"
    assert rr.register_url == "https://prov.org/robotics" and rr.register_is_info


def test_medium_form_action_when_distinct():
    html = ("Camp. Register now. add to cart "
            "<form action='/enroll/submit' method='post'></form>" * 3)
    rr = resolve_register("https://prov.org/camp", own_links=[], own_html=html)
    assert rr.confidence == "medium"
    assert rr.register_url.endswith("/enroll/submit") and not rr.register_is_info


# --- Tier LOW + NONE ---------------------------------------------------------

def test_low_intent_anchor_confirmed_by_fetch():
    own = [_link("https://forms.gle/abcd1234", "Register here")]
    fetched = ("Camp registration form. Add to cart to enroll now. " * 20, [], "")
    rr = resolve_register("https://prov.org/camp", own_links=own, own_html="",
                          fetch=lambda u: fetched)
    assert rr.confidence == "low"
    assert rr.register_url == "https://forms.gle/abcd1234"


def test_low_discarded_when_fetch_shows_no_affordance():
    own = [_link("https://prov.org/register", "Register")]
    rr = resolve_register("https://prov.org/camp", own_links=own, own_html="",
                          fetch=lambda u: ("just a description, no signup here " * 30, [], ""))
    assert not rr.found and rr.confidence == ""


def test_none_when_nothing_found_is_not_a_failure():
    rr = resolve_register("https://prov.org/camp", own_links=[], own_html="just prose")
    assert rr.register_url == "" and rr.confidence == "" and not rr.register_is_info


# --- verdict ceiling ---------------------------------------------------------

def test_verdict_ceiling_table():
    assert verdict_ceiling("high", evidence_clean=True) == "parent_ready"
    assert verdict_ceiling("medium", evidence_clean=True) == "parent_ready"
    assert verdict_ceiling("medium", evidence_clean=False) == "needs_review"
    assert verdict_ceiling("low", evidence_clean=True) == "needs_review"
    assert verdict_ceiling("", evidence_clean=True) == "info_confirmed"


# --- gate integration: never alias; combined page marked -----------------

def test_gate_marks_webtrac_combined_page_register_is_info():
    url = "https://majwhaydenweb.myvscloud.com/webtrac/web/iteminfo.html?FMID=1&Module=AR"
    sess = Session(name="Lower Camp", info_url=url, register_url=url,
                   dates="07/06/2026 - 07/10/2026", ages="5-7", extractor="webtrac")
    prog = Program(name="Lower Camp", provider_id="p", info_url=url, camp_scoped=True)
    prog.sessions = [sess]
    rich = ("Lower Camp. Youth summer day camp ages 5-7. Add To Cart. $390. "
            "June and July. webtrac " * 10)
    res = gate_program(prog, fetched_text={url: rich}, provider_name="Hayden",
                       provider_host="jwhayden.org")
    assert res.published
    s = res.published[0]
    assert s.register_is_info is True and s.register_confidence == "high"
    assert s.verdict == "parent_ready"


def test_gate_low_confidence_routes_to_review():
    info = "https://prov.org/adventure-camp"
    sess = Session(name="Adventure Camp", info_url=info, register_url="https://forms.gle/x",
                   dates="July 7-11", ages="8-12", extractor="generic",
                   register_confidence="low", name_source="title")
    prog = Program(name="Adventure Camp", provider_id="p", info_url=info)
    prog.sessions = [sess]
    text = "Adventure Camp youth summer day camp ages 8-12 July sessions. " * 12
    res = gate_program(prog, fetched_text={info: text}, provider_name="Prov",
                       provider_host="prov.org")
    assert not res.published and res.review
    assert "confidence low" in res.review[0].evidence["review_reason"]
