"""roadmap2 Phase 6 — deterministic per-platform verdict policy.

Some platforms can't honestly reach `parent_ready` on the crawl path. MyRec, for
example, renders its add-to-cart/checkout via JavaScript we don't drive, so a
crawl can confirm the catalog but never the cart. Rather than leave that row
`unverified` (looks like a bug) or let a weak signal guess `parent_ready` (a
false positive), we DECIDE it on purpose: ship MyRec as `needs_js` so a later
render/Firecrawl confirm pass can upgrade it.
"""

from __future__ import annotations

from config.settings import SETTINGS


def apply_verdict_policy(session: dict) -> dict:
    """Return the session with its parent_verdict adjusted per platform policy."""
    plat = (session.get("platform") or "").lower()
    verdict = session.get("parent_verdict") or ""
    if "myrec" in plat and verdict != "parent_ready":
        policy = SETTINGS.get("b5_myrec_verdict", "needs_js")
        return {
            **session,
            "parent_verdict": policy,
            "parent_can_register": False,
            "parent_verify_reason": session.get("parent_verify_reason")
            or "myrec cart is JS-rendered; needs a render/Firecrawl confirm pass",
        }
    return session
