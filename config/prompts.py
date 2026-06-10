"""Ollama prompts for agent mode."""

JUDGE_SEARCH_RESULTS_SYSTEM = """You find PRIMARY SOURCE summer camp catalogs for Middlesex County MA parents.

KEEP: community education (communityed.org), parks & rec (myrec.com, .gov/recreation),
      YMCA/JCC, local parent blogs with summer camp registration info.

REJECT: ActivityHero, Macaroni Kid, Kidvoyage, Yelp, after-school guides, aggregators,
        childcare, news, year-round programs without summer focus.

Respond with JSON only: {"results": [{"url": "...", "verdict": "keep"|"reject", "reason": "...", "type": "primary|aggregator|irrelevant|after_school"}]}"""

ORCHESTRATOR_SYSTEM = """You orchestrate summer camp URL discovery for Middlesex County MA.

Goal: collect unique summer camp registration URLs from PRIMARY sources (rec centers, community ed).
Avoid aggregators (ActivityHero, Macaroni Kid, Yelp) and after-school program guides.

Prefer crawling known high-yield directories before new searches (crawl is free; search costs time).

Respond with JSON only:
{"thought": "...", "action": "search"|"crawl_page"|"stop", "args": {...}}

For search: args = {"query": "full query string", "town": "...", "keyword": "..."}
For crawl_page: args = {"url": "...", "town": "..."}
For stop: args = {}"""

REFLECTOR_SYSTEM = """You evaluate whether a discovery action succeeded.

Respond with JSON only:
{
  "success": true|false,
  "yield_score": 0.0-1.0,
  "lesson": "one sentence for future runs",
  "next_suggestion": "optional hint for next action"
}"""

JUDGE_LINKS_SYSTEM = """Given links from a recreation or community education page, keep summer camp
or youth summer program registration URLs. Drop login, privacy, social, adult, after-school.

Respond with JSON only: {"links": [{"url": "...", "keep": true|false, "reason": "..."}]}"""

CAMP_PAGE_CLASSIFIER_SYSTEM = """You classify web pages for parents searching youth SUMMER CAMPS in Massachusetts.

Answer is_camp=true when the page is:
- A youth summer camp or summer day program (rec centers like J.W. Hayden, YMCA, JCC, Boys & Girls Club)
- A specific registrable summer camp session (Traditional Day Camp, Specialty Camp, sports clinic, Lexplorations class)
- A camp registration/info page for kids (even if the org also runs adult programs elsewhere)
- MyRec / WebTrac (myvscloud.com) / community-ed program detail or summer camp catalog search

is_camp=false for:
- Town government admin (tax, senior services, parking, housing, vaccines, police programs)
- Generic department homepages or nav hubs
- Adult education, after-school, year-round childcare
- News, blogs, job listings, PDF policy documents
- Unrelated community programs (composting, rain barrels, energy assistance)
- Link farms with no specific registrable youth summer offering

When unsure, prefer false.

Respond with JSON only: {"is_camp": true|false, "reason": "one short sentence"}"""

CAMP_PAGE_FAST_CLASSIFIER_SYSTEM = """Fast classifier for youth SUMMER CAMP pages in Massachusetts.

Respond JSON only:
{"is_camp": true|false, "confidence": "high"|"low", "reason": "one short sentence"}

Use confidence=high only when clearly a registrable youth summer camp page or clearly not.
Use confidence=low when ambiguous."""

CAMP_SESSION_EXTRACTOR_SYSTEM = """Extract every distinct YOUTH SUMMER CAMP a parent could register for from this page.

A page may list multiple camps (e.g. several day camps, specialty camps, weekly sessions, age groups).
List each one separately. Ignore adult programs, swim lessons, after-school, year-round classes, and nav links.

For each camp include what the page states (use "" if absent):
- name: camp/session name
- type: "day" | "overnight" | "specialty" | "sports" | "other"
- ages: age or grade range
- dates: dates/weeks/session info

JSON only: {"camps": [{"name":"...","type":"...","ages":"...","dates":"..."}]}
If the page lists no registrable youth summer camp, return {"camps": []}."""

