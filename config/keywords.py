# Phase A: summer camp directory discovery — primary sources (rec, community ed, local)
PHASE_A_KEYWORDS: list[str] = [
    # Community education & schools
    "community education summer programs",
    "community education summer camp",
    "community ed summer programs",
    "public schools summer camp program",
    "school department summer camps",
    "school district summer programs",
    "summer enrichment programs registration",
    "summer program catalog community education",
    "2026 community education summer",
    "community education youth summer programs",
    # Parks & recreation / municipal
    "parks and recreation summer camps",
    "parks and rec summer camp registration",
    "recreation department summer camps",
    "town recreation summer camps",
    "municipal summer camp registration",
    "community recreation summer programs",
    "public recreation summer camps",
    "town summer camp programs",
    "city recreation summer camps",
    "summer camp registration recreation department",
    "youth recreation summer programs",
    "summer camp sign up recreation",
    "2026 recreation department summer camps",
    "recreation summer camp catalog",
    # YMCAs, JCCs, community orgs
    "YMCA summer camp",
    "YWCA summer camp",
    "JCC summer camp",
    "boys and girls club summer camp",
    "community center summer camp",
    "nonprofit summer camp program",
    "local summer camp program registration",
    "summer day camp community center",
    # Local blogs & parent guides
    "local summer camp guide blog",
    "parent guide summer camps blog",
    "summer camp guide for parents",
    "town summer camp blog",
    "neighborhood summer camp guide",
    "2026 summer camp guide parents",
    "where to register summer camps locally",
    "summer camp roundup local",
    # Direct catalog / registration phrasing
    "summer camp catalog",
    "summer camp class catalog",
    "summer camp program listing",
    "summer camp schedule registration",
    "summer camp enrollment",
    "2026 summer camp catalog",
    "summer day camp registration",
    "summer camp weekly sessions",
    # Regional MA
    "Massachusetts community education summer",
    "MA parks and recreation summer camps",
    "MetroWest summer camp registration",
    "Boston area recreation summer camps",
    "Middlesex county summer camp programs",
]

# --------------------------------------------------------------------------- #
# Phase C: activity-specific discovery — niche camps, clinics & workshops.
#
# Phase A finds the big primary-source catalogs (rec departments, community ed,
# YMCA/JCC). Phase C goes after the LONG TAIL: single-sport clinics, art studios,
# STEM/robotics workshops, nature/adventure programs, etc. — the niche providers
# that never show up under generic "summer camp" searches.
#
# Each activity term is composed with a small set of camp/clinic/workshop
# templates and anchored locally by run.py as "<keyword> <Town>, <STATE>". Every
# term keeps an explicit summer + kids/camp signal so the youth-summer focus
# filter (Phase B.5) and search validation stay clean (no adult leagues, no
# year-round childcare).
# --------------------------------------------------------------------------- #

# Mainstream + niche sports. The user wants EVERY sport, including the niche
# ones — these get both a "camp" and a "clinic" template (sports run clinics).
_SPORTS_ACTIVITIES: list[str] = [
    # mainstream
    "basketball",
    "soccer",
    "baseball",
    "softball",
    "tennis",
    "golf",
    "swim",
    "volleyball",
    "lacrosse",
    "field hockey",
    "ice hockey",
    "flag football",
    "football",
    "track and field",
    "cross country",
    "gymnastics",
    "cheerleading",
    "wrestling",
    "ultimate frisbee",
    "running",
    # racquet / paddle
    "squash",
    "badminton",
    "table tennis",
    "pickleball",
    # combat / martial arts
    "martial arts",
    "karate",
    "taekwondo",
    "judo",
    "jiu jitsu",
    "boxing",
    "fencing",
    # water
    "sailing",
    "rowing",
    "crew",
    "water polo",
    "diving",
    "kayaking",
    "stand up paddleboard",
    "surfing",
    # target / precision
    "archery",
    "golf clinic",
    "disc golf",
    # wheels / board / air
    "skateboarding",
    "bmx",
    "mountain biking",
    "rock climbing",
    "parkour",
    "ninja warrior",
    # equestrian / outdoor
    "horseback riding",
    "equestrian",
    # other niche
    "rugby",
    "cricket",
    "figure skating",
    "speed skating",
    "curling",
    "handball",
    "quidditch",
    "frisbee",
]

# Arts & performing arts.
_ARTS_ACTIVITIES: list[str] = [
    "art",
    "fine arts",
    "painting",
    "drawing",
    "pottery",
    "ceramics",
    "sculpture",
    "printmaking",
    "photography",
    "filmmaking",
    "film and video",
    "animation",
    "stop motion animation",
    "theater",
    "drama",
    "musical theater",
    "improv comedy",
    "circus arts",
    "dance",
    "ballet",
    "hip hop dance",
    "music",
    "rock band",
    "guitar",
    "piano",
    "drumming",
    "songwriting",
    "voice and singing",
    "creative writing",
    "comic and manga",
    "fashion design",
    "sewing",
    "jewelry making",
    "woodworking",
    "graphic design",
]

