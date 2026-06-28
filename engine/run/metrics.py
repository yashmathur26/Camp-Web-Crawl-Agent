"""Phase 6 — coverage rollup + link metrics + eval floor (v3 §Phase 6).

Turns the v3 standard into something the run measures and can enforce:

  * coverage rollup — per provider, was registration reached? (a HIGH/MEDIUM
    register_url, or any enroll affordance / platform link). No → missed signup.
  * link metrics — the one-screen health check: register==info rate SPLIT by
    register_is_info (real coincidence vs the old aliasing regression), the
    register_confidence distribution, the parent_url rung distribution, the
    missed-signup list, and the review-tier size (the false-negative gauge).
  * eval floor — when ground truth exists, fail the run loudly if confirmed
    precision / info_url_validity drops below threshold.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from engine.fetch.urls import normalize_url
from engine.model import Program, Provider
from engine.run.links import parent_rung


@dataclass
class ProviderCoverage:
    provider_id: str
    host: str
    confirmed: int = 0
    registration_reached: bool = False

    @property
    def missed_signup(self) -> bool:
        return self.confirmed > 0 and not self.registration_reached


def coverage_rollup(
    providers: list[Provider], programs: list[Program]
) -> list[ProviderCoverage]:
    """Per provider: registration reached iff any confirmed session carries a
    high/medium register link (or any register_url at all). Confirmed-but-none →
    missed signup (→ review + adapter flag)."""
    by_id: dict[str, ProviderCoverage] = {
        p.provider_id: ProviderCoverage(provider_id=p.provider_id, host=p.host)
        for p in providers
    }
    for prog in programs:
        cov = by_id.get(prog.provider_id)
        if cov is None:
            cov = by_id.setdefault(
                prog.provider_id,
                ProviderCoverage(provider_id=prog.provider_id, host=prog.provider_id),
            )
        for s in prog.sessions:
            cov.confirmed += 1
            if s.register_confidence in ("high", "medium") or s.register_url:
                cov.registration_reached = True
    return list(by_id.values())


@dataclass
class LinkMetrics:
    confirmed: int = 0
    review: int = 0
    register_found: int = 0
    register_eq_info_real: int = 0       # register==info AND register_is_info (legit)
    register_eq_info_regression: int = 0  # register==info WITHOUT the flag (alarm)
    confidence_dist: dict = field(default_factory=dict)
    rung_dist: dict = field(default_factory=dict)
    missed_signups: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "confirmed": self.confirmed,
            "review": self.review,
            "register_found": self.register_found,
            "register_eq_info_real": self.register_eq_info_real,
            "register_eq_info_regression": self.register_eq_info_regression,
            "confidence_dist": dict(self.confidence_dist),
            "rung_dist": dict(self.rung_dist),
            "missed_signups": list(self.missed_signups),
        }


def link_metrics(
    programs: list[Program],
    review: list[Program],
    coverage: list[ProviderCoverage] | None = None,
) -> LinkMetrics:
    m = LinkMetrics()
    conf: Counter = Counter()
    rung: Counter = Counter()
    for prog in programs:
        for s in prog.sessions:
            m.confirmed += 1
            conf[s.register_confidence or "none"] += 1
            rung[parent_rung(s, s.homepage_url)] += 1
            if s.register_url:
                m.register_found += 1
                if normalize_url(s.register_url) == normalize_url(s.info_url):
                    if s.register_is_info:
                        m.register_eq_info_real += 1
                    else:
                        m.register_eq_info_regression += 1
    m.review = sum(len(p.sessions) for p in review)
    m.confidence_dist = dict(conf)
    m.rung_dist = {f"rung{k}": v for k, v in sorted(rung.items())}
    if coverage:
        m.missed_signups = sorted(c.host for c in coverage if c.missed_signup)
    return m


def summary_lines(m: LinkMetrics) -> list[str]:
    """One-screen link health for the run narration."""
    reg_eq = m.register_eq_info_real + m.register_eq_info_regression
    rate = (reg_eq / m.register_found) if m.register_found else 0.0
    return [
        f"link health: {m.confirmed} confirmed, {m.review} review",
        f"  register found: {m.register_found}/{m.confirmed}; "
        f"register==info {reg_eq} ({rate*100:.0f}%) "
        f"= {m.register_eq_info_real} real / {m.register_eq_info_regression} REGRESSION",
        f"  confidence: {m.confidence_dist}",
        f"  parent_url rungs: {m.rung_dist}",
        f"  missed signups ({len(m.missed_signups)}): "
        + (", ".join(m.missed_signups[:10]) or "none"),
    ]


@dataclass
class EvalFloorResult:
    ok: bool
    precision: float | None
    info_url_validity: float | None
    floor: float
    reason: str = ""


def enforce_eval_floor(
    town: str, sessions_csv, floor: float, *, check_info_urls: bool = False
) -> EvalFloorResult | None:
    """Score the confirmed tier against ground truth and judge it against `floor`.
    Returns None when no ground truth exists for the town (nothing to enforce)."""
    from pathlib import Path

    from engine.eval.score import GROUND_TRUTH_DIR, load_ground_truth, load_published, score

    if not (GROUND_TRUTH_DIR / f"{town.lower()}.csv").exists():
        return None
    published = load_published(Path(sessions_csv))
    gt = load_ground_truth(town)
    metrics = score(published, gt, check_info_urls=check_info_urls)
    precision = metrics.get("precision")
    validity = metrics.get("info_url_validity")
    failed = []
    if precision is not None and precision < floor:
        failed.append(f"precision {precision:.2%} < {floor:.0%}")
    if validity is not None and validity < floor:
        failed.append(f"info_url_validity {validity:.2%} < {floor:.0%}")
    return EvalFloorResult(ok=not failed, precision=precision,
                           info_url_validity=validity, floor=floor,
                           reason="; ".join(failed))
