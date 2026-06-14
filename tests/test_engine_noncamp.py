"""Waltham W3W feedback round: non-camp rejection, age/adult sanitation,
register-link selection, locale-mirror skip, and provider name prefixing.

Each case is a real false-positive (or wrong field) from the Waltham camp list.
The rules are domain-agnostic — these assert the *category* is handled, not a URL.
"""

from __future__ import annotations

from engine.extract.generic import score_follow_links
from engine.model import Program, Session
from engine.validate.gate import gate_program
from engine.validate.noncamp import (
    adult_min_age,
    is_generic_name,
    noncamp_reason,
    prefixed_name,
    sanitize_age,
)


# --- noncamp_reason categories ----------------------------------------------

def test_recruitment_posting_rejected():
    assert noncamp_reason(
        "Day Camp Counselors",
        info_url="https://runningbrook.org/who-we-are/join-our-team/day-camp-counselors",
    )
    # but a Counselor-in-Training CAMP program is fine
    assert noncamp_reason("Counselor-in-Training Program", info_url="https://y.org/cit") is None


def test_lessons_and_open_play_rejected():
    assert noncamp_reason("Open Play Hours", info_url="https://j.org/program/basketball")
    assert noncamp_reason("Pre-Swim Club", info_url="https://j.org/")
    assert noncamp_reason("Adaptive Special Needs Swim Lessons in Waltham", info_url="https://s.com/x")
    assert noncamp_reason("Masters Swim", info_url="https://j.org/")
    # a real swim CAMP must survive
    assert noncamp_reason("Junior Swim Camp", info_url="https://x.org/swim-camp") is None


def test_resource_page_rejected_by_section_not_hardcoded_words():
    # Caught by the generalizable /camp-resources/ path — NOT by page-specific
    # words. Every jewishcamp row shares this resource-hub URL, incl. ones whose
    # name contains "Camp".
    res_url = "https://jewishcamp.org/camp-resources/making-mensches"
    assert noncamp_reason("URJ Camp Harlam's Middah Zoo Program", info_url=res_url)
    assert noncamp_reason("What's Your Mussar?", info_url=res_url)
    # generalizes to any site's resource hub / document naming
    assert noncamp_reason("Activity Sheet", info_url="https://anycamp.org/resources/printables")
    assert noncamp_reason("Summer Reading PDF", info_url="https://anycamp.org/page")
    # a real camp under a normal path is untouched
    assert noncamp_reason("Nature Camp", info_url="https://anycamp.org/programs/nature") is None


def test_school_district_service_rejected():
    assert noncamp_reason("English as a Supplemental Language Program",
                          info_url="https://watertown.k12.ma.us/72101_3")
    assert noncamp_reason("Watertown Farm to School Program", info_url="https://w.k12.ma.us/y")
    assert noncamp_reason("Transition & STRIVE Services", info_url="https://bps.org/z")
    assert noncamp_reason(
        "Community Academy of Health & Science",
        info_url="https://bostonpublicschools.org/enrollment/welcome-services/change-of-address",
    )


def test_year_round_childcare_rejected_only_when_not_summer():
    elc = ("Early Learning Center. Nurturing children ages 6 weeks to 5 years. "
           "Open year-round, Monday to Friday. " * 4)
    assert noncamp_reason("Summer Camp", text=elc, dates="", is_summer=False)
    # a genuine summer session on the same operator is kept
    assert noncamp_reason("Summer Day Camp", text=elc, dates="July 7-11", is_summer=True) is None


# --- age + adult sanitation --------------------------------------------------

def test_sanitize_age_drops_artifacts():
    assert sanitize_age("age 02") == ""
    assert sanitize_age("ages 1") == ""
    assert sanitize_age("ages 6-12") == "ages 6-12"
    assert sanitize_age("18 months") == "18 months"


def test_adult_min_age_handles_bare_plus():
    assert adult_min_age("19+") is True
    assert adult_min_age("ages 18-99") is True
    assert adult_min_age("18 months") is False
    assert adult_min_age("6-12") is False


# --- name accuracy -----------------------------------------------------------

def test_generic_names_get_provider_prefix():
    assert is_generic_name("Older Boys Unit")
    assert is_generic_name("Summer Camp")
    assert not is_generic_name("WorldBuilder: Minecraft Game Design")
    assert prefixed_name("Younger Kids Unit", "West Suburban YMCA") == \
        "West Suburban YMCA — Younger Kids Unit"
    # specific names untouched; provider already-present untouched
    assert prefixed_name("Astrophysics", "Boston Leadership Institute") == "Astrophysics"
    assert prefixed_name("YMCA Summer Camp", "West Suburban YMCA") == "YMCA Summer Camp"


