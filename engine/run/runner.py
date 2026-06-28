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
import logging
import time
from pathlib import Path

from config_engine import ENGINE

logger = logging.getLogger("engine.run")
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


def _dump_programs(programs: list[Program]) -> list[dict]:
    return [
        {**p.to_row(), "camp_scoped": p.camp_scoped,
         "sessions": [s.to_row() for s in p.sessions]}
        for p in programs
    ]


def _load_programs(raws: list[dict]) -> list[Program]:
    from engine.model import Session

    programs = []
    for praw in raws:
        prog = Program.from_row(praw)
        prog.camp_scoped = bool(praw.get("camp_scoped"))
        prog.sessions = [Session.from_row(s) for s in praw.get("sessions", [])]
        programs.append(prog)
    return programs


def _serialize_result(programs: list[Program], gaps: list[Gap], seconds: float,
                      review: list[Program] | None = None) -> dict:
    return {
        "programs": _dump_programs(programs),
        "review": _dump_programs(review or []),
        "gaps": [g.to_row() for g in gaps],
        "seconds": seconds,
        "done": True,
    }


def _deserialize_result(
    blob: dict,
) -> tuple[list[Program], list[Gap], float, list[Program]]:
    programs = _load_programs(blob.get("programs", []))
    review = _load_programs(blob.get("review", []))
    gaps = [Gap.from_row(g) for g in blob.get("gaps", [])]
    return programs, gaps, float(blob.get("seconds", 0.0)), review


# --------------------------------------------------------------------------- #
# Town run (7.1 parallel)
# --------------------------------------------------------------------------- #

async def run_town(
    town: str, *, out_root: Path | str = "data", fresh: bool = False,
    include_review: bool = False, eval_floor: float | None = None,
) -> dict[str, int]:
    registry = load_town(town)
    out_dir = Path(out_root) / town.lower() / "engine"
    report = RunReport(town=registry.town)
    ckpt = {} if fresh else load_checkpoint(out_dir)

    # P1.3: drop to 1 provider at a time when memory is tight, regardless of
    # the configured concurrency. (psutil read inline — engine never imports
    # src/, per R2.)
    concurrency = int(ENGINE["concurrency"])
    try:
        import psutil

        free_mb = int(psutil.virtual_memory().available / (1024 ** 2))
        if free_mb < 6000:
            concurrency = 1
        logger.info("engine start: %dMB free, concurrency=%d", free_mb, concurrency)
    except Exception:  # noqa: BLE001
        pass

    report.narrate(
        f"Engine run: {registry.town}, {len(registry.providers)} provider(s), "
        f"{sum(1 for v in ckpt.values() if v.get('done'))} from checkpoint, "
        f"concurrency={concurrency}"
    )

    try:
        from engine.extract.base import reset_shared_client

        reset_shared_client()
    except ImportError:
        pass
    extract = _resolve_extractor()
    sem = asyncio.Semaphore(concurrency)
    lock = asyncio.Lock()

    async def run_one(entry: RegistryEntry) -> None:
        provider = provider_from_entry(entry, registry.town)
        cached = ckpt.get(provider.provider_id)
        if cached and cached.get("done"):
            programs, gaps, seconds, review = _deserialize_result(cached)
            provider.status = "done" if programs else "gap"
            async with lock:
                report.providers.append(provider)
                report.provider_block(provider, programs, gaps, seconds, review=review)
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
            review: list[Program] = []
            gaps: list[Gap] = [gap] if gap else []

            def _clone(program: Program) -> Program:
                return Program(
                    name=program.name, provider_id=provider.provider_id,
                    info_url=program.info_url, category_hint=program.category_hint,
                    description_snippet=program.description_snippet,
                    camp_scoped=program.camp_scoped, program_id=program.program_id,
                )

            for program in programs_raw:
                result = gate_program(
                    program, fetched_text=fetched_text, provider_id=provider.provider_id,
                    provider_name=provider.name, provider_host=provider.host,
                    include_review=include_review,
                )
                if result.published:
                    kept = _clone(program)
                    kept.sessions = result.published
                    published.append(kept)
                if result.review:
                    flagged = _clone(program)
                    flagged.sessions = result.review
                    review.append(flagged)
                gaps.extend(result.gaps)
            # Phase 6L: resolve the link bundle (homepage_url + parent_url ladder)
            # on every confirmed session before write.
            from engine.run.links import annotate_link_bundle

            annotate_link_bundle(provider, published)
            seconds = time.monotonic() - t0
            provider.status = "done" if published else "gap"
            async with lock:
                report.providers.append(provider)
                report.provider_block(provider, published, gaps, seconds, review=review)
                ckpt[provider.provider_id] = _serialize_result(
                    published, gaps, seconds, review=review)
                save_checkpoint(out_dir, ckpt)  # crash-safe: saved per provider

    await asyncio.gather(*(run_one(e) for e in registry.providers))
    # Close the shared Chromium inside this loop (clean close, not abandon) —
    # frees its RAM before the caller moves on to Phase C.
    try:
        from engine.fetch.render import shutdown_browser_pool

        await shutdown_browser_pool()
    except Exception:  # noqa: BLE001
        pass
    counts = report.write(out_dir)

    # Phase 6 eval floor: when a threshold is set and ground truth exists, fail
    # the run loudly if the confirmed tier's precision / info_url_validity drops
    # below it. A slop run must not pass quietly.
    if eval_floor is not None:
        from engine.run.metrics import enforce_eval_floor

        res = enforce_eval_floor(town, out_dir / "sessions.csv", eval_floor)
        if res is None:
            report.narrate(f"eval floor: no ground truth for {town}; skipped")
        elif res.ok:
            report.narrate(
                f"eval floor PASSED (>= {eval_floor:.0%}): "
                f"precision={res.precision}, info_url_validity={res.info_url_validity}")
        else:
            report.narrate(f"EVAL FLOOR FAILED: {res.reason}")
            raise RuntimeError(f"engine run failed eval floor: {res.reason}")
    return counts


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
    ap.add_argument("--eval-floor", type=float, default=None,
                    help="fail the run if confirmed precision/info_url_validity < FLOOR "
                         "(e.g. 0.95); requires ground truth for the town")
    args = ap.parse_args(argv)
    counts = asyncio.run(run_town(args.town, out_root=args.out_root, fresh=args.fresh,
                                  include_review=args.review, eval_floor=args.eval_floor))
    print("rows:", counts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
