"""US Sports Camps (ussportscamps.com) source configuration.

The site renders its results client-side from a public Algolia index, so we
query that index directly instead of scraping the Cloudflare-protected,
JS-rendered results page. The App ID and *search-only* API key below ship in
the site's own browser JS (themes/v2/dist/js/index.js) and are safe to embed.

If the site ever rotates the key, re-grab it in one line:

    curl -s https://www.ussportscamps.com/themes/v2/dist/js/index.js \
      | grep -oE 'algoliaAppId:"[^"]*"|algoliaSearchKey:"[^"]*"|algoliaIndex:"[^"]*"'
"""

from __future__ import annotations

ALGOLIA_APP_ID = "HW2V8G4F6H"
ALGOLIA_SEARCH_KEY = "539ec63f78b5ab04c8177bdd0247ef21"
ALGOLIA_INDEX = "algolia-camps"

# Full deep-link prefix. Each camp record carries a `url` path like
# /basketball/nike/<slug>; the canonical camp page is BASE_URL + url.
# (This is the permalink that does NOT bounce back to the homepage.)
BASE_URL = "https://www.ussportscamps.com"

# Camps returned per (town, sport). Filled by distance from the town center,
# so the list reaches this count even when fewer than this many are local.
CAMPS_PER_SPORT = 10

# Politeness delay (seconds) between Algolia queries.
REQUEST_DELAY_S = 0.15

# Fallback sport slugs (the 27 facets observed on 2026-06-14). At runtime we
# fetch the live `sportSlug` facet and fall back to this list if that fails,
# so the set stays current without a hardcoded-only dependency.
SPORT_SLUGS_FALLBACK: list[str] = [
    "baseball", "basketball", "cross-country", "dance",
    "elite-hoops-basketball", "fieldhockey", "flag-football", "football",
    "golf", "gymnastics", "lacrosse", "mile-post-35", "multisport", "nike",
    "pickleball", "rowing", "rugby", "skiing", "soccer", "softball",
    "sport-performance", "swim", "tennis", "track-field", "volleyball",
    "waterpolo", "wrestling",
]
