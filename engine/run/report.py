"""ONE output writer + plain-English narration (R6.1, R7.4).

Every count printed comes from the same result lists that feed the CSVs —
the old pipeline printed "0 published" and "+26 rows" for one provider because
two writers disagreed; here there is exactly one.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from engine.model import Gap, Program, Provider, write_output

logger = logging.getLogger("engine")


@dataclass
class RunReport:
    town: str
    providers: list[Provider] = field(default_factory=list)
    programs: list[Program] = field(default_factory=list)
    review: list[Program] = field(default_factory=list)
    gaps: list[Gap] = field(default_factory=list)
    narration: list[str] = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=dict)
    coverage: list = field(default_factory=list)        # Phase 6 ProviderCoverage
    link_metrics: object = None                          # Phase 6 LinkMetrics

    def narrate(self, line: str) -> None:
        self.narration.append(line)
        logger.info(line)

    def provider_block(
        self, provider: Provider, programs: list[Program], gaps: list[Gap],
        seconds: float, review: list[Program] | None = None,
    ) -> None:
        """One narration block per provider: tried X, found Y, gapped Z because W."""
        review = review or []
        self.programs.extend(programs)
        self.review.extend(review)
        self.gaps.extend(gaps)
        self.timings[provider.host] = round(seconds, 1)
        sessions = sum(len(p.sessions) for p in programs)
        review_sessions = sum(len(p.sessions) for p in review)
        self.narrate(
            f"[{provider.host}] vendor={provider.vendor} → "
            f"{len(programs)} program(s), {sessions} session(s), "
            f"{review_sessions} review, {len(gaps)} gap(s) "
            f"in {seconds:.1f}s"
        )
        for g in gaps[:5]:
            self.narrate(f"  gap: {g.reason} — {g.evidence[:120]}")

    def write(self, out_dir: Path) -> dict[str, int]:
        counts = write_output(out_dir, self.providers, self.programs, self.gaps,
                              review=self.review)
        # Phase 6L: the two deliverable surfaces — parent CSV (one link per camp)
        # + Firecrawl manifest (internal content links keyed by camp_id).
        from engine.run.links import write_link_views

        counts.update(write_link_views(out_dir, self.programs, self.town))

        # Phase 6: coverage rollup + link metrics → coverage.csv + run summary.
        import csv as _csv

        from engine.run.metrics import coverage_rollup, link_metrics, summary_lines

        self.coverage = coverage_rollup(self.providers, self.programs)
        self.link_metrics = link_metrics(self.programs, self.review, self.coverage)
        with open(out_dir / "coverage.csv", "w", newline="", encoding="utf-8") as f:
            w = _csv.DictWriter(
                f, fieldnames=["provider_id", "host", "confirmed",
                               "registration_reached", "missed_signup"])
            w.writeheader()
            for c in self.coverage:
                w.writerow({"provider_id": c.provider_id, "host": c.host,
                            "confirmed": c.confirmed,
                            "registration_reached": c.registration_reached,
                            "missed_signup": c.missed_signup})
        counts["coverage.csv"] = len(self.coverage)
        (out_dir / "narration.log").write_text(
            "\n".join(self.narration) + "\n", encoding="utf-8"
        )
        from engine.run.metrics import summary_lines

        summary = [
            f"== engine run — {self.town} — {time.strftime('%Y-%m-%d %H:%M:%S')} ==",
            *(f"  {fname}: {n} rows" for fname, n in counts.items()),
            "  slowest providers: "
            + ", ".join(
                f"{h}={s}s"
                for h, s in sorted(self.timings.items(), key=lambda kv: -kv[1])[:5]
            ),
            *(f"  {ln}" for ln in summary_lines(self.link_metrics)),
        ]
        for line in summary:
            self.narrate(line)
        (out_dir / "narration.log").write_text(
            "\n".join(self.narration) + "\n", encoding="utf-8"
        )
        return counts
