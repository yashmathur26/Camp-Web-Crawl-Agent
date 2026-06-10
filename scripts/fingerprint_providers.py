"""Fingerprint the registration/web platform each Lexington provider uses.

Fetches each provider's page (follow redirects), then scans the HTML + outbound
links for known registration-platform signatures. Prints a categorized report.
"""

import asyncio
import re
from urllib.parse import urlparse

import httpx

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# Real Lexington (or directly-serving-Lexington) provider pages worth probing.
PROVIDERS = {
    "Town of Lexington (gov)": "https://lexingtonma.gov/511/Recreation-Community-Programs",
    "LexRec (Human Services)": "https://lexrecma.myrec.com/info/activities/activities.aspx",
    "J.W. Hayden Rec Centre": "https://www.jwhayden.org/summer-camp",
    "Lexington Community Ed / Lexplorations": "https://lexingtoncommunityed.org/lexplorations/",
    "LexFarm": "https://lexfarm.org/education",
    "Waldorf School of Lexington": "https://thewaldorfschool.org/summer",
    "Summers Edge Day Camp": "https://summersedgedaycamp.com/",
    "Lexington Christian Academy": "https://lca.edu/summer",
    "Munroe Center for the Arts": "https://munroecenter.org/summer-camp.html",
    "The Robo Hub": "https://therobohub.com/summer-camp-2026",
    "Hancock Nursery School": "https://hancocknurseryschool.org/hns-summer",
    "Lexington United (soccer)": "https://lexingtonunited.org/spring-summer-vacation-clinics",
    "Viking Sports Camps": "https://vikingcamps.com/locations/lexington",
    "Lexington Playcare Center": "https://lexingtonplaycarecenter.org/summer-camp",
    "FUSE School": "https://fuseprogram.com/lexington-vacation-summer-program",
    "Lexington Debate Institute": "https://lexdebateinstitute.com/summer",
    "Goddard School Lexington": "https://goddardschool.com/schools/ma/lexington/lexington/our-school/special-programs/summer-camp",
    "Lexington Arts & Crafts Society": "https://students.arbitersports.com/organizations/search?query=Lexington+Arts+and+Crafts",
    "Lexington Symphony (Phoenix)": "https://lexingtonsymphony.org/phoenixproject",
    "MGH Aspire": "https://massgeneral.org/children/aspire/apply",
    "Drumlin Farm (Mass Audubon)": "https://massaudubon.org/places-to-explore/wildlife-sanctuaries/drumlin-farm",
    "Nike/US Sports Camps": "https://ussportscamps.com/basketball/massachusetts/lexington",
}

# Platform signatures: name -> regexes that appear in HTML or links.
SIGNATURES = {
    "WebTrac / myvscloud (Vermont Systems)": [r"myvscloud\.com", r"webtrac", r"wbwsc"],
    "MyRec.com": [r"myrec\.com"],
    "WooCommerce (WordPress store)": [r"woocommerce", r"wp-content/plugins/woocommerce", r"add-to-cart="],
    "WordPress (generic)": [r"wp-content", r"wp-json"],
    "ACTIVE Network / ActiveCommunities": [r"activecommunities\.com", r"activenetwork", r"apm\.activecommunities"],
    "CommunityPass": [r"register\.communitypass\.net", r"communitypass"],
    "RecDesk": [r"recdesk\.com"],
    "CivicRec / CivicPlus": [r"civicrec", r"civicplus", r"\.civicengage"],
    "PerfectMind": [r"perfectmind"],
    "Ultracamp": [r"ultracamp\.com"],
    "CampBrain": [r"campbrain"],
    "CampMinder": [r"campminder"],
    "Sawyer (hisawyer)": [r"hisawyer\.com", r"sawyer"],
    "Jackrabbit": [r"jackrabbitclass\.com", r"jackrabbittech"],
    "CampDoc": [r"campdoc\.com"],
    "Squarespace": [r"squarespace\.com", r"static1\.squarespace"],
    "Wix": [r"wix\.com", r"wixstatic"],
    "ArbiterSports / ArbiterRegistration": [r"arbitersports\.com", r"arbiter"],
    "Daxko (YMCA/club ops)": [r"daxko", r"operations\.daxko"],
    "Duda site builder": [r"dudaone", r"d\.cdn-website\.com", r"irp\.cdn-website\.com"],
}

LINK_RE = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)


async def probe(client: httpx.AsyncClient, name: str, url: str) -> dict:
    info = {"name": name, "url": url, "final": "", "status": 0, "hits": set(), "links_to": set(), "err": ""}
    try:
        r = await client.get(url, follow_redirects=True, timeout=20)
        info["status"] = r.status_code
        info["final"] = str(r.url)
        html = r.text or ""
        low = html.lower()
        for plat, pats in SIGNATURES.items():
            if any(re.search(p, low) for p in pats):
                info["hits"].add(plat)
        # outbound links to known registration hosts
        for href in LINK_RE.findall(html):
            h = href.lower()
            for plat, pats in SIGNATURES.items():
                if any(re.search(p, h) for p in pats):
                    info["links_to"].add(plat)
    except Exception as e:
        info["err"] = f"{type(e).__name__}: {str(e)[:60]}"
    return info


async def main():
    async with httpx.AsyncClient(headers={"User-Agent": UA}) as client:
        results = await asyncio.gather(*[probe(client, n, u) for n, u in PROVIDERS.items()])

    print("=" * 90)
    print("LEXINGTON PROVIDER PLATFORM FINGERPRINT")
    print("=" * 90)
    for r in results:
        print(f"\n● {r['name']}")
        print(f"   url:    {r['url']}")
        if r["err"]:
            print(f"   STATUS: ERROR  {r['err']}")
            continue
        redir = "  (redirected)" if r["final"].rstrip("/") != r["url"].rstrip("/") else ""
        print(f"   status: {r['status']}{redir}")
        if redir:
            print(f"   final:  {r['final']}")
        page = sorted(r["hits"]) or ["(none detected in page HTML)"]
        print(f"   page signals:  {', '.join(page)}")
        if r["links_to"]:
            print(f"   links out to:  {', '.join(sorted(r['links_to']))}")


asyncio.run(main())
