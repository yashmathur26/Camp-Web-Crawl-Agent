"""Task 0.1 helper: assemble ground-truth rows from CAPTURED REAL catalogs.

This script only transcribes what the captured fixtures (real responses saved
from the live sites) show a parent would see — it does not crawl, guess, or
filter by keywords. The youth-summer selection for MyRec is encoded explicitly
below (reviewed by hand, like a parent reading the catalog). Long-tail
providers are appended manually in engine/eval/ground_truth/lexington.csv
after live review — see ground_truth/README.md for provenance.
"""

from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "engine/eval/ground_truth/lexington.csv"

NOISE_TEXT = {"share", "enrollment count details", ""}


def webtrac_rows() -> list[dict]:
    """Hayden: one row per (program, date window) from the two catalog captures."""
    rows: list[dict] = []
    for fixture in (
        "tests/fixtures/webtrac/majwhaydenweb.myvscloud.com.catalog.meta.json",
        "tests/fixtures/webtrac/majwhaydenweb.myvscloud.com.catalog_specialty.meta.json",
    ):
        meta = json.loads((ROOT / fixture).read_text())
        # The catalog interleaves: name-link then date-link for the same FMID.
        by_fmid: dict[str, dict] = {}
        for link in meta.get("links", []):
            url = link.get("url", "")
            text = (link.get("text") or "").strip()
            m = re.search(r"FMID=(\d+)", url)
            if "iteminfo" not in url.lower() or not m or text.lower() in NOISE_TEXT:
                continue
            fmid = m.group(1)
            slot = by_fmid.setdefault(
                fmid,
                {"name": "", "dates": "",
                 "info_url": f"https://majwhaydenweb.myvscloud.com/webtrac/web/iteminfo.html?FMID={fmid}&Module=AR"},
            )
            if re.match(r"^\d{2}/\d{2}/\d{4}", text):
                slot["dates"] = text.replace(" -", " - ")
            else:
                slot["name"] = text
        for slot in by_fmid.values():
            if slot["name"]:
                rows.append(
                    {"provider_host": "jwhayden.org", "program_name": slot["name"],
                     "session_dates": slot["dates"], "true_info_url": slot["info_url"]}
                )
    return rows


# LexRec youth-summer selection — every entry transcribed from the captured
# catalog (tests/fixtures/myrec/lexrecma.myrec.com.meta.json), reviewed by hand.
# Excluded on review: senior services, adult fitness (Tai Chi/Pilates/yoga/...),
# spring-season clinics, leagues, donations, lunches, trips, tournaments.
MYREC_YOUTH_SUMMER = [
    "Leader in Training - Application",
    "Swim Team 10 & Under Week (full season)",
    "Spring Adaptive Quickball: Youth (6-11)",
    "Youth Adaptive Tennis Lessons (Ages 6-11)",
    "Archery - July 13-16",
    "Blue Sox Week 1 - Ages 7-10",
    "Challenger Foundational Skills Camp - July 20th-July 24th (Half Day)",
    "Minuteman Boys Hoop (half day)",
    "Summer 3v3: 4th/5th/6th Grade",
    "USTA Tennis in the Parks: Red Ball (ages 6-7)",
    "Youth Tennis Clinic - Week 1",
    "Sports Zone - Active Minds Active Bodies",
    "Viking Basketball Camp",
    "RAD Kids w/Lexington Police Department",
    "Chess Summer Clinic - August 10-14",
    "Dungeons & Dragons Adventures - NEW Players",
    "FC Academy - Filmmaking & Special Effects",
    "KTK Summer Clinic - July 20 - 24",
    "Right Brain Curriculum - Minecraft Innovators & Lego Challenges",
    "Buildwave - Summer Clinic",
    "Circuit Lab: Circuit Makers 101 & Robot Commanders 101",
    "Snapology - Mining & Building and Mega Machines Robotics",
    "Golf Clinic - Summer",
    "Challenger Tiny Tykes Soccer - Ages 2 & 3 from 3:00-3:45pm",
    "Fishing Clinic (Pre-K)",
    "Youth Track Clinic",
]


def myrec_rows() -> list[dict]:
    meta = json.loads(
        (ROOT / "tests/fixtures/myrec/lexrecma.myrec.com.meta.json").read_text()
    )
    url_by_name: dict[str, str] = {}
    for link in meta.get("links", []):
        text = (link.get("text") or "").strip()
        if "program_details" in (link.get("url") or "").lower() and text:
            url_by_name.setdefault(text, link["url"])
    rows = []
    missing = []
    for name in MYREC_YOUTH_SUMMER:
        url = url_by_name.get(name)
        if not url:
            missing.append(name)
            continue
        m = re.search(r"(?:july|august|june)[^,)]*(?:\s*[-–]\s*[a-z]*\s*\d{1,2}[a-z]{0,2})?", name, re.I)
        rows.append(
            {"provider_host": "lexrecma.myrec.com", "program_name": name,
             "session_dates": m.group(0).strip() if m else "", "true_info_url": url}
        )
    if missing:
        print(f"WARN: {len(missing)} selected names not found in fixture: {missing}", file=sys.stderr)
    return rows


