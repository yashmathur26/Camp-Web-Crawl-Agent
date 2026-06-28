"""v3 Phase 6L — link bundle: homepage_url, parent_url ladder, content-set dedup,
the two output surfaces, merge-back. Cases mirror the roadmap's per-provider
traces + edge-case table."""

from __future__ import annotations

import csv

from engine.model import Program, Provider, Session
from engine.run.links import (
    derive_homepage,
    derive_parent_url,
    firecrawl_content_urls,
    merge_back,
    parent_rung,
    write_link_views,
)


def _prov(host, seed=""):
    return Provider(name=host, host=host, town="Lexington", seed_url=seed or f"https://{host}/")


# --- homepage_url (§6L.1 + invariant §2.2.3) --------------------------------

def test_homepage_own_domain():
    assert derive_homepage(_prov("runningbrook.org"), "https://runningbrook.org/x") \
        == "https://runningbrook.org/"


def test_homepage_platform_hosted_never_bare_vendor_root():
    prov = _prov("majwhaydenweb.myvscloud.com",
                 seed="https://majwhaydenweb.myvscloud.com/webtrac/web/search.html")
    info = "https://majwhaydenweb.myvscloud.com/webtrac/web/iteminfo.html?FMID=1&Module=AR"
    hp = derive_homepage(prov, info)
    assert hp.endswith("/webtrac/web/search.html")     # catalog root, not myvscloud.com
    assert hp != "https://myvscloud.com/"


def test_homepage_platform_hosted_prefers_registry_own_site():
    prov = _prov("jwhayden.org",
                 seed="https://majwhaydenweb.myvscloud.com/webtrac/web/search.html")
    info = "https://majwhaydenweb.myvscloud.com/webtrac/web/iteminfo.html?FMID=1&Module=AR"
    assert derive_homepage(prov, info) == "https://jwhayden.org/"


# --- parent_url ladder (§6L.2) ----------------------------------------------

def test_rung1_own_info_page():
    s = Session(name="Excursions", info_url="https://rb.org/adventures/excursions",
                page_role="info", nearest_hub="https://rb.org/adventures")
    assert derive_parent_url(s, "https://rb.org/") == "https://rb.org/adventures/excursions"
    assert parent_rung(s, "https://rb.org/") == 1


def test_rung1_webtrac_platform_item_page():
    url = "https://x.myvscloud.com/webtrac/web/iteminfo.html?FMID=9&Module=AR"
    s = Session(name="Lower Camp", info_url=url, page_role="")   # vendor: no role
    assert derive_parent_url(s, "https://jwhayden.org/") == url   # rung 1 via platform id


def test_rung2_camp_only_in_hub():
    # info_url is itself a hub/section → not the camp's own page → nearest hub.
    s = Session(name="Camp X", info_url="https://rb.org/adventures",
                page_role="info", nearest_hub="https://rb.org/adventures")
    s2 = Session(name="Camp Y", info_url="https://rb.org/summer-camps",
                 page_role="info", nearest_hub="https://rb.org/programs/summer")
    assert derive_parent_url(s2, "https://rb.org/") == "https://rb.org/programs/summer"
    assert parent_rung(s2, "https://rb.org/") == 2


def test_rung3_homepage_floor():
    s = Session(name="Tiny Acorn", info_url="https://camptinyacorn.org/about",
                page_role="peripheral", nearest_hub="")
    assert derive_parent_url(s, "https://camptinyacorn.org/") == "https://camptinyacorn.org/"
    assert parent_rung(s, "https://camptinyacorn.org/") == 3


# --- Firecrawl content set dedup (§6L.3) ------------------------------------

def test_shared_hub_crawled_once():
    hub = "https://rb.org/adventures"
    progs = [Program(name="A", provider_id="p", sessions=[
        Session(name="A", info_url="https://rb.org/adventures/a", nearest_hub=hub),
        Session(name="B", info_url="https://rb.org/adventures/b", nearest_hub=hub),
    ])]
    urls = firecrawl_content_urls(progs)
    assert urls.count(hub) == 1
    assert "https://rb.org/adventures/a" in urls and "https://rb.org/adventures/b" in urls


def test_webtrac_canonical_dedup():
    progs = [Program(name="P", provider_id="p", sessions=[
        Session(name="C1",
                info_url="https://x.myvscloud.com/webtrac/web/iteminfo.html?FMID=5&Module=AR"),
        Session(name="C2",
                info_url="https://x.myvscloud.com/webtrac/web/iteminfo.html?Module=AR&FMID=5&_csrf_token=z"),
    ])]
    assert len(firecrawl_content_urls(progs)) == 1   # same FMID → one content URL


# --- the two surfaces (§4) ---------------------------------------------------

def test_write_link_views_columns_and_no_register_in_parent_csv(tmp_path):
    s = Session(name="Excursions", display_name="Running Brook — Excursions",
                info_url="https://rb.org/adventures/excursions",
                register_url="https://forms.gle/x", parent_url="https://rb.org/adventures/excursions",
                nearest_hub="https://rb.org/adventures", register_confidence="low",
                dates="July 7-18", ages="8-10", price="$300")
    progs = [Program(name="Excursions", provider_id="p", sessions=[s])]
    counts = write_link_views(tmp_path, progs, "Lexington")
    assert counts == {"parent_camps.csv": 1, "firecrawl_manifest.csv": 1}
    parent = list(csv.DictReader(open(tmp_path / "parent_camps.csv")))[0]
    assert set(parent) == {"camp_id", "display_name", "parent_url", "dates", "ages", "price", "town"}
    assert "register_url" not in parent and "info_url" not in parent
    assert parent["parent_url"] == "https://rb.org/adventures/excursions"
    manifest = list(csv.DictReader(open(tmp_path / "firecrawl_manifest.csv")))[0]
    assert manifest["register_url"] == "https://forms.gle/x"
    assert manifest["camp_id"] == s.session_id


# --- merge-back (§4.3) -------------------------------------------------------

def test_merge_back_enriches_content_not_parent_url():
    parent = [{"camp_id": "c1", "display_name": "X", "parent_url": "https://rb.org/x",
               "dates": "", "ages": "", "price": ""}]
    fc = {"c1": {"description": "Full description from Firecrawl",
                 "dates": "July 7 - July 18", "price": "$320"}}
    out = merge_back(parent, fc)[0]
    assert out["parent_url"] == "https://rb.org/x"          # unchanged
    assert out["dates"] == "July 7 - July 18" and out["price"] == "$320"
    assert out["description"] == "Full description from Firecrawl"
