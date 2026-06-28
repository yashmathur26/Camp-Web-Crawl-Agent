"""v3 Phase 3 — feature-based page-role classification.

Fixtures are HTML-shaped (real markup), per the roadmap's move off slug regexes.
(A full real-saved-HTML corpus replaces these once the Firecrawl pull lands; the
classifier contract is the same.)"""

from __future__ import annotations

from engine.extract.features import classify_role, page_features, role_of_page
from engine.model import Program, Session
from engine.validate.gate import gate_program

REG_HTML = """
<html><h1>Robotics Camp</h1>
<p>Youth summer day camp, ages 7-12. Week of July 14. $295.</p>
<form action="/checkout"><button>Add to Cart</button></form>
</html>"""

INFO_HTML = """
<html><h1>Creative Arts Camp</h1>
<p>A youth summer day camp for ages 6-12. Campers paint and perform.
Sessions run July 7 - July 18. Contact us to learn more.</p>
</html>"""

PERIPHERAL_HTML = """
<html><h1>About Us</h1>
<p>Our mission and history. Meet our staff and board. In the news: our alumni.
Read our privacy policy and refund policy. Directions and parking below.</p>
</html>"""


def test_registration_role_from_form_or_cart():
    role, f = role_of_page("https://p.org/robotics", REG_HTML,
                           "Robotics Camp ages 7-12 week of July 14 $295 add to cart",
                           name="Robotics Camp")
    assert role == "registration"
    assert f.has_enroll_form and f.has_cart_cta and f.has_price and f.has_date


def test_info_role_prose_plus_fields_no_affordance():
    text = ("Creative Arts Camp. A youth summer day camp for ages 6-12. "
            "Sessions run July 7 - July 18. Campers paint and perform. " * 8)
    role, f = role_of_page("https://p.org/arts", INFO_HTML, text, name="Creative Arts Camp")
    assert role == "info"
    assert not f.has_cart_cta and f.has_date and f.name_in_h1


def test_peripheral_role_about_alumni_news():
    text = ("About Us. Our mission and history. Meet our staff and board. "
            "In the news: our alumni. Privacy policy. Directions and parking. " * 4)
    role, _f = role_of_page("https://p.org/about", PERIPHERAL_HTML, text, name="Summer Camp")
    assert role == "peripheral"


def test_price_near_date_without_cart_is_registration():
    f = page_features("https://p.org/x", "", "Ages 8-12. July 7-11. $400 tuition.",
                      name="Camp")
    assert f.has_price and f.has_date
    assert classify_role(f) == "registration"


def test_gate_routes_peripheral_role_to_review():
    info = "https://prov.org/about-our-camp"
    text = ("Our mission and history. Meet our staff. Alumni news. " * 20)
    sess = Session(name="Our Story", info_url=info, dates="July 7-11", ages="8-12",
                   extractor="generic", name_source="title", page_role="peripheral")
    prog = Program(name="Our Story", provider_id="p", info_url=info)
    prog.sessions = [sess]
    res = gate_program(prog, fetched_text={info: text}, provider_name="Prov",
                       provider_host="prov.org")
    assert not res.published and res.review
    assert "peripheral" in res.review[0].evidence["review_reason"]