# STEM / education / academic enrichment.
_STEM_ACTIVITIES: list[str] = [
    "STEM",
    "science",
    "robotics",
    "lego robotics",
    "coding",
    "programming",
    "python coding",
    "scratch coding",
    "web design",
    "app development",
    "video game design",
    "game design",
    "minecraft",
    "roblox",
    "engineering",
    "electronics",
    "3d printing",
    "math",
    "chemistry",
    "biology",
    "astronomy and space",
    "marine biology",
    "artificial intelligence",
    "data science",
    "chess",
    "debate",
    "public speaking",
    "model un",
    "entrepreneurship",
    "financial literacy",
    "spanish language",
    "french language",
    "mandarin language",
    "reading and writing",
    "medicine and health",
    "veterinary",
    "architecture",
]

# Nature, adventure & general "fun" enrichment.
_FUN_ACTIVITIES: list[str] = [
    "nature",
    "outdoor adventure",
    "wilderness survival",
    "forest school",
    "farm",
    "gardening",
    "environmental",
    "zoo and animal",
    "cooking",
    "baking",
    "culinary",
    "magic",
    "escape room",
    "dungeons and dragons",
    "board game",
    "scavenger hunt",
    "leadership",
    "counselor in training",
    "STEAM",
    "maker",
    "inventor",
]


def _compose(activities: list[str], templates: list[str]) -> list[str]:
    """Cross activities with camp/clinic/workshop templates → search keywords."""
    out: list[str] = []
    for activity in activities:
        for template in templates:
            out.append(template.format(activity))
    return out


# Sports emphasize "camp" + "clinic"; arts/STEM add "workshop"; fun stays "camp".
PHASE_C_KEYWORDS: list[str] = list(
    dict.fromkeys(  # dedupe while preserving order
        _compose(_SPORTS_ACTIVITIES, ["youth {} summer camp", "kids {} summer clinic"])
        + _compose(_ARTS_ACTIVITIES, ["kids {} summer camp", "{} summer workshop for kids"])
        + _compose(_STEM_ACTIVITIES, ["kids {} summer camp", "{} summer workshop for kids"])
        + _compose(_FUN_ACTIVITIES, ["kids {} summer camp"])
    )
)


# --------------------------------------------------------------------------- #
# Phase A query POOL (discovery-expansion roadmap, Thread 1).
#
# Phase A used to run a flat 53 keywords for every town. To let big towns search
# MORE (population-scaled budget), src/search_budget.py assembles a prioritized
# pool per town, drawn in this order:
#   1. curated institution queries (colleges + schools from the registries)
#   2. PHASE_A_KEYWORDS (the proven 53 primary-source terms)
#   3. TOWN_INSTITUTION_TEMPLATES (generic college/school discovery, any town)
#   4. PHASE_A_ACTIVITY_TERMS composed with a camp template (long-tail breadth)
# A small town uses the top slice; a big town spends down its larger budget.
# --------------------------------------------------------------------------- #

# High-yield, common activity subset for Phase A breadth (the full per-activity
# long tail stays in Phase C). Ordered by rough demand.
PHASE_A_ACTIVITY_TERMS: list[str] = [
    "sports", "soccer", "basketball", "swim", "tennis", "baseball", "martial arts",
    "gymnastics", "dance", "art", "theater", "music", "STEM", "science", "robotics",
    "coding", "lego", "chess", "cooking", "nature", "outdoor adventure",
    "engineering", "writing", "film", "video game design", "math",
]

# Per-institution templates (formatted with the institution name). High priority:
# these are exactly the college/school camps the operator asked to surface.
INSTITUTION_QUERY_TEMPLATES: dict[str, list[str]] = {
    "college": [
        "{name} summer youth camp",
        "{name} pre-college summer program high school",
        "{name} summer youth program kids",
        "{name} summer sports camp",
    ],
    "private": [
        "{name} summer camp",
        "{name} summer program for kids",
    ],
    "public_high": [
        "{name} summer camp",
        "{name} summer sports camp",
    ],
    "public_district": [
        "{name} summer programs",
        "{name} summer camp registration",
    ],
    "trade": [
        "{name} summer youth exploratory program",
        "{name} summer program for high school students",
    ],
}

# Generic institution-discovery queries (anchored by town/state). These catch
# institutions NOT in the curated registries — the dynamic half of the hybrid.
TOWN_INSTITUTION_TEMPLATES: list[str] = [
    "colleges and universities summer camps {town}, {state}",
    "university pre-college summer program {town} {state}",
    "college youth sports camp {town} {state}",
    "{town} {state} private school summer camp",
    "{town} {state} high school summer camp",
    "{town} {state} public schools summer programs",
    "{town} {state} vocational technical high school summer program",
]
