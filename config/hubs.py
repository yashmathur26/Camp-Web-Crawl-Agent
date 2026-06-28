"""HUB ADAPTER ROADMAP H0.2 — declarative registry of ZIP-seeded national hubs.

A "hub" is a national camp aggregator whose catalog is reached by injecting a
town's ZIP (or city/state) into a templated search URL. Hubs bypass the B.5
recursive navigator entirely — they are *seeds*, not crawl targets.

No logic lives here. Each entry declares only:
  - host:            canonical hostname (for detection / logging)
  - adapter:         the parser module key (phase_d.hubs.<adapter>)
  - render:          how to fetch the search page
                       "raw"        -> plain GET is enough (server-rendered)
                       "rendered"   -> needs JS settle (AJAX result list)
                       "playwright" -> SPA, hash route, wait for grid/XHR
  - radius_miles:    search radius the template encodes (None == city-name search)
  - search_template: a .format(zip=, radius=, city=, state=, page=) URL template

`hub_search_url(hub, ...)` renders a template safely (only the placeholders a
given template actually contains are required).
"""

from __future__ import annotations

import re

HUBS: dict[str, dict] = {
    "camp_invention": {
        "host": "invent.org",
        "adapter": "camp_invention",
        "render": "rendered",  # AJAX result list
        "radius_miles": 25,
        "search_template": (
            "https://www.invent.org/program-search"
            "?field_geolocation_proximity%5Bvalue%5D={radius}"
            "&field_geolocation_proximity%5Bsource_configuration%5D%5Borigin_address%5D={zip}"
            "&field_program_status_value_1%5B%5D=pre-registration"
            "&field_program_status_value_1%5B%5D=registration"
            "&sort_by=field_geolocation_proximity&sort_order=ASC"
        ),
    },
    "skyhawks": {
        "host": "register.skyhawks.com",
        "adapter": "configio",
        "render": "raw",  # server-rendered HTML, no JS wait
        "radius_miles": 10,
        "search_template": "https://register.skyhawks.com/search?zip={zip}&zipdis={radius}",
    },
    "idtech": {
        "host": "idtech.com",
        "adapter": "idtech",
        "render": "playwright",  # SPA, hash route, must wait for grid/XHR
        "radius_miles": None,  # city-name search, not radius
        "search_template": "https://www.idtech.com/location-search?s={city},+{state},+USA&p={page}",
    },
}

_PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")


def hub(name: str) -> dict:
    """Return one hub entry; raises KeyError on an unknown hub name."""
    return HUBS[name]


def template_fields(template: str) -> set[str]:
    """The set of {placeholder} names a template actually uses."""
    return set(_PLACEHOLDER_RE.findall(template))


def hub_search_url(
    name: str,
    *,
    zip: str = "",  # noqa: A002 — mirrors the template placeholder name
    radius: int | str | None = None,
    city: str = "",
    state: str = "",
    page: int | str = 1,
) -> str:
    """Render a hub's search URL for one town seed.

    Only the placeholders the chosen template contains are required; supplying a
    value for a placeholder the template doesn't use is harmless. A missing
    required value raises ValueError (a silent empty would corrupt the search).
    """
    entry = HUBS[name]
    template = entry["search_template"]
    needed = template_fields(template)
    values = {
        "zip": str(zip or ""),
        "radius": "" if radius is None else str(radius),
        "city": str(city or ""),
        "state": str(state or ""),
        "page": str(page),
    }
    missing = [f for f in needed if not values.get(f, "")]
    if missing:
        raise ValueError(f"hub {name}: missing template value(s) {missing}")
    return template.format(**values)