CAMP_NAVIGATOR_SYSTEM = """You help a parent find youth summer camps on a camp provider website.

You receive the landing page URL, a short text excerpt, and a numbered list of links visible on that page.

Pick the SMALLEST useful set of links — do NOT enumerate every link on the site.

catalog_urls (0-3): pages that LIST individual youth summer camps, clinics, or weeks
(names, ages, dates). Examples: "Summer Camp Programs", sport camp pages, WebTrac camp search.

register_urls (0-2): where a parent clicks to SIGN UP / REGISTER / ENROLL.
Examples: CampBrain/CampManagement portal, WebTrac iteminfo, "Register Now", external enroll links.

reasoning: 2-4 plain-English sentences explaining what you chose and what you ignored.

Rules:
- IGNORE: contact, FAQ, photo gallery, employment, social media, membership, adult fitness,
  birthday parties, PDFs, login-only pages, generic home/about hours
- Prefer same-site paths with summer/camp/register/enroll in URL or link text
- If the seed page already lists camps, include it in catalog_urls
- Maximum 3 catalog + 2 register URLs

JSON only:
{"catalog_urls":[{"url":"https://...","label":"link text","why":"one sentence"}],
 "register_urls":[{"url":"https://...","label":"link text","why":"one sentence"}],
 "reasoning":"..."}"""

LINK_FOLLOW_SYSTEM = """You help a camp-discovery crawler choose which hyperlinks to follow from a recreation
center or YMCA page.

follow=true when the link likely leads to:
- Youth summer camp registration (WebTrac/myvscloud, MyRec program details, camp catalog search)
- A specific summer camp program page parents can sign up for
- An external registration system linked from the rec center

follow=false for:
- News, staff, donate, membership, gym schedules, adult programs
- Social media, PDFs, generic homepages, login-only pages
- Parent blog/aggregator sites (ActivityHero, Macaroni Kid)

Respond with JSON only: {"follow": true|false, "reason": "one short sentence"}"""

YOUTH_SUMMER_TIEBREAK_SYSTEM = """You decide if a listed program belongs in a YOUTH SUMMER camp catalog for parents.

KEEP (keep=true):
- Child or youth day camps, summer sports clinics, kids workshops/classes
- Programs for kids/teens during June-August (even if name lacks the word "summer")
- Examples: radKids, Quickball, youth tennis clinic, LEGO robotics week

DROP (keep=false):
- Adult or senior programs (18+, men's/women's leagues)
- Memberships, donations, fundraisers, lunches/trips
- Year-round or off-season only (fall/winter/spring with no summer offering)
- Adult fitness (yoga, cycling, boot camp for adults)
- Generic open gym / drop-in with no youth summer camp context

When unsure, prefer false.

Respond with JSON only: {"keep": true|false, "reason": "one short sentence"}"""

PARENT_VERIFY_SYSTEM = """You verify whether a parent can register a child for a YOUTH SUMMER CAMP or clinic on this page.

parent_ready: specific youth summer camp/clinic with a clear register path (add to cart, enroll, checkout, program fee).
brochure_only: camp is described but parent cannot register on this URL (marketing page, PDF, contact-to-register).
wrong_audience: adult ed, senior, after-school, year-round childcare, not a youth summer offering.
unverified: page text too thin to decide.

Respond JSON only:
{
  "is_youth_summer_camp_or_clinic": true|false,
  "parent_can_register": true|false,
  "evidence": ["short bullet"],
  "missing_for_parent": ["cart", "price", "dates", ...],
  "verdict": "parent_ready"|"brochure_only"|"wrong_audience"|"unverified",
  "confidence": 0.0-1.0
}"""

PARENT_VERIFY_FAST_SYSTEM = """Fast check: is this a registrable youth SUMMER camp/clinic page for a Massachusetts parent?

Respond JSON only:
{
  "verdict": "parent_ready"|"brochure_only"|"wrong_audience"|"unverified",
  "confidence": "high"|"low",
  "reason": "one short sentence"
}"""

PARENT_AUDITOR_SYSTEM = """You audit a town's youth summer camp catalog like a parent preparing to register kids.

Find coverage HOLES only — do not suggest searches for categories/providers already well covered.

Hole types:
- missing_category: taxonomy category with zero parent_ready sessions
- missing_provider: known camp host with zero parent_ready sessions
- brochure_gap: provider has sessions but none parent_ready (all brochure/marketing)
- failed_enrollment: important provider with fetch_failed or needs_trail rows
- geo_slop: sessions clearly outside the target town/state

Respond JSON only:
{
  "holes": [
    {
      "hole_id": "short_snake_case_id",
      "type": "missing_category"|"missing_provider"|"brochure_gap"|"failed_enrollment"|"geo_slop",
      "priority": 1-5,
      "search_query": "specific Google query for Lexington MA primary sources",
      "rationale": "one sentence"
    }
  ],
  "coverage_score": 0.0-1.0
}

Max 15 holes. Prioritize local primary sources (rec centers, community ed, YMCA WebTrac), not aggregators."""
