"""Single source of truth for registration-platform signatures.

Consumed by:
  - src/platforms.py        detect_platform() host/link/HTML detection
  - src/registration.py     is_registration_platform_url()
  - scripts/fingerprint_all_candidates.py   per-host fingerprint report

Tiers:
  structured  clean URL patterns -> exact per-session links
  portal      JS/queue registration; we surface entry points + visible links
  builder     marketing-site builders; trail first, LLM last
"""

from __future__ import annotations

# platform id -> signature spec
PLATFORM_SIGNATURES: dict[str, dict] = {
    "webtrac": {
        "label": "WebTrac / myvscloud (Vermont Systems)",
        "tier": "structured",
        "host_substrings": ("myvscloud.com", "webtrac", "wbwsc"),
        "html_patterns": (r"myvscloud\.com", r"webtrac", r"wbwsc"),
    },
    "myrec": {
        "label": "MyRec.com",
        "tier": "structured",
        "host_substrings": ("myrec.com",),
        "html_patterns": (r"myrec\.com", r"program_details\.aspx"),
    },
    "community_ed": {
        "label": "Community Ed WooCommerce (communityed.org/com)",
        "tier": "structured",
        # matched by host SUFFIX, not substring — see config/community_ed.py
        "host_suffixes": ("communityed.org", "communityed.com"),
        "host_substrings": (),
        "html_patterns": (r"lexplorations", r"find-a-class"),
    },
    "woocommerce": {
        "label": "WooCommerce (WordPress store)",
        "tier": "structured",
        "host_substrings": (),
        "html_patterns": (
            r"woocommerce",
            r"wp-content/plugins/woocommerce",
            r"add-to-cart=",
        ),
    },
    "sawyer": {
        "label": "Sawyer (hisawyer)",
        "tier": "structured",
        "host_substrings": ("hisawyer.com",),
        "html_patterns": (r"hisawyer\.com",),
    },
    "campbrain": {
        "label": "CampBrain",
        "tier": "portal",
        "host_substrings": ("campbrainregistration.com", "campbrain.com"),
        "html_patterns": (r"campbrain",),
    },
    "arbitersports": {
        "label": "ArbiterSports / ArbiterRegistration",
        "tier": "portal",
        "host_substrings": ("arbitersports.com",),
        "html_patterns": (r"arbitersports\.com",),
    },
    "active": {
        "label": "ACTIVE Network / ActiveCommunities",
        "tier": "portal",
        "host_substrings": ("activecommunities.com", "active.com", "apm.activecommunities"),
        "html_patterns": (r"activecommunities\.com", r"activenetwork", r"apm\.activecommunities"),
    },
    "communitypass": {
        "label": "CommunityPass",
        "tier": "portal",
        "host_substrings": ("communitypass.net",),
        "html_patterns": (r"register\.communitypass\.net", r"communitypass"),
    },
    "veracross": {
        "label": "Veracross Program Registration",
        "tier": "structured",
        "host_substrings": ("veracross.com", "programregistration.veracross"),
        "html_patterns": (r"veracross\.com", r"programregistration\.veracross"),
    },
    "daxko": {
        "label": "Daxko (YMCA/club ops)",
        "tier": "portal",
        "host_substrings": ("daxko.com", "operations.daxko"),
        "html_patterns": (r"daxko", r"operations\.daxko"),
    },
    "ultracamp": {
        "label": "Ultracamp",
        "tier": "portal",
        "host_substrings": ("ultracamp.com",),
        "html_patterns": (r"ultracamp\.com",),
    },
    "recdesk": {
        "label": "RecDesk",
        "tier": "portal",
        "host_substrings": ("recdesk.com",),
        "html_patterns": (r"recdesk\.com",),
    },
    "civicrec": {
        "label": "CivicRec / CivicPlus",
        "tier": "portal",
        "host_substrings": ("civicrec", "civicplus"),
        "html_patterns": (r"civicrec", r"civicplus", r"\.civicengage"),
    },
    "perfectmind": {
        "label": "PerfectMind",
        "tier": "portal",
        "host_substrings": ("perfectmind",),
        "html_patterns": (r"perfectmind",),
    },
    "jackrabbit": {
        "label": "Jackrabbit",
        "tier": "portal",
        "host_substrings": ("jackrabbitclass.com",),
        "html_patterns": (r"jackrabbitclass\.com", r"jackrabbittech"),
    },
    "campdoc": {
        "label": "CampDoc",
        "tier": "portal",
        "host_substrings": ("campdoc.com",),
        "html_patterns": (r"campdoc\.com",),
    },
    "campminder": {
        "label": "CampMinder",
        "tier": "portal",
        "host_substrings": ("campminder.com",),
        "html_patterns": (r"campminder",),
    },
    "configio": {
        "label": "Configio (Skyhawks register.skyhawks.com & *.configio.com)",
        "tier": "structured",
        # The Configio engine backs register.skyhawks.com and many *.configio.com
        # storefronts; the parser is reusable beyond Skyhawks (HUB_ADAPTER H0.3).
        "host_substrings": ("register.skyhawks.com", "configio.com"),
        "html_patterns": (r"register\.skyhawks\.com", r"configio\.com", r"/pd/\d+"),
    },
    "squarespace": {
        "label": "Squarespace",
        "tier": "builder",
        "host_substrings": ("squarespace.com", "static1.squarespace"),
        "html_patterns": (r"squarespace\.com", r"static1\.squarespace"),
    },
    "wix": {
        "label": "Wix",
        "tier": "builder",
        "host_substrings": ("wixstatic.com", "wix.com"),
        "html_patterns": (r"wix\.com", r"wixstatic"),
    },
    "weebly": {
        "label": "Weebly",
        "tier": "builder",
        "host_substrings": ("editmysite.com", "weebly.com"),
        "html_patterns": (r"editmysite\.com", r"weebly\.com"),
    },
    "wordpress": {
        "label": "WordPress (generic)",
        "tier": "builder",
        "host_substrings": (),
        "html_patterns": (r"wp-content", r"wp-json"),
    },
}

# External registration platforms detectable from a link's host alone, in
# detection priority order (structured first, then portals).
EXTERNAL_PLATFORM_ORDER: tuple[str, ...] = (
    "webtrac",
    "myrec",
    "veracross",
    "sawyer",
    "campbrain",
    "arbitersports",
    "active",
    "communitypass",
    "daxko",
    "ultracamp",
    "recdesk",
    "civicrec",
    "perfectmind",
    "jackrabbit",
    "campdoc",
    "campminder",
    "configio",
)

BUILDER_PLATFORM_ORDER: tuple[str, ...] = ("squarespace", "wix", "weebly")


def host_signatures() -> list[tuple[str, tuple[str, ...]]]:
    """[(platform, host_substrings)] for external registration platforms."""
    return [
        (pid, PLATFORM_SIGNATURES[pid]["host_substrings"])
        for pid in EXTERNAL_PLATFORM_ORDER
        if PLATFORM_SIGNATURES[pid]["host_substrings"]
    ]


def builder_host_signatures() -> list[tuple[str, tuple[str, ...]]]:
    return [
        (pid, PLATFORM_SIGNATURES[pid]["host_substrings"])
        for pid in BUILDER_PLATFORM_ORDER
    ]


def registration_host_substrings() -> tuple[str, ...]:
    """Flat host-substring list for is_registration_platform_url()."""
    subs: list[str] = []
    for pid in EXTERNAL_PLATFORM_ORDER:
        subs.extend(PLATFORM_SIGNATURES[pid]["host_substrings"])
    return tuple(dict.fromkeys(subs))
