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
    gaps: list[Gap] = field(default_factory=list)
    narration: list[str] = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=dict)

    def narrate(self, line: str) -> None:
        self.narration.append(line)
        logger.info(line)

    def provider_block(
        self, provider: Provider, programs: list[Program], gaps: list[Gap], seconds: float
    ) -> None:
        """One narration block per provider: tried X, found Y, gapped Z because W."""
        self.programs.extend(programs)
        self.gaps.extend(gaps)
        self.timings[provider.host] = round(seconds, 1)
        sessions = sum(len(p.sessions) for p in programs)
        self.narrate(
            f"[{provider.host}] vendor={provider.vendor} → "
            f"{len(programs)} program(s), {sessions} session(s), {len(gaps)} gap(s) "
            f"in {seconds:.1f}s"
        )
        for g in gaps[:5]:
            self.narrate(f"  gap: {g.reason} — {g.evidence[:120]}")

    def write(self, out_dir: Path) -> dict[str, int]:
        counts = write_output(out_dir, self.providers, self.programs, self.gaps)
        (out_dir / "narration.log").write_text(
            "\n".join(self.narration) + "\n", encoding="utf-8"
        )
        summary = [
            f"== engine run — {self.town} — {time.strftime('%Y-%m-%d %H:%M:%S')} ==",
            *(f"  {fname}: {n} rows" for fname, n in counts.items()),
            "  slowest providers: "
            + ", ".join(
                f"{h}={s}s"
                for h, s in sorted(self.timings.items(), key=lambda kv: -kv[1])[:5]
            ),
        ]
        for line in summary:
            self.narrate(line)
        (out_dir / "narration.log").write_text(
            "\n".join(self.narration) + "\n", encoding="utf-8"
        )
        return counts