# --- locale mirror skip ------------------------------------------------------

def test_locale_mirror_not_followed():
    links = [
        {"url": "https://ymcaboston.org/youth-and-family/camps/waltham-camp-guide", "text": "Camp Guide"},
        {"url": "https://ymcaboston.org/es/youth-and-family/camps/waltham-camp-guide", "text": "Guía"},
    ]
    follows = score_follow_links("https://ymcaboston.org/", links)
    assert any("/youth-and-family" in u and "/es/" not in u for u in follows)
    assert not any("/es/" in u for u in follows)


# --- end-to-end through the gate --------------------------------------------

def _gate_one(name, text, *, dates="", ages="", info="https://x.org/p", provider_name=""):
    sess = Session(name=name, info_url=info, dates=dates, ages=ages)
    prog = Program(name=name, provider_id="p", info_url=info)
    prog.sessions = [sess]
    return gate_program(prog, fetched_text={info: text}, provider_name=provider_name)


def test_gate_drops_counselor_job_even_with_summer_date():
    text = "Day Camp Counselors. Join our team this June! Grades 4-5. " * 10
    res = _gate_one("Day Camp Counselors", text, dates="June 22", ages="grades 4-5",
                    info="https://r.org/join-our-team/day-camp-counselors")
    assert not res.published


def test_gate_drops_swim_lessons_with_youth_age():
    text = "Adaptive Special Needs Swim Lessons in Waltham. Private instruction. " * 10
    res = _gate_one("Adaptive Special Needs Swim Lessons in Waltham", text, ages="6-18",
                    info="https://s.com/waltham-swim-lessons")
    assert not res.published


def test_gate_drops_resource_page_despite_fake_june_date():
    # the generic extractor scraped "June 20" off a resource page -> fake summer.
    text = "Making Mensches: a periodic table of character strengths. " * 20
    res = _gate_one("What's Your Mussar?", text, dates="June 20", ages="",
                    info="https://jewishcamp.org/camp-resources/making-mensches")
    assert not res.published


def test_gate_drops_masters_swim_bare_19_plus():
    text = "Masters Swim. Lap swimming for experienced swimmers. " * 12
    res = _gate_one("Masters Swim", text, dates="June 29 - August 21", ages="19+",
                    info="https://j.org/masters")
    assert not res.published


def test_gate_prefixes_generic_name_and_keeps_real_camp():
    text = ("Younger Kids Unit at our summer day camp. Campers entering grades 3-5 "
            "enjoy swimming, sports and arts. " * 8)
    res = _gate_one("Younger Kids Unit", text, dates="June 29 - July 2", ages="8-10",
                    info="https://wsymca.org/camp-chickami", provider_name="West Suburban YMCA")
    assert res.published
    assert res.published[0].name == "West Suburban YMCA — Younger Kids Unit"


def test_higher_ed_adult_dropped_but_youth_precollege_kept():
    # adult college "Summer Session" with a summer date -> dropped
    adult = ("Harvard Summer School. Undergraduate and graduate courses for "
             "college credit. Admissions, financial aid, and study abroad. " * 6)
    res = _gate_one("Summer Session", adult, dates="June 22 - August 1", ages="",
                    info="https://harvard.edu/summer")
    assert not res.published
    # pre-college youth program on the SAME kind of site -> kept
    youth = ("Bentley Summer Business Program: a pre-college summer program for "
             "high school students entering grades 10-12. Rising juniors. " * 6)
    res2 = _gate_one("Bentley Summer Business Program", youth, dates="July 6-17",
                     ages="grades 10-12", info="https://bentley.edu/pre-college",
                     provider_name="Bentley University")
    assert res2.published


def test_school_summer_camp_passes_service_filter():
    # a real school camp must NOT be caught by the school-district service rule
    txt = ("Waltham High School Summer Theater Camp for students entering grades "
           "6-9, ages 11-14. Two-week program. " * 6)
    res = _gate_one("Waltham High School Summer Theater Camp", txt, dates="July 7-18",
                    ages="11-14", info="https://walthampublicschools.org/o/whs/summer-theater")
    assert res.published


def test_gate_keeps_legit_camp_unaffected():
    text = ("Astrophysics three-week program at Gann/Bentley in Waltham for high "
            "school students. Hands-on research. " * 8)
    res = _gate_one("Astrophysics", text, dates="June 29 - July 17", ages="grades 9-12",
                    info="https://bli.com/three-week-programs", provider_name="Boston Leadership Institute")
    assert res.published
    assert res.published[0].name == "Astrophysics"  # specific name untouched
