"""Engine v3 eval (plan §11) — the definition of done for every phase (R1).

Scores a published output (engine sessions.csv, or the old pipeline's
camp_sessions.csv via --input) against hand-curated ground truth:

  program recall      matched GT programs / GT programs
  session recall      matched GT sessions / GT sessions-with-dates
  precision           published rows matching GT / published rows
  info_url validity   live fetch: >=400 chars containing the program name

Ground truth CSV: provider_host, program_name, session_dates, true_info_url.
Writes engine/eval/history/<timestamp>.json; --compare diffs two entries.
"""

from __future__ import annotations

import csv
import json
import re
import time
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import urlparse

EVAL_DIR = Path(__file__).resolve().parent
GROUND_TRUTH_DIR = EVAL_DIR / "ground_truth"
HISTORY_DIR = EVAL_DIR / "history"

# --------------------------------------------------------------------------- #
# Name normalization + fuzzy matching (plan §2 grouping + §11 matching)
# --------------------------------------------------------------------------- #

_WEEK_LABEL_RE = re.compile(
    r"\b(?:week|session|wk|sess)\s*(?:[#:]?\s*)?(?:\d+|one|two|three|four|five|six|"
    r"seven|eight|nine|ten)\b",
    re.I,
)
_DATE_FRAG_RE = re.compile(
    r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s*\d{1,2}"
    r"(?:\s*[-–—]\s*(?:[a-z]+\.?\s*)?\d{1,2})?\b"
    r"|\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b"
    r"|\b20\d{2}\b",
    re.I,
)
_PUNCT_RE = re.compile(r"[^a-z0-9\s]")
_WS_RE = re.compile(r"\s+")

_STOP_TOKENS = {"the", "a", "an", "of", "and", "for", "at", "in", "to", "with"}


def normalize_name(name: str) -> str:
    """Strip dates, week/session labels, punctuation; lowercase; collapse ws."""
    s = (name or "").lower()
    s = _DATE_FRAG_RE.sub(" ", s)
    s = _WEEK_LABEL_RE.sub(" ", s)
    s = _PUNCT_RE.sub(" ", s)
    return _WS_RE.sub(" ", s).strip()


def _tokens(name: str) -> set[str]:
    return {t for t in normalize_name(name).split() if t and t not in _STOP_TOKENS}


