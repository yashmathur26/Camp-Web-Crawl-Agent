"""Tests for enrollment signal extraction."""

from phase_b.enrollment_signals import extract_enrollment_signals, verify_registrable


WEBTRAC_HTML = """
<html><body>
<h1>Summer Day Camp Week 3</h1>
<p>Ages 8-12. Program fee $425.</p>
<a href="addtocart.aspx">Add to Cart</a>
</body></html>
"""

WOO_HTML = """
<div class="woocommerce">
  <span class="woocommerce-Price-amount">$350</span>
  <button class="single_add_to_cart_button">Add to cart</button>
  <p>Summer LEGO camp ages 7-10</p>
</div>
"""

BROCHURE_HTML = """
<h1>Our Summer Camps</h1>
<p>We offer amazing programs for kids during June and July.</p>
<p>Contact us to register or download our brochure.</p>
"""


def test_webtrac_parent_ready():
    url = "https://ymca.myvscloud.com/webtrac/web/iteminfo.html?FMID=12345"
    sig = extract_enrollment_signals(url, WEBTRAC_HTML, session_name="Day Camp")
    assert sig.auto_verdict == "parent_ready"
    assert sig.has_cart_cta
    assert verify_registrable(url, WEBTRAC_HTML).auto_verdict == "parent_ready"


def test_woo_parent_ready():
    url = "https://lexingtoncommunityed.org/class/lego-summer/"
    sig = extract_enrollment_signals(url, WOO_HTML, session_name="LEGO Camp")
    assert sig.auto_verdict == "parent_ready"
    assert sig.has_price


def test_brochure_only():
    url = "https://example.com/summer-camps"
    sig = extract_enrollment_signals(url, BROCHURE_HTML, session_name="Summer Camp")
    assert sig.auto_verdict == "brochure_only"
    assert "brochure_only" in sig.blockers


def test_teens_hub_rejected():
    url = "https://bostonjcc.org/program/teens"
    sig = extract_enrollment_signals(url, "<p>Teen programs</p>", session_name="Teens")
    assert sig.auto_verdict == "wrong_audience"