def lexplorations_rows() -> list[dict]:
    """CommunityEd/Lexplorations: full camp set from the live WooCommerce store
    API (captured to tests/fixtures/communityed/store_products.json). The
    /class/{slug} permalink IS the info page. Weeks one-six are the camps;
    pure after-school-care items are excluded."""
    import html as html_mod

    items = json.loads(
        (ROOT / "tests/fixtures/communityed/store_products.json").read_text()
    )
    week_slugs = {"week-one", "week-two", "week-three", "week-four", "week-five", "week-six"}
    rows = []
    for it in items:
        cats = {c.get("slug") for c in (it.get("categories") or [])}
        if not (cats & week_slugs):
            continue
        name = html_mod.unescape(it["name"]).strip()
        m = re.search(r"\(([^)]*(?:june|july|august)[^)]*)\)", name, re.I)
        rows.append(
            {"provider_host": "lexingtoncommunityed.org", "program_name": name,
             "session_dates": m.group(1).strip() if m else "",
             "true_info_url": it["permalink"]}
        )
    return rows


# Robohub programs: transcribed from the live marketing page (saved to
# tests/fixtures/sawyer/therobohub.com.html); each pairs a program heading with
# its Sawyer activity-set link (the info page).
ROBOHUB_PROGRAMS = [
    ("Junior Design Squad", "1687230"),
    ("Robot Explorers", "1687198"),
    ("Stories and STEAM Explorers", "1686801"),
    ("Design Squad Crafters", "1687267"),
    ("Planes, Drones and Rockets: Gr. 2-3", "1687232"),
    ("Tech Crafters", "1686804"),
    ("Battling Robot Crafters", "1687204"),
    ("Math and Vex Robotics Rising 3rd Through 6th Grade", "1837146"),
    ("App Inventor with AI and Data: Gr. 4-6", "1687276"),
    ("Electricity Engineers", "1687337"),
    ("Battling Robot Engineers", "1687195"),
    ("Planes, Drones and Rockets: Gr. 4-6", "1687367"),
    ("Design Squad Makers", "1687205"),
    ("App Inventor with AI and Data: Gr. 6-9", "1687340"),
    ("Battling Robot Inventors with VEX IQ", "1687281"),
]

# Long-tail providers: program-level rows transcribed from live pages fetched
# 2026-06-11 (see ground_truth/README.md for per-provider provenance + the
# providers deliberately left at zero rows).
LONG_TAIL = [
    ("thewaldorfschool.org", "WSL Summer Program", "June 29 - August", "https://thewaldorfschool.org/summer"),
    ("summersedgedaycamp.com", "Summer's Edge Day Camp", "", "https://summersedgedaycamp.com/"),
    ("summersedgedaycamp.com", "Summer's Edge Tennis School", "", "https://summersedgedaycamp.com/"),
    ("lexfarm.org", "LexFarm Summer Camp", "", "https://lexfarm.org/education"),
    ("hancocknurseryschool.org", "HNS Summer", "6/22-6/26", "https://hancocknurseryschool.org/hns-summer"),
    ("hancocknurseryschool.org", "HNS Summer", "7/6-7/10", "https://hancocknurseryschool.org/hns-summer"),
    ("hancocknurseryschool.org", "HNS Summer", "7/13-7/17", "https://hancocknurseryschool.org/hns-summer"),
    ("hancocknurseryschool.org", "HNS Summer", "7/20-7/24", "https://hancocknurseryschool.org/hns-summer"),
    ("hancocknurseryschool.org", "HNS Summer", "7/27-7/31", "https://hancocknurseryschool.org/hns-summer"),
    ("lexingtonunited.org", "June Kick Off the Summer Clinic", "June", "https://lexingtonunited.org/spring-summer-vacation-clinics"),
    ("lexingtonunited.org", "July Coed Mid-Summer Clinic", "July", "https://lexingtonunited.org/spring-summer-vacation-clinics"),
    ("lexingtonunited.org", "August Preseason Clinic", "August", "https://lexingtonunited.org/spring-summer-vacation-clinics"),
    ("vikingcamps.com", "Grades K-8 Multi Sport Camps", "", "https://vikingcamps.com/locations/lexington"),
    ("vikingcamps.com", "Pre-K Multi Sport Camps", "", "https://vikingcamps.com/locations/lexington"),
    ("vikingcamps.com", "Preschool Multi Sport Camps", "", "https://vikingcamps.com/locations/lexington"),
    ("vikingcamps.com", "Baseball & Softball Camps", "", "https://vikingcamps.com/locations/lexington"),
    ("vikingcamps.com", "Basketball Camps", "", "https://vikingcamps.com/locations/lexington"),
    ("vikingcamps.com", "Flag Football Camps", "", "https://vikingcamps.com/locations/lexington"),
    ("lexingtonplaycarecenter.org", "Camp LPC", "July - August", "https://lexingtonplaycarecenter.org/summer-camp"),
    ("lexingtonplaycarecenter.org", "Big Kid Camp", "July - August", "https://lexingtonplaycarecenter.org/summer-camp"),
    ("fuseprogram.com", "Seven Week Summer Program", "June 22 - August 6", "https://fuseprogram.com/lexington-vacation-summer-program"),
    ("lexdebateinstitute.com", "The Summer Institute", "", "https://lexdebateinstitute.com/summer"),
    ("goddardschool.com", "Wonder of Learning Summer Program", "", "https://goddardschool.com/schools/ma/lexington/lexington/our-school/special-programs/summer-camp"),
]


