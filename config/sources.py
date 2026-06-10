"""Source targeting: primary hosts to prefer, guides to mine, junk to reject."""

# HARD DENY — never useful. Social, jobs, news, reviews, doc/site hosts, and
# national content-mill directories. These are dropped at search ingest AND are
# never accepted as outbound leads from a guide.
AGGREGATOR_DENY_DOMAINS: frozenset[str] = frozenset({
    # National content mills / review / staffing / doc hosts
    "yelp.com",
    "care.com",
    "sittercity.com",
    "summercamps.com",
    "campnavigator.com",
    "mommynearest.com",
    "kidscamps.com",
    "kidvoyage.com",
    "verywellfamily.com",
    "parents.com",
    "activekids.com",
    # Local news / media
    "patch.com",
    "lexobserver.org",
    "lexmedia.org",
    # Social / jobs / event / doc-host / site-builder platforms
    "facebook.com",
    "instagram.com",
    "twitter.com",
    "x.com",
    "linkedin.com",
    "indeed.com",
    "eventbrite.com",
    "issuu.com",
    "weebly.com",
    "ecode360.com",
})

# PARENT GUIDES — curated lists that recommend real local camps. We do NOT keep
# their own pages; instead we mine their OUTBOUND links (the camps they point to).
GUIDE_DOMAINS: frozenset[str] = frozenset({
    "activityhero.com",
    "macaronikid.com",
    "kidsoutandabout.com",
    "communitykangaroo.com",
    "mommypoppins.com",
    "bostoncentral.com",
    "bostonmoms.com",
    "bostonparentspaper.com",
    "bostontechmom.com",
    "metrowestmom.com",
    "masscamps.com",
    "teenlife.com",
    "getfamilyhq.com",
    "jewishboston.com",
    "thebestcamps.com",
    "acanewengland.org",
    "tourlexington.us",
    "walthamplaygroup.org",
})

# Signals that an outbound link is a real registration / program detail page
REGISTRATION_SIGNAL_SUBSTRINGS: tuple[str, ...] = (
    "/register",
    "/registration",
    "/course",
    "/courses",
    "/program",
    "/programs",
    "/activity",
    "/activities",
    "/camp",
    "/camps",
    "/class",
    "/classes",
    "/session",
    "programid=",
    "/enroll",
    "/signup",
    "/sign-up",
)

TITLE_REJECT_PATTERNS: tuple[str, ...] = (
    "after school",
    "after-school",
    "afterschool",
    "childcare",
    "daycare",
    "babysitter",
    "nanny",
    "tutor",
    "jobs",
    "careers",
    "employment",
)

# If title matches reject pattern but also contains these, keep anyway
TITLE_REJECT_OVERRIDES: tuple[str, ...] = (
    "summer camp",
    "summer camps",
    "day camp",
    "sleepaway",
)

URL_REJECT_PATH_PATTERNS: tuple[str, ...] = (
    "/after-school",
    "/afterschool",
    "/childcare",
    "/child-care",
    "/daycare",
)

PREFERRED_HOST_SUBSTRINGS: tuple[str, ...] = (
    "communityed.org",
    "communityed.com",
    "myrec.com",
    "ymca.org",
    "ymca.net",
    "jcc",
    "bgclub",
    "burlingtonrecreation.org",
    "recreation.org",
)

# Canonical municipal rec department seeds — injected into B.5 even when Serper
# only surfaces Facebook/Yelp for "Burlington parks and recreation".
TOWN_REC_SEEDS: dict[str, str] = {
    "Burlington": "https://www.burlingtonrecreation.org/info/activities/activities.aspx",
    "Lexington": "https://lexrecma.myrec.com/info/activities/activities.aspx",
}

# Recreation / camp venues that run their own summer programs (Hayden, YMCA, etc.)
REC_CENTER_HOST_HINTS: tuple[str, ...] = (
    "jwhayden.org",
    "hayden",
    "ymca.org",
    "ymca.net",
    "ymcaboston",
    "myrec.com",
    "communityed.org",
    "communityed.com",
    "jcc",
    "bgclub",
    "boysandgirlsclub",
    "summersedgedaycamp",
    "daycamp",
)

PREFERRED_PATH_SUBSTRINGS: tuple[str, ...] = (
    "/recreation",
    "/summer-camp",
    "/summer-camps",
    "/programs",
)

# Directory crawl seeds to skip (blog indexes, nav hubs — low camp yield).
DIRECTORY_CRAWL_SKIP_PATH_PATTERNS: tuple[str, ...] = (
    "/category/blog",
    "/category/",
    "/tag/",
    "/author/",
    "/wait-listed",
)

# Prefer these path fragments when picking one seed per domain.
DIRECTORY_CRAWL_PREFERRED_PATHS: tuple[str, ...] = (
    "lexplorations",
    "lexploration",
    "childrens-programs",
    "children's-programs",
    "summer-camp",
    "summer-camps",
    "/camps",
    "/camp/",
    "registration",
    "register",
    "/activities",
    "/recreation",
    "/programs",
)
