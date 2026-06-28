"""Phase 0 safety net — labeled gate-tier fixtures + on-demand eval.

The roadmap moves the keep/drop decision around (Phases 1–5). Before/while doing
that we need one command that says, on a small HAND-LABELED set, whether each
page lands in the tier it should: `confirmed`, `review`, or `gap`. This is the
content-grounded characterization the roadmap's Phase 0 asks for — wired to run
on demand, not only against a full crawl.

Each fixture is a single-session Program fed through the ONE gate (R6); its true
tier is hand-labeled. `report()` runs the gate and scores tier accuracy plus the
two deliverable metrics the roadmap names — precision (of the confirmed tier) and
info_url validity (≥400 chars containing the name) on the labeled pages.

    python -m engine.eval.fixtures        # prints the table

The companion test (tests/test_engine_phase0_fixtures.py) asserts 100% tier
accuracy so a gate change that misroutes one of these classes fails loudly.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from engine.model import Program, Session
from engine.validate.gate import gate_program


def _pad(s: str, n: int = 700) -> str:
    """Repeat to clear the ≥400-char info-page guard while keeping name tokens."""
    out = s
    while len(out) < n:
        out += " " + s
    return out


@dataclass
class Fixture:
    label: str
    expected_tier: str          # confirmed | review | gap
    name: str
    info_url: str
    text: str
    register_url: str = ""
    dates: str = ""
    ages: str = ""
    extractor: str = ""
    camp_scoped: bool = False
    provider_host: str = ""
    provider_name: str = ""
    name_source: str = ""
    note: str = ""


# --- the labeled set ---------------------------------------------------------
# One representative of every class the roadmap calls out for Phase 0/1.
FIXTURES: list[Fixture] = [
    Fixture(
        label="known-platform catalog row",
        expected_tier="confirmed",
        name="Lower Camp",
        info_url="https://majwhaydenweb.myvscloud.com/webtrac/web/iteminfo.html?FMID=1&Module=AR",
        register_url="https://majwhaydenweb.myvscloud.com/webtrac/web/iteminfo.html?FMID=1&Module=AR",
        text=_pad("Lower Camp at Hayden. Youth summer day camp, ages 5-7. "
                  "Add To Cart. $390 per week. June and July sessions. webtrac"),
        dates="07/06/2026 - 07/10/2026", ages="5-7",
        extractor="webtrac", camp_scoped=True,
        provider_host="jwhayden.org", provider_name="J.W. Hayden Center",
        note="vendor catalog must survive every gate change",
    ),
    Fixture(
        label="info-then-register single camp (own domain)",
        expected_tier="confirmed",
        name="Creative Arts Camp",
        info_url="https://runningbrook.org/camps/creative-arts-camp",
        text=_pad("Creative Arts Camp. A youth summer day camp for ages 6-12. "
                  "Campers paint, sculpt and perform. Register online. "
                  "Sessions run July 7 - July 18."),
        dates="July 7 - July 18", ages="6-12",
        extractor="generic",
        provider_host="runningbrook.org", provider_name="Running Brook",
        name_source="title",
    ),
    Fixture(
        label="third-party aggregator/blog (denylist)",
        expected_tier="gap",
        name="10 Best Summer Camps Near Boston",
        info_url="https://www.collegevine.com/blog/best-summer-camps-boston",
        text=_pad("A roundup blog post listing summer camps near Boston for "
                  "high school students applying to college. Ages 14-18."),
        dates="July 2026", ages="14-18",
        extractor="generic",
        provider_host="runningbrook.org", provider_name="Running Brook",
        name_source="title",
        note="off-domain admissions blog — hard deny",
    ),
    Fixture(
        label="out-of-state row",
        expected_tier="gap",
        name="Hoops Camp",
        info_url="https://ussportscamps.com/basketball/new-hampshire/hoops",
        text=_pad("Hoops Camp. Youth basketball summer camp ages 8-14 in New "
                  "Hampshire. Register now. Sessions in July."),
        dates="July 6 - July 10", ages="8-14",
        extractor="generic",
        provider_host="ussportscamps.com", provider_name="US Sports Camps",
    ),
    Fixture(
        label="hub/category landing page",
        expected_tier="review",
        name="Summer Camps",
        info_url="https://runningbrook.org/summer-camps",
        text=_pad("Summer Camps at Running Brook. Browse our day camps, "
                  "specialty camps and leadership programs for ages 5-15. "
                  "Choose a camp below to learn more and register."),
        dates="Summer 2026", ages="5-15",
        extractor="generic",
        provider_host="runningbrook.org", provider_name="Running Brook",
        name_source="title",
        note="section overview the crawler descended FROM, not a camp",
    ),
    Fixture(
        label="chrome-named row",
        expected_tier="review",
        name="Register Now",
        info_url="https://runningbrook.org/camps/adventure",
        text=_pad("Adventure Camp. Youth summer day camp ages 7-12. Hiking, "
                  "kayaking and team challenges. Sessions in July and August."),
        dates="July 14 - July 25", ages="7-12",
        extractor="generic",
        provider_host="runningbrook.org", provider_name="Running Brook",
        name_source="link_text",
    ),
    Fixture(
        label="off-domain generic guess (same-host rule)",
        expected_tier="review",
        name="Camp Wildwood",
        info_url="https://some-aggregator-directory.com/listing/camp-wildwood",
        text=_pad("Camp Wildwood. A traditional youth summer overnight camp for "
                  "ages 8-15 with swimming, archery and arts. July sessions."),
        dates="July 6 - July 31", ages="8-15",
        extractor="generic",
        provider_host="runningbrook.org", provider_name="Running Brook",
        name_source="title",
        note="generic row off the provider's registrable domain",
    ),
    Fixture(
        label="recurring lessons (non-camp)",
        expected_tier="review",
        name="Adaptive Special Needs Swim Lessons",
        info_url="https://swimcenter.org/waltham-swim-lessons",
        text=_pad("Adaptive Special Needs Swim Lessons in Waltham. Private "
                  "instruction for swimmers of all abilities, ages 6-18. "
                  "Year-round weekly lessons."),
        ages="6-18",
        extractor="generic",
        provider_host="swimcenter.org", provider_name="Swim Center",
        name_source="title",
    ),
]


# --- scoring -----------------------------------------------------------------


def gate_tier(fx: Fixture) -> str:
    """Run the ONE gate over a fixture and return its tier."""
    sess = Session(
        name=fx.name, info_url=fx.info_url, register_url=fx.register_url,
        dates=fx.dates, ages=fx.ages, extractor=fx.extractor,
        name_source=fx.name_source,
    )
    prog = Program(name=fx.name, provider_id="prov_fx", info_url=fx.info_url,
                   camp_scoped=fx.camp_scoped)
    prog.sessions = [sess]
    res = gate_program(
        prog, fetched_text={fx.info_url: fx.text},
        provider_name=fx.provider_name, provider_host=fx.provider_host,
    )
    if res.published:
        return "confirmed"
    if res.review:
        return "review"
    return "gap"


@dataclass
class FixtureReport:
    rows: list[tuple[str, str, str, bool]] = field(default_factory=list)  # label, exp, got, ok
    tier_accuracy: float = 0.0
    confirmed_precision: float | None = None
    info_url_validity: float | None = None


def report(fixtures: list[Fixture] | None = None) -> FixtureReport:
    from engine.validate.gate import name_in_text

    fixtures = fixtures if fixtures is not None else FIXTURES
    rows = []
    correct = 0
    pred_confirmed = 0
    pred_confirmed_right = 0
    info_valid = 0
    info_checked = 0
    for fx in fixtures:
        got = gate_tier(fx)
        ok = got == fx.expected_tier
        correct += ok
        rows.append((fx.label, fx.expected_tier, got, ok))
        if got == "confirmed":
            pred_confirmed += 1
            pred_confirmed_right += fx.expected_tier == "confirmed"
            info_checked += 1
            if len(fx.text) >= 400 and name_in_text(fx.name, fx.text):
                info_valid += 1
    rep = FixtureReport(rows=rows, tier_accuracy=correct / len(fixtures) if fixtures else 0.0)
    rep.confirmed_precision = (pred_confirmed_right / pred_confirmed) if pred_confirmed else None
    rep.info_url_validity = (info_valid / info_checked) if info_checked else None
    return rep


def _pct(v) -> str:
    return "n/a" if v is None else f"{v * 100:.1f}%"


def main() -> int:
    rep = report()
    print("== engine gate-tier fixtures ==")
    width = max(len(r[0]) for r in rep.rows)
    for label, exp, got, ok in rep.rows:
        mark = "ok " if ok else "XX "
        print(f"  {mark}{label:<{width}}  expected={exp:<9} got={got}")
    print()
    print(f"  tier accuracy        {_pct(rep.tier_accuracy)}")
    print(f"  confirmed precision  {_pct(rep.confirmed_precision)}")
    print(f"  info_url validity    {_pct(rep.info_url_validity)}")
    return 0 if rep.tier_accuracy == 1.0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
