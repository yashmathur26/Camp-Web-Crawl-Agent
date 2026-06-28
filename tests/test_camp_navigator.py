from phase_b.camp_navigator import _rank_links_for_agent


def test_rank_links_prefers_camp_urls():
    seed = "https://cedarland.net/summer-camp"
    links = [
        {"url": "https://cedarland.net/contact", "text": "Contact"},
        {"url": "https://cedarland.net/summer-camp/application", "text": "Register"},
        {"url": "https://cedardale.campmanagement.com/enroll", "text": "Enroll"},
        {"url": "https://facebook.com/foo", "text": "Facebook"},
    ]
    ranked = _rank_links_for_agent(seed, links, cap=10)
    urls = [r["url"] for r in ranked]
    assert "https://cedarland.net/summer-camp/application" in urls
    assert "https://cedardale.campmanagement.com/enroll" in urls
    assert "https://facebook.com/foo" not in urls