def token_set_ratio(a: str, b: str) -> float:
    """fuzzywuzzy-style token_set_ratio in [0,1]: order-free, subset-tolerant."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 1.0 if normalize_name(a) == normalize_name(b) and normalize_name(a) else 0.0
    inter = " ".join(sorted(ta & tb))
    sa = (inter + " " + " ".join(sorted(ta - tb))).strip()
    sb = (inter + " " + " ".join(sorted(tb - ta))).strip()
    ratios = [
        SequenceMatcher(None, inter, sa).ratio() if inter else 0.0,
        SequenceMatcher(None, inter, sb).ratio() if inter else 0.0,
        SequenceMatcher(None, sa, sb).ratio(),
    ]
    return max(ratios)


MATCH_THRESHOLD = 0.85


def names_match(a: str, b: str, threshold: float = MATCH_THRESHOLD) -> bool:
    return token_set_ratio(a, b) >= threshold


# --------------------------------------------------------------------------- #
# Date-window overlap (session matching)
# --------------------------------------------------------------------------- #

_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
)}
_MD_RE = re.compile(r"\b([a-z]{3,9})\.?\s*(\d{1,2})\b", re.I)
_NUM_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})(?:/\d{2,4})?\b")
_ISO_RE = re.compile(r"\b\d{4}-(\d{2})-(\d{2})\b")


def parse_date_window(text: str) -> tuple[int, int] | None:
    """Parse a dates string to an (ordinal, ordinal) day-of-year window.

    Tolerant of "June 29 – July 2", "6/29-7/2", "2026-07-06 – 2026-07-10",
    "Week of July 7". Year is ignored (camps are seasonal)."""
    if not text:
        return None
    days: list[int] = []
    for m in _MD_RE.finditer(text):
        mon = _MONTHS.get(m.group(1)[:3].lower())
        if mon:
            days.append(mon * 31 + int(m.group(2)))
    for m in _NUM_RE.finditer(text):
        mon, day = int(m.group(1)), int(m.group(2))
        if 1 <= mon <= 12 and 1 <= day <= 31:
            days.append(mon * 31 + day)
    for m in _ISO_RE.finditer(text):
        days.append(int(m.group(1)) * 31 + int(m.group(2)))
    if not days:
        return None
    return (min(days), max(days))


def windows_overlap(a: tuple[int, int] | None, b: tuple[int, int] | None) -> bool:
    if a is None or b is None:
        return False
    return a[0] <= b[1] and b[0] <= a[1]


# --------------------------------------------------------------------------- #
# Row loading
# --------------------------------------------------------------------------- #

def _host(url: str) -> str:
    h = (urlparse(url or "").netloc or "").lower()
    return h[4:] if h.startswith("www.") else h


@dataclass
class PublishedRow:
    provider_host: str
    name: str
    info_url: str
    dates: str = ""
    raw: dict = field(default_factory=dict)


def load_ground_truth(town: str) -> list[dict]:
    path = GROUND_TRUTH_DIR / f"{town.lower()}.csv"
    if not path.exists():
        raise FileNotFoundError(f"no ground truth at {path}")
    with open(path, newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if (r.get("program_name") or "").strip()]
    return rows


def load_published(path: Path) -> list[PublishedRow]:
    """Load engine sessions.csv OR the old pipeline camp_sessions.csv."""
    out: list[PublishedRow] = []
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            name = (r.get("name") or "").strip()
            if not name:
                continue
            host = (
                _host(r.get("source_url", ""))
                or _host(r.get("info_url", ""))
                or _host(r.get("register_url", ""))
            )
            out.append(
                PublishedRow(
                    provider_host=host,
                    name=name,
                    info_url=(r.get("info_url") or "").strip(),
                    dates=(r.get("dates") or "").strip(),
                    raw=dict(r),
                )
            )
    return out


# --------------------------------------------------------------------------- #
# Scoring
# --------------------------------------------------------------------------- #

def load_aliases(town: str) -> dict[str, str]:
    """Optional <town>.aliases.csv: alt_host,provider_host — maps vendor/funnel
    hosts (majwhaydenweb.myvscloud.com, lexingtonma.gov) to the GT provider."""
    path = GROUND_TRUTH_DIR / f"{town.lower()}.aliases.csv"
    if not path.exists():
        return {}
    with open(path, newline="", encoding="utf-8") as f:
        return {
            r["alt_host"].strip().lower(): r["provider_host"].strip().lower()
            for r in csv.DictReader(f)
            if r.get("alt_host") and r.get("provider_host")
        }


def _hosts_related(gt_host: str, pub_host: str, aliases: dict[str, str] | None = None) -> bool:
    """Provider matching by host, tolerant of funnel aliases (gov -> myrec)."""
    if not gt_host or not pub_host:
        return False
    if aliases and aliases.get(pub_host) == gt_host:
        return True
    return gt_host == pub_host or gt_host in pub_host or pub_host in gt_host


def score(
    published: list[PublishedRow],
    ground_truth: list[dict],
    *,
    check_info_urls: bool = False,
    fetch_fn=None,
    aliases: dict[str, str] | None = None,
) -> dict:
    gt_programs: dict[tuple[str, str], list[dict]] = {}
    for r in ground_truth:
        key = (r["provider_host"].strip().lower(), normalize_name(r["program_name"]))
        gt_programs.setdefault(key, []).append(r)

    # Program recall: each distinct GT program matched by >=1 published row.
    matched_programs: set[tuple[str, str]] = set()
    # Session recall: GT rows with dates matched on program + window overlap.
    gt_sessions = [r for r in ground_truth if (r.get("session_dates") or "").strip()]
    matched_sessions = 0
    row_matched = [False] * len(published)

    for key, gt_rows in gt_programs.items():
        gt_host, _ = key
        gt_name = gt_rows[0]["program_name"]
        for i, pub in enumerate(published):
            if not _hosts_related(gt_host, pub.provider_host, aliases):
                continue
            if names_match(gt_name, pub.name):
                matched_programs.add(key)
                row_matched[i] = True

    for r in gt_sessions:
        gt_win = parse_date_window(r["session_dates"])
        for pub in published:
            if not _hosts_related(r["provider_host"].strip().lower(), pub.provider_host, aliases):
                continue
            if not names_match(r["program_name"], pub.name):
                continue
            if windows_overlap(gt_win, parse_date_window(pub.dates)):
                matched_sessions += 1
                break

    program_recall = len(matched_programs) / len(gt_programs) if gt_programs else 0.0
    session_recall = matched_sessions / len(gt_sessions) if gt_sessions else None
    precision = (sum(row_matched) / len(published)) if published else None

    info_validity = None
    info_checked = 0
    if check_info_urls and published:
        if fetch_fn is None:
            fetch_fn = _default_fetch
        valid = 0
        seen: dict[str, str] = {}
        for pub in published:
            if not pub.info_url:
                info_checked += 1
                continue
            if pub.info_url not in seen:
                seen[pub.info_url] = fetch_fn(pub.info_url)
            text = seen[pub.info_url]
            info_checked += 1
            if len(text) >= 400 and _name_in_text(pub.name, text):
                valid += 1
        info_validity = valid / info_checked if info_checked else None

    return {
        "gt_programs": len(gt_programs),
        "gt_sessions": len(gt_sessions),
        "published_rows": len(published),
        "program_recall": round(program_recall, 4),
        "session_recall": round(session_recall, 4) if session_recall is not None else None,
        "precision": round(precision, 4) if precision is not None else None,
        "info_url_validity": round(info_validity, 4) if info_validity is not None else None,
        "matched_programs": len(matched_programs),
        "matched_sessions": matched_sessions,
        "unmatched_gt_programs": sorted(
            f"{h}: {gt_programs[(h, n)][0]['program_name']}"
            for (h, n) in set(gt_programs) - matched_programs
        ),
    }


def _name_in_text(name: str, text: str) -> bool:
    """Program name present in page text: all (or all-but-one) tokens appear."""
    toks = _tokens(name)
    if not toks:
        return False
    low = text.lower()
    hits = sum(1 for t in toks if t in low)
    return hits >= max(1, len(toks) - 1)


def _default_fetch(url: str) -> str:
    import requests

    try:
        resp = requests.get(
            url,
            timeout=20,
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"},
        )
        return resp.text or ""
    except Exception:  # noqa: BLE001 — a dead URL is simply invalid
        return ""


# --------------------------------------------------------------------------- #
# History + CLI
# --------------------------------------------------------------------------- #

def write_history(town: str, metrics: dict, *, label: str = "") -> Path:
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%dT%H%M%S")
    name = f"{label or ts}.json" if label else f"{ts}.json"
    path = HISTORY_DIR / name
    payload = {"town": town, "timestamp": ts, "label": label, **metrics}
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def format_table(metrics: dict) -> str:
    rows = [
        ("GT programs", metrics["gt_programs"]),
        ("GT sessions (dated)", metrics["gt_sessions"]),
        ("Published rows", metrics["published_rows"]),
        ("Program recall", _pct(metrics["program_recall"])),
        ("Session recall", _pct(metrics["session_recall"])),
        ("Precision", _pct(metrics["precision"])),
        ("Info-url validity", _pct(metrics["info_url_validity"])),
    ]
    width = max(len(k) for k, _ in rows)
    return "\n".join(f"  {k:<{width}}  {v}" for k, v in rows)


def _pct(v) -> str:
    return "n/a" if v is None else f"{v * 100:.1f}%"
