"""Runner v0 (task 1.6): registry → extractor → gate → writer. Sequential.

Phase 3 swaps the stub dispatch for real vendor extractors; Phase 7 adds
parallelism + resumability. `python -m engine.run --town lexington`.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

from engine.model import Gap, Program, Provider
from engine.registry.schema import RegistryEntry, load_town
from engine.run.report import RunReport
from engine.validate.gate import gate_program


def provider_from_entry(entry: RegistryEntry, town: str) -> Provider:
    return Provider(
        name=entry.name, host=entry.host, town=town, seed_url=entry.seed,
        vendor=entry.vendor, org_id=entry.org_id, aliases=entry.aliases,
    )


async def _stub_extract(provider: Provider) -> tuple[list[Program], Gap | None, dict[str, str]]:
    """v0 stub: every provider gaps as needs_adapter (replaced in Phase 3)."""
    gap = Gap(
        provider_id=provider.provider_id,
        reason="needs_adapter",
        evidence=f"no extractor wired for vendor '{provider.vendor}' yet",
        suggested_action=f"implement engine/extract/vendors/{provider.vendor}.py",
    )
    return [], gap, {}


async def run_town(town: str, *, out_root: Path | str = "data") -> dict[str, int]:
    registry = load_town(town)
    report = RunReport(town=registry.town)
    report.narrate(
        f"Engine run: {registry.town}, {len(registry.providers)} registered provider(s)"
    )

    extract = _resolve_extractor()
    for entry in registry.providers:
        provider = provider_from_entry(entry, registry.town)
        t0 = time.monotonic()
        try:
            programs, gap, fetched_text = await extract(provider)
        except Exception as exc:  # noqa: BLE001 — a provider must never kill the town run
            programs, gap, fetched_text = [], Gap(
                provider_id=provider.provider_id, reason="render_failed",
                evidence=f"extractor crashed: {exc}",
                suggested_action="inspect traceback in engine log",
            ), {}

        published_programs: list[Program] = []
        gaps: list[Gap] = [gap] if gap else []
        for program in programs:
            result = gate_program(
                program, fetched_text=fetched_text, provider_id=provider.provider_id
            )
            if result.published:
                kept = Program(
                    name=program.name, provider_id=provider.provider_id,
                    info_url=program.info_url, category_hint=program.category_hint,
                    description_snippet=program.description_snippet,
                    camp_scoped=program.camp_scoped,
                    program_id=program.program_id,
                )
                kept.sessions = result.published
                published_programs.append(kept)
            gaps.extend(result.gaps)

        provider.status = "done" if published_programs else "gap"
        report.providers.append(provider)
        report.provider_block(provider, published_programs, gaps, time.monotonic() - t0)

    out_dir = Path(out_root) / town.lower() / "engine"
    return report.write(out_dir)


def _resolve_extractor():
    """Dispatch hook: Phase 3 installs the vendor dispatcher here."""
    try:
        from engine.extract.base import extract_for_provider

        return extract_for_provider
    except ImportError:
        return _stub_extract


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Engine v3 town run")
    ap.add_argument("--town", required=True)
    ap.add_argument("--out-root", default="data")
    args = ap.parse_args(argv)
    counts = asyncio.run(run_town(args.town, out_root=args.out_root))
    print("rows:", counts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