# Verified during the Phase-3 eval loop: program-level entries present in the
# live LexRec catalog (category/program pages with their own ProgramIDs) that
# the initial youth-summer selection missed. Same captured-catalog provenance.
MYREC_ADDITIONS = [
    "LexRec Summer Day Camp",
    "Blue Sox Baseball Camp",
    "Minuteman Sports Clinics",
    "USTA Tennis in the Parks Youth Tennis Lessons",
    "Viking Sports Summer Camps",
    "Circuit Lab - Robotics, Coding, & STEAM Summer Clinics",
    "FC Academy - Summer Filmmaking Clinics",
    "Kidcreate - Kpop, Anime, and Gaming",
    "Kids Test Kitchen - Summer",
    "Right Brain - Summer STEM Clinics",
    "Snapology - STEM & Robotics Summer Clinics",
    "SNL Sports Academy Fishing Clinic",
    "Viking Pre-K & Kindergarten Soccer",
]


def myrec_addition_rows() -> list[dict]:
    return [
        {"provider_host": "lexrecma.myrec.com", "program_name": n,
         "session_dates": "", "true_info_url": "https://lexrecma.myrec.com/info/activities/default.aspx?type=camps"}
        for n in MYREC_ADDITIONS
    ]


def munroe_roster_rows() -> list[dict]:
    """Munroe's captured ACTIVE Summer Camp 2026 roster (tests/fixtures/active/
    munroe.json) — youth camp sessions only; the umbrella row is superseded."""
    payload = json.loads((ROOT / "tests/fixtures/active/munroe.json").read_text())
    url = "https://campscui.active.com/orgs/TheMunroeCenterfortheArts?season=3743834"
    rows = []
    for s in payload.get("sessions", []):
        name = (s.get("name") or "").strip()
        if not name:
            continue
        start = s.get("startDate") or {}
        dates = ""
        if isinstance(start, dict) and start.get("month"):
            dates = f"{int(start['month']):02d}/{int(start.get('day', 1)):02d}/{start.get('year', '')}"
        rows.append(
            {"provider_host": "munroecenter.org", "program_name": name,
             "session_dates": dates, "true_info_url": url}
        )
    return rows


def robohub_rows() -> list[dict]:
    return [
        {"provider_host": "therobohub.com", "program_name": name, "session_dates": "",
         "true_info_url": f"https://www.hisawyer.com/the-robo-hub/schedules/activity-set/{aset}"}
        for name, aset in ROBOHUB_PROGRAMS
    ]


def long_tail_rows() -> list[dict]:
    return [
        {"provider_host": h, "program_name": n, "session_dates": d, "true_info_url": u}
        for h, n, d, u in LONG_TAIL
    ]


def main() -> int:
    rows = (
        webtrac_rows()
        + myrec_rows()
        + myrec_addition_rows()
        + lexplorations_rows()
        + munroe_roster_rows()
        + robohub_rows()
        + long_tail_rows()
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f, fieldnames=["provider_host", "program_name", "session_dates", "true_info_url"]
        )
        w.writeheader()
        w.writerows(rows)
    by_host: dict[str, int] = {}
    for r in rows:
        by_host[r["provider_host"]] = by_host.get(r["provider_host"], 0) + 1
    print(f"Wrote {OUT}: {len(rows)} rows")
    for h, c in sorted(by_host.items(), key=lambda kv: -kv[1]):
        print(f"  {h}: {c}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
