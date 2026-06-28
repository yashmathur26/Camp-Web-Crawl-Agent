"""HUB ADAPTER ROADMAP H0.7 — pre-scale gates that must pass before a hub emits.

Safeguards precede scale. Four gates:

  1. register_url verification gate — every emitted parent_ready row's
     register_url must 200 AND contain a registration affordance
     (cart/register/program-detail). Asymmetric: demote only on positive
     evidence of failure (4xx/5xx or no affordance), never on absence of a check.

  2. per-host sanity bounds — but hub hosts are EXEMPT from the single-provider
     explosion ceiling (one hub search legitimately yields 20+ rows). Hubs get a
     separate high ceiling + a zero-floor alarm (a hub returning 0 across all
     towns is a likely template/markup break, not a real empty).

  3. snapshot diffing — persist per-hub result counts; alarm on run-over-run
     deltas beyond +/- threshold so a silent markup change surfaces.

The fetcher used by the register gate is INJECTED, so unit tests run with no
network (fixtures only) — a global forbidden action otherwise.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# Affordance signals in register-page HTML.
_AFFORDANCE_RE = re.compile(
    r"add[\s_-]?to[\s_-]?cart|/cart|class=[\"'][^\"']*cart|register\s*now|"
    r"enroll\s*now|program[\s_-]?detail|iteminfo|program_details|"
    r"begin\s*registration|add\s*to\s*selection|wbwsc|__doPostBack",
    re.I,
)

from shared.data_layout import DATA_ROOT as _DATA_ROOT

# Per-run when FIREFLY_DATA_ROOT is redirected; the unified runner symlinks this
# back to the shared repo dir so snapshot diffing persists across runs.
SNAPSHOT_DIR = _DATA_ROOT / "_snapshots"

# Single-provider explosion ceiling (non-hub). Hubs override this (H0.7.2).
DEFAULT_HOST_CEILING = 60
HUB_HOST_CEILING = 500
DEFAULT_DIFF_THRESHOLD = 0.30  # +/- 30% run-over-run delta -> alarm


def has_registration_affordance(html: str) -> bool:
    """True when register-page HTML carries a registration affordance."""
    if not html:
        return False
    if _AFFORDANCE_RE.search(html):
        return True
    # Reuse the richer signal detector as a backstop.
    try:
        from phase_b.enrollment_signals import verify_registrable

        sig = verify_registrable("", html)
        return bool(sig.has_cart_cta or sig.auto_verdict == "parent_ready")
    except Exception:  # noqa: BLE001
        return False


async def register_url_gate(
    rows: list[dict],
    fetch,
    *,
    only_parent_ready: bool = True,
) -> list[dict]:
    """Verify each row's register_url and demote failures.

    `fetch(url) -> (status:int, html:str)`. status<=0 means the check could not
    run (network down/timeout) — per the asymmetric rule we DO NOT demote on an
    absent check, only on a 4xx/5xx or a 200-without-affordance.

    Demotion = set registrable=False, parent_ready=False, _gate_reason=<why>.
    A passing row gets _gate_reason='200+affordance' and gate_checked=True.
    """
    out: list[dict] = []
    cache: dict[str, tuple[int, str]] = {}
    for row in rows:
        r = dict(row)
        url = r.get("register_url", "")
        is_pr = r.get("parent_ready", True) and r.get("registrable", True)
        if only_parent_ready and not is_pr:
            out.append(r)
            continue
        if not url:
            r["registrable"] = False
            r["parent_ready"] = False
            r["_gate_reason"] = "no register_url"
            out.append(r)
            continue
        if url not in cache:
            try:
                cache[url] = await fetch(url)
            except Exception as exc:  # noqa: BLE001
                logger.warning("register gate fetch error %s: %s", url, exc)
                cache[url] = (0, "")
        status, html = cache[url]
        if status <= 0:
            # Check could not run — leave the row as-is (no positive failure).
            r["gate_checked"] = False
            r["_gate_reason"] = "unchecked (fetch unavailable)"
            out.append(r)
            continue
        if status >= 400:
            r["registrable"] = False
            r["parent_ready"] = False
            r["gate_checked"] = True
            r["_gate_reason"] = f"register_url {status}"
            out.append(r)
            continue
        if not has_registration_affordance(html):
            r["registrable"] = False
            r["parent_ready"] = False
            r["gate_checked"] = True
            r["_gate_reason"] = "no registration affordance"
            out.append(r)
            continue
        r["gate_checked"] = True
        r["_gate_reason"] = "200+affordance"
        out.append(r)
    return out


def apply_host_bounds(
    rows: list[dict],
    *,
    is_hub: bool,
    ceiling: int | None = None,
) -> tuple[list[dict], list[str]]:
    """Cap rows per host. Hubs use the high ceiling and are NOT truncated by the
    single-provider cap. Returns (rows, alarms). Truncation is logged, never silent.
    """
    cap = ceiling if ceiling is not None else (HUB_HOST_CEILING if is_hub else DEFAULT_HOST_CEILING)
    alarms: list[str] = []
    by_host: dict[str, int] = {}
    kept: list[dict] = []
    truncated: dict[str, int] = {}
    for row in rows:
        host = (row.get("platform") or "") + "|" + (row.get("_hub") or row.get("source_url", ""))
        n = by_host.get(host, 0)
        if n >= cap:
            truncated[host] = truncated.get(host, 0) + 1
            continue
        by_host[host] = n + 1
        kept.append(row)
    for host, dropped in truncated.items():
        alarms.append(f"host {host}: truncated {dropped} rows at cap {cap}")
        logger.warning("host bounds: %s truncated %d rows at cap %d", host, dropped, cap)
    return kept, alarms


def zero_floor_alarm(hub: str, total_rows: int) -> str | None:
    """A hub returning 0 rows across ALL towns is a likely markup break."""
    if total_rows == 0:
        msg = f"ZERO-FLOOR ALARM: hub '{hub}' returned 0 rows across all towns (likely template/markup break)"
        logger.error(msg)
        return msg
    return None


def _snapshot_path(hub: str) -> Path:
    return SNAPSHOT_DIR / f"{hub}.json"


def read_snapshot(hub: str) -> dict | None:
    p = _snapshot_path(hub)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            return None
    return None


def write_snapshot(hub: str, counts: dict, *, ts: str = "") -> None:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"hub": hub, "ts": ts, "counts": counts}
    _snapshot_path(hub).write_text(json.dumps(payload, indent=1))


def diff_snapshot(
    hub: str,
    new_counts: dict,
    *,
    threshold: float = DEFAULT_DIFF_THRESHOLD,
) -> list[str]:
    """Compare new per-key counts to the persisted snapshot; alarm on big deltas."""
    prev = read_snapshot(hub)
    if not prev:
        return []
    old = prev.get("counts", {})
    alarms: list[str] = []
    keys = set(old) | set(new_counts)
    for k in sorted(keys):
        a = int(old.get(k, 0))
        b = int(new_counts.get(k, 0))
        if a == 0 and b == 0:
            continue
        base = a or 1
        delta = (b - a) / base
        if abs(delta) > threshold:
            alarms.append(
                f"snapshot delta {hub}/{k}: {a} -> {b} ({delta:+.0%}, > +/-{threshold:.0%})"
            )
    for msg in alarms:
        logger.warning(msg)
    return alarms
