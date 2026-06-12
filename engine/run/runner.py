"""Runner (Phase 7): parallel per-provider jobs, resumable via checkpoint,
single writer. `python -m engine.run --town lexington [--fresh]`.

- Concurrency: ENGINE["concurrency"] providers in flight (asyncio). Host
  politeness lives in the shared fetch layer, so parallel providers cannot
  hammer one host. Plain-path fetches are sync (httpx) and serialize at the
  event loop; render/capture awaits parallelize — the wall-clock win is on the
  browser-heavy providers.
- Resumability: data/<town>/engine/checkpoint.json maps provider_id -> result;
  a rerun skips finished providers entirely (no fetches). --fresh ignores it.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from config_engine import ENGINE
from engine.model import Gap, Program, Provider
from engine.registry.schema import RegistryEntry, load_town
from engine.run.report import RunReport
from engine.validate.gate import gate_program


def provider_from_entry(entry: RegistryEntry, town: str) -> Provider:
    return Provider(
        name=entry.name, host=entry.host, town=town, seed_url=entry.seed,
        vendor=entry.vendor, org_id=entry.org_id, aliases=entry.aliases,
    )


async def _stub_extract(provider: Provider):
    gap = Gap(provider_id=provider.provider_id, reason="needs_adapter",
              evidence=f"no extractor wired for vendor '{provider.vendor}' yet",
              suggested_action=f"implement engine/extract/vendors/{provider.vendor}.py")
    return [], gap, {}


def _resolve_extractor():
    try:
        from engine.extract.base import extract_for_provider

        return extract_for_provider
    except ImportError:
        return _stub_extract


# --------------------------------------------------------------------------- #
# Checkpoint (7.2)
# --------------------------------------------------------------------------- #

def _ckpt_path(out_dir: Path) -> Path:
    return out_dir / "checkpoint.json"


def load_checkpoint(out_dir: Path) -> dict:
    p = _ckpt_path(out_dir)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except json.JSONDecodeError:
            return {}
    return {}


def save_checkpoint(out_dir: Path, ckpt: dict) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    _ckpt_path(out_dir).write_text(json.dumps(ckpt))


def _serialize_result(programs: list[Program], gaps: list[Gap], seconds: float) -> dict:
    return {
        "programs": [
            {**p.to_row(), "camp_scoped": p.camp_scoped,
             "sessions": [s.to_row() for s in p.sessions]}
            for p in programs
        ],
        "gaps": [g.to_row() for g in gaps],
        "seconds": seconds,
        "done": True,
    }


def _deserialize_result(blob: dict) -> tuple[list[Program], list[Gap], float]:
    from engine.model import Session

    programs = []
    for praw in blob.get("programs", []):
        prog = Program.from_row(praw)
        prog.camp_scoped = bool(praw.get("camp_scoped"))
        prog.sessions = [Session.from_row(s) for s in praw.get("sessions", [])]
        programs.append(prog)
    gaps = [Gap.from_row(g) for g in blob.get("gaps", [])]
    return programs, gaps, float(blob.get("seconds", 0.0))


# --------------------------------------------------------------------------- #
# Town run (7.1 parallel)
# --------------------------------------------------------------------------- #

async def run_town(
    town: str, *, out_root: Path | str = "data", fresh: bool = False,
    include_review: bool = False,
) -> dict[str, int]:
    registry = load_town(town)
    out_dir = Path(out_root) / town.lower() / "engine"
    report = RunReport(town=registry.town)
    ckpt = {} if fresh else load_checkpoint(out_dir)
    report.narrate(
        f"Engine run: {registry.town}, {len(registry.providers)} provider(s), "
        f"{sum(1 for v in ckpt.values() if v.get('done'))} from checkpoint, "
        f"concurrency={ENGINE['concurrency']}"
    )

    try:
        from engine.extract.base import reset_shared_client

        reset_shared_client()
    except ImportError:
        pass
    extract = _resolve_extractor()
    sem = asyncio.Semaphore(int(ENGINE["concurrency"]))
    lock = asyncio.Lock()

    async def run_one(entry: RegistryEntry) -> None:
        provider = provider_from_entry(entry, registry.town)
        cached = ckpt.get(provider.provider_id)
        if cached and cached.get("done"):
            programs, gaps, seconds = _deserialize_result(cached)
            provider.status = "done" if programs else "gap"
            async with lock:
                report.providers.append(provider)
                report.provider_block(provider, programs, gaps, seconds)
            return
        async with sem:
            t0 = time.monotonic()
            try:
                programs_raw, gap, fetched_text = await extract(provider)
            except Exception as exc:  # noqa: BLE001
                programs_raw, gap, fetched_text = [], Gap(
                    provider_id=provider.provider_id, reason="render_failed",
                    evidence=f"extractor crashed: {exc}",
                    suggested_action="inspect traceback",
                ), {}
            published: list[Program] = []
            gaps: list[Gap] = [gap] if gap else []
            for program in programs_raw:
                result = gate_program(
                    program, fetched_text=fetched_text, provider_id=provider.provider_id,
                    include_review=include_review,
                )
                if result.published:
                    kept = Program(
                        name=program.name, provider_id=provider.provider_id,
                        info_url=program.info_url, category_hint=program.category_hint,
                        description_snippet=program.description_snippet,
                        camp_scoped=program.camp_scoped, program_id=program.program_id,
                    )
                    kept.sessions = result.published
                    published.append(kept)
                gaps.extend(result.gaps)
            seconds = time.monotonic() - t0
            provider.status = "done" if published else "gap"
            async with lock:
                report.providers.append(provider)
                report.provider_block(provider, published, gaps, seconds)
                ckpt[provider.provider_id] = _serialize_result(published, gaps, seconds)
                save_checkpoint(out_dir, ckpt)  # crash-safe: saved per provider

    await asyncio.gather(*(run_one(e) for e in registry.providers))
    return report.write(out_dir)


def main(argv: list[str] | None = None) -> int:
    import argparse
    import logging

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(name)s %(message)s", datefmt="%H:%M:%S"
    )
    ap = argparse.ArgumentParser(description="Engine v3 town run")
    ap.add_argument("--town", required=True)
    ap.add_argument("--out-root", default="data")
    ap.add_argument("--fresh", action="store_true",
                    help="ignore the checkpoint and rerun every provider")
    ap.add_argument("--review", action="store_true",
                    help="publish evidence/audience rejects as needs_review for human markup")
    args = ap.parse_args(argv)
    counts = asyncio.run(run_town(args.town, out_root=args.out_root, fresh=args.fresh,
                                  include_review=args.review))
    print("rows:", counts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
