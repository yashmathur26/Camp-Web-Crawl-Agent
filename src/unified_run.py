"""Unified run orchestrator — one command, all engines/parts, one big CSV.

You give it a town (or several); it runs every discovery source IN ORDER —

    Phase A (search) -> Phase B (harvest) -> v3 engine -> Part D (hubs + US
    Sports Camps) -> Part C (agentic gap fill)

— inside an isolated, timestamped run workspace, then merges everything every
source produced into a single deduped catalog CSV.

Workspace layout (one folder per run):

    runs/<YYYY-MM-DD_HHMMSS>/
        data/            all per-run pipeline output (FIREFLY_DATA_ROOT)
            _baseline    -> symlink to the shared committed baselines
            _snapshots   -> symlink to shared hub snapshots (cross-run diffing)
            _fixtures    -> symlink to shared golden fixtures
        logs/            per-run logs (FIREFLY_LOGS_ROOT) + one log per stage
        all_camps.csv    the merged one-big-CSV deliverable
        all_camps.txt    readable report
        manifest.json    timestamp, towns, per-stage status/duration, counts

Cross-run state stays shared so runs are cheap: the engine fetch DB
(data/cache), search-dedup caches (cache/), and curated registries
(engine/registry/towns) are NOT copied per run.

Each stage runs as its own subprocess with FIREFLY_DATA_ROOT / FIREFLY_LOGS_ROOT
pointed at the run folder, so a stage that fails or lacks prerequisites (no API
key, no curated registry, no candidates) is logged and skipped without killing
the run. Whatever camps any stage produced still get merged.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNS_ROOT = REPO_ROOT / "runs"
SHARED_DATA = REPO_ROOT / "data"
REGISTRY_DIR = REPO_ROOT / "engine" / "registry" / "towns"

# Shared, read-mostly dirs symlinked into each run's data/ so the pipeline can
# read committed baselines/fixtures and persist cross-run hub snapshots.
SHARED_SYMLINKS = ("_baseline", "_fixtures", "_snapshots")

# Ordered stages. `scope`: "per_town" runs once per town; "once" runs with the
# full town list. `cmd` is built lazily so it can see the run context.
STAGE_ORDER = ["A", "B", "engine", "D", "C"]


@dataclass
class RunContext:
    ts: str
    run_dir: Path
    data_dir: Path
    logs_dir: Path
    towns: list[str]
    env: dict = field(default_factory=dict)
    registry_dir: Path | None = None


def _now_ts() -> str:
    return datetime.now().strftime("%Y-%m-%d_%H%M%S")


def create_workspace(towns: list[str], *, runs_root: Path | None = None, ts: str | None = None,
                     resume_dir: Path | None = None) -> RunContext:
    runs_root = runs_root or RUNS_ROOT
    if resume_dir is not None:
        # RESUME: reuse an existing run folder verbatim — never wipe. Phase B
        # skips sources already marked crawled in each town's candidates.csv, and
        # the engine resumes from its checkpoint.json. Idempotent setup below.
        run_dir = Path(resume_dir)
        ts = run_dir.name
    else:
        ts = ts or _now_ts()
        run_dir = runs_root / ts
    data_dir = run_dir / "data"
    logs_dir = run_dir / "logs"
    data_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    # Symlink shared read-mostly dirs into the per-run data dir.
    for name in SHARED_SYMLINKS:
        target = SHARED_DATA / name
        if not target.exists():
            target.mkdir(parents=True, exist_ok=True)
        link = data_dir / name
        if not link.exists():
            try:
                link.symlink_to(target, target_is_directory=True)
            except OSError as exc:  # pragma: no cover - platform/FS dependent
                logger.warning("could not symlink %s: %s", name, exc)

    # Per-run engine registry dir, seeded with the committed curated registries.
    # Auto-generated registries for other towns are written here at run time, so
    # the engine works for EVERY town without polluting the committed registry.
    registry_dir = run_dir / "registry"
    registry_dir.mkdir(parents=True, exist_ok=True)
    if REGISTRY_DIR.is_dir():
        import shutil

        for y in REGISTRY_DIR.glob("*.yaml"):
            if y.name.endswith(".proposals.yaml"):
                continue
            dst = registry_dir / y.name
            if not dst.exists():  # don't clobber an auto-built registry on resume
                shutil.copy2(y, dst)

    env = dict(os.environ)
    env["FIREFLY_DATA_ROOT"] = str(data_dir)
    env["FIREFLY_LOGS_ROOT"] = str(logs_dir)
    env["FIREFLY_REGISTRY_DIR"] = str(registry_dir)
    env["PYTHONUNBUFFERED"] = "1"

    ctx = RunContext(ts=ts, run_dir=run_dir, data_dir=data_dir, logs_dir=logs_dir, towns=towns, env=env)
    ctx.registry_dir = registry_dir
    return ctx


# --------------------------------------------------------------------------- #
# Engine registry: auto-build from Phase A/B discovery so the engine works for
# EVERY town, not just the two with a hand-curated registry.
# --------------------------------------------------------------------------- #
def _vendor_from_url(url: str) -> tuple[str, str]:
    """(vendor, org_id) fingerprinted from a URL host alone (no fetch)."""
    from urllib.parse import urlparse

    from engine.registry.proposer import VENDOR_SIGNATURES

    low = url.lower()
    netloc = urlparse(url).netloc.lower().replace("www.", "")
    if "communityed" in netloc:
        return "communityed", netloc.split(".")[0]
    for sub, vendor in VENDOR_SIGNATURES:
        if sub in low:
            org = ""
            if vendor == "webtrac" and netloc.endswith("myvscloud.com"):
                org = netloc.split(".")[0]
            elif vendor == "myrec":
                org = netloc.split(".")[0]
            return vendor, org
    return "unknown", ""


def build_registry_from_discovery(town: str, data_dir: Path, registry_dir: Path, *, cap: int = 80) -> Path | None:
    """Build an engine registry YAML for `town` from this run's Phase A/B output.

    Sources: shared/phase_a/candidates.csv (provider seeds for the town) and
    shared/phase_b/camp_links.csv (registration URLs that reveal vendor hosts).
    Known-vendor hosts are listed first. Returns the path, or None if discovery
    surfaced nothing (engine then has nothing to do for that town).
    """
    import csv

    import yaml

    from urllib.parse import urlparse

    from engine.registry.proposer import _DENY_HOST_RE

    urls: list[str] = []
    cand = data_dir / "shared" / "phase_a" / "candidates.csv"
    if cand.exists():
        with cand.open(newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if (r.get("town") or "").strip().lower() == town.lower() and r.get("url"):
                    urls.append(r["url"])
    links = data_dir / "shared" / "phase_b" / "camp_links.csv"
    if links.exists():
        with links.open(newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if (r.get("town_hint") or "").strip().lower() == town.lower() and r.get("url"):
                    urls.append(r["url"])

    known: list[dict] = []
    unknown: list[dict] = []
    seen: set[str] = set()
    for u in urls:
        host = urlparse(u).netloc.lower().replace("www.", "")
        if not host or host in seen or _DENY_HOST_RE.search(host):
            continue
        seen.add(host)
        vendor, org = _vendor_from_url(u)
        entry = {"name": host, "host": host, "seed": u, "vendor": vendor, "org_id": org}
        (known if vendor != "unknown" else unknown).append(entry)

    providers = (known + unknown)[:cap]
    if not providers:
        return None

    out = registry_dir / f"{town.replace(' ', '_').lower()}.yaml"
    out.write_text(
        yaml.safe_dump(
            {"town": town, "state": "MA",
             "_generated": "auto-built from Phase A/B discovery by unified_run",
             "providers": providers},
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return out


def ensure_registry(ctx: RunContext, town: str, *, data_root: Path | None = None) -> bool:
    """Make sure an engine registry exists for `town`. Returns True if available.

    Curated committed registries (copied in at workspace creation) win; otherwise
    one is auto-built from `data_root`'s discovery (the town's isolated root when
    running in parallel, else the shared run data dir).
    """
    reg_dir = ctx.registry_dir or (ctx.run_dir / "registry")
    slug = town.replace(" ", "_").lower()
    existing = reg_dir / f"{slug}.yaml"
    if existing.exists():
        return True
    built = build_registry_from_discovery(town, data_root or ctx.data_dir, reg_dir)
    return built is not None


def _link_shared_into(data_root: Path) -> None:
    """Symlink the shared read-mostly dirs into a (per-town) data root."""
    data_root.mkdir(parents=True, exist_ok=True)
    for name in SHARED_SYMLINKS:
        target = SHARED_DATA / name
        if not target.exists():
            target.mkdir(parents=True, exist_ok=True)
        link = data_root / name
        if not link.exists():
            try:
                link.symlink_to(target, target_is_directory=True)
            except OSError:  # pragma: no cover
                pass


def _town_data_root(ctx: RunContext, town: str, *, isolated: bool) -> Path:
    """Where a town's A/B/engine write. Isolated (own root) for parallel runs so
    concurrent towns never race the shared candidates.csv / camp_links.csv."""
    if not isolated:
        return ctx.data_dir
    root = ctx.data_dir / "_towns" / town.replace(" ", "_").lower()
    _link_shared_into(root)
    return root


def _town_env(ctx: RunContext, data_root: Path) -> dict:
    env = dict(ctx.env)
    env["FIREFLY_DATA_ROOT"] = str(data_root)
    return env


def _collect_town_outputs(ctx: RunContext, town: str, town_root: Path) -> None:
    """Copy an isolated town's engine + phase outputs into the main run data dir
    (under <slug>/) so Part C and the merge find them in the standard layout."""
    import shutil

    slug = town.replace(" ", "_").lower()
    src = town_root / slug
    if not src.is_dir():
        return
    dst = ctx.data_dir / slug
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        target = dst / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
        else:
            shutil.copy2(item, target)


def _run_cmd(cmd: list[str], *, env: dict, log_path: Path, timeout: int | None = None) -> dict:
    """Run one stage subprocess, tee output to log_path. Returns a status dict."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    t0 = datetime.now()
    header = f"$ {' '.join(cmd)}\n# started {t0.isoformat()}\n{'=' * 70}\n"
    with log_path.open("w", encoding="utf-8") as logf:
        logf.write(header)
        logf.flush()
        try:
            proc = subprocess.run(
                cmd, cwd=str(REPO_ROOT), env=env, stdout=logf,
                stderr=subprocess.STDOUT, timeout=timeout, check=False,
            )
            rc = proc.returncode
            status = "ok" if rc == 0 else "error"
        except subprocess.TimeoutExpired:
            rc = -1
            status = "timeout"
        except Exception as exc:  # noqa: BLE001
            logf.write(f"\n[orchestrator] launch failed: {exc}\n")
            rc, status = -2, "launch_failed"
    seconds = (datetime.now() - t0).total_seconds()
    return {"status": status, "rc": rc, "seconds": round(seconds, 1), "log": str(log_path)}


def _town_stage_specs(ctx: RunContext, town: str, *, isolated: bool = False) -> list[dict]:
    """A -> B -> engine for one town (run sequentially within the town).

    When isolated, the town writes to its own data root (parallel-safe) and the
    engine emits there; outputs are collected into the main dir afterward.
    """
    py = [sys.executable]
    slug = town.replace(" ", "_").lower()
    data_root = _town_data_root(ctx, town, isolated=isolated)
    env = _town_env(ctx, data_root) if isolated else ctx.env
    common = {"town": town, "env": env, "town_data_root": data_root}
    return [
        {"key": f"A:{town}", "stage": "A", **common,
         "cmd": py + ["-m", "src.run", "--no-dry-run", "--phase", "A", "--town", town]},
        {"key": f"B:{town}", "stage": "B", **common,
         # harvest only — the v3 engine does enumeration; B5's enumeration here
         # is unused by the merge AND is where the slow agent-navigator lives.
         "cmd": py + ["-m", "src.run", "--no-dry-run", "--phase", "B", "--town", town,
                      "--no-enumerate-sessions"]},
        {"key": f"engine:{town}", "stage": "engine", **common,
         "cmd": py + ["-m", "engine.run", "--town", slug, "--out-root", str(data_root)]},
    ]


def _shared_stage_specs(ctx: RunContext, *, gate: bool, per_sport: int) -> list[dict]:
    """Part D then Part C — run once across all towns, after per-town pipelines."""
    py = [sys.executable]
    towns_csv = ",".join(ctx.towns)
    d_cmd = py + ["-m", "scripts.run_part_d", "--town", towns_csv, "--per-sport", str(per_sport)]
    if not gate:
        d_cmd.append("--no-gate")
    return [
        {"key": "D", "stage": "D", "town": None, "cmd": d_cmd},
        {"key": "C", "stage": "C", "town": None,
         "cmd": py + ["-m", "src.run", "--no-dry-run", "--phase", "C", "--towns", towns_csv]},
    ]


def _execute_stage(ctx: RunContext, spec: dict, *, skip: set, only: set, stage_timeout: int | None) -> dict | None:
    """Run one stage with skip/only filtering and engine-registry guarding."""
    st = spec["stage"]
    if only and st not in only:
        return None
    if st in skip:
        return {"key": spec["key"], "stage": st, "status": "skipped", "rc": 0, "seconds": 0.0}
    if st == "engine":
        if not ensure_registry(ctx, spec["town"], data_root=spec.get("town_data_root")):
            logger.info("stage %s -> skipped (no providers discovered)", spec["key"])
            return {"key": spec["key"], "stage": st, "status": "skipped_no_registry", "rc": 0, "seconds": 0.0}
    log_path = ctx.logs_dir / f"stage_{spec['key'].replace(':', '_')}.log"
    res = _run_cmd(spec["cmd"], env=spec.get("env", ctx.env), log_path=log_path, timeout=stage_timeout)
    res.update({"key": spec["key"], "stage": st})
    logger.info("stage %s -> %s (%ss)", spec["key"], res["status"], res["seconds"])
    return res


def _run_town_pipeline(ctx: RunContext, town: str, *, skip: set, only: set,
                       stage_timeout: int | None, isolated: bool = False) -> list[dict]:
    out: list[dict] = []
    specs = _town_stage_specs(ctx, town, isolated=isolated)
    for spec in specs:
        r = _execute_stage(ctx, spec, skip=skip, only=only, stage_timeout=stage_timeout)
        if r is not None:
            out.append(r)
    if isolated:
        _collect_town_outputs(ctx, town, specs[0]["town_data_root"])
    return out


def run_unified(
    towns: list[str],
    *,
    skip: set[str] | None = None,
    only: set[str] | None = None,
    gate: bool = False,
    per_sport: int = 10,
    runs_root: Path | None = None,
    stage_timeout: int | None = None,
    town_parallelism: int = 1,
    resume_dir: Path | None = None,
    ts: str | None = None,
) -> dict:
    """Run the full unified pipeline for `towns` and merge into one CSV.

    skip/only filter by stage letter ({"A","B","engine","D","C"}).
    town_parallelism > 1 runs that many town pipelines (A->B->engine) at once;
    each town stays internally sequential and full-depth. Part D and Part C run
    once after all town pipelines finish.
    """
    skip = skip or set()
    only = only or set()
    ctx = create_workspace(towns, runs_root=runs_root, ts=ts, resume_dir=resume_dir)
    logger.info("unified run %s -> %s | towns=%s | parallelism=%d | resume=%s",
                ctx.ts, ctx.run_dir, towns, town_parallelism, bool(resume_dir))

    stage_results: list[dict] = []
    # Per-town pipelines (A->B->engine), optionally concurrent across towns.
    if town_parallelism > 1 and len(ctx.towns) > 1:
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=town_parallelism) as ex:
            futs = {
                ex.submit(_run_town_pipeline, ctx, t, skip=skip, only=only,
                          stage_timeout=stage_timeout, isolated=True): t
                for t in ctx.towns
            }
            per_town = {futs[f]: f.result() for f in futs}
        for t in ctx.towns:  # stable, town-ordered results
            stage_results.extend(per_town.get(t, []))
    else:
        for t in ctx.towns:
            stage_results.extend(
                _run_town_pipeline(ctx, t, skip=skip, only=only, stage_timeout=stage_timeout)
            )

    # Shared stages (Part D, then Part C) once all towns are done.
    for spec in _shared_stage_specs(ctx, gate=gate, per_sport=per_sport):
        r = _execute_stage(ctx, spec, skip=skip, only=only, stage_timeout=stage_timeout)
        if r is not None:
            stage_results.append(r)

    rows = merge_run_catalog(ctx.data_dir)
    csv_path, txt_path = write_merged(rows, ctx.run_dir)

    by_source: dict[str, int] = {}
    for r in rows:
        by_source[r["source"]] = by_source.get(r["source"], 0) + 1

    manifest = {
        "timestamp": ctx.ts,
        "created_at": datetime.now().isoformat(),
        "towns": towns,
        "town_parallelism": town_parallelism,
        "stages": stage_results,
        "total_camps": len(rows),
        "camps_by_source": by_source,
        "outputs": {"merged_csv": str(csv_path), "merged_txt": str(txt_path)},
    }
    (ctx.run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    logger.info("unified run done: %d camps -> %s", len(rows), csv_path)
    return {"ctx": ctx, "manifest": manifest, "rows": rows, "csv_path": str(csv_path)}


# --------------------------------------------------------------------------- #
# Merge: every source CSV -> one deduped catalog
# --------------------------------------------------------------------------- #
UNIFIED_FIELDS = [
    "source", "town", "name", "platform", "geo_town", "geo_city", "geo_state",
    "geo_zip", "start_date", "dates", "ages", "price", "register_url",
    "info_url", "verdict", "serving_towns", "discovered_via", "session_uid",
]


def _unslug(slug: str) -> str:
    return slug.replace("_", " ").title()


def _base_row(source: str, town: str) -> dict:
    return {k: "" for k in UNIFIED_FIELDS} | {"source": source, "town": town, "serving_towns": [town] if town else []}


def _read_csv(path: Path) -> list[dict]:
    import csv

    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def merge_run_catalog(data_dir: Path) -> list[dict]:
    """Collect every camp-producing CSV under a run's data dir, normalize, dedup."""
    from src.geo_resolve import geo_tag
    from src.hub_dedup import dedupe_sessions
    from src.season import parse_start_date

    raw: list[dict] = []

    def add(row: dict):
        if (row.get("name") or row.get("register_url")):
            raw.append(row)

    # Engine sessions: <town>/engine/sessions.csv
    for p in data_dir.glob("*/engine/sessions.csv"):
        town = _unslug(p.parts[-3])
        for r in _read_csv(p):
            row = _base_row("engine", town)
            row.update({
                "name": r.get("name", ""), "platform": "engine",
                "register_url": r.get("register_url", ""), "info_url": r.get("info_url", ""),
                "dates": r.get("dates", ""), "ages": r.get("ages", ""),
                "price": r.get("price", ""), "verdict": r.get("verdict", ""),
                "geo_town": town, "geo_state": "MA",
            })
            add(row)

    # Verified pipeline output: <town>/phase_p/all_verified.csv
    for p in data_dir.glob("*/phase_p/all_verified.csv"):
        town = _unslug(p.parts[-3])
        for r in _read_csv(p):
            row = _base_row("pipeline", town)
            row.update({
                "name": r.get("name", ""), "platform": r.get("platform", "") or "pipeline",
                "register_url": r.get("register_url", ""), "info_url": r.get("info_url", ""),
                "dates": r.get("dates", ""), "ages": r.get("ages", ""),
                "price": r.get("price", ""), "verdict": r.get("parent_verdict", ""),
                "geo_town": town, "geo_state": "MA",
            })
            add(row)

    # Gap-fill new sessions: <town>/phase_gap/new_sessions.csv
    for p in data_dir.glob("*/phase_gap/new_sessions.csv"):
        town = _unslug(p.parts[-3])
        for r in _read_csv(p):
            row = _base_row("gap", town)
            row.update({
                "name": r.get("name", ""), "platform": r.get("platform", "") or "gap",
                "register_url": r.get("register_url", ""), "info_url": r.get("info_url", ""),
                "dates": r.get("dates", ""), "ages": r.get("ages", ""), "price": r.get("price", ""),
                "geo_town": town, "geo_state": "MA",
            })
            add(row)

    # Part D (hubs + US Sports Camps): part_d/part_d_ma_camps.csv
    pd_csv = data_dir / "part_d" / "part_d_ma_camps.csv"
    if pd_csv.exists():
        for r in _read_csv(pd_csv):
            serving = [t for t in (r.get("serving_towns", "") or "").split(";") if t]
            row = _base_row("part_d", serving[0] if serving else "")
            row.update({
                "name": r.get("name", ""), "platform": r.get("platform", ""),
                "register_url": r.get("register_url", ""), "info_url": r.get("info_url", ""),
                "dates": r.get("dates", ""), "start_date": r.get("start_date", ""),
                "ages": r.get("ages", ""), "price": r.get("price", ""),
                "geo_town": r.get("geo_town", ""), "geo_city": r.get("geo_city", ""),
                "geo_state": r.get("geo_state", "") or "MA", "geo_zip": r.get("geo_zip", ""),
                "serving_towns": serving,
                "discovered_via": [v for v in (r.get("discovered_via", "") or "").split(";") if v],
            })
            add(row)

    # Fill start_date from dates where missing.
    for row in raw:
        if not row.get("start_date") and row.get("dates"):
            dt = parse_start_date(row["dates"], default_year=2026)
            if dt:
                row["start_date"] = dt.isoformat()

    deduped, removed = dedupe_sessions(raw)
    logger.info("merge: %d raw -> %d unique (%d collapsed)", len(raw), len(deduped), removed)

    # Final geo tag pass for any row carrying a venue.
    for row in deduped:
        if not row.get("geo_state"):
            tagged = geo_tag(row)
            row["geo_state"] = tagged.get("geo_state", "")
            row["geo_town"] = row.get("geo_town") or tagged.get("geo_town", "")
        row.setdefault("session_uid", "")
    return deduped


# --------------------------------------------------------------------------- #
# Archive: relocate old clutter, keep the essentials
# --------------------------------------------------------------------------- #
# Kept in place under data/: committed baselines/fixtures, cross-run hub
# snapshots, the shared engine fetch cache, and tracked index files.
KEEP_IN_DATA = {"_baseline", "_baseline_v2", "_fixtures", "_snapshots", "cache",
                "README.txt", "junk_audit.csv"}


def archive_clutter(
    *,
    repo_root: Path | None = None,
    archive_root: Path | None = None,
    dry_run: bool = False,
    ts: str | None = None,
) -> dict:
    """Move old run clutter into archive/<ts>/ (reversible). Keeps essentials.

    Moves: every data/* except KEEP_IN_DATA, all of logs/*, and trash/.
    Leaves: data/_baseline, _fixtures, _snapshots, cache, README.txt,
    junk_audit.csv; and pilot/ + pictures/ (untouched — say so).
    """
    import shutil

    repo_root = repo_root or REPO_ROOT
    archive_root = archive_root or (repo_root / "archive")
    ts = ts or _now_ts()
    dest = archive_root / ts
    moved: list[str] = []

    def _move(src: Path, rel: str) -> None:
        moved.append(rel)
        if dry_run:
            return
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(target))

    data = repo_root / "data"
    if data.is_dir():
        for item in sorted(data.iterdir()):
            if item.name in KEEP_IN_DATA:
                continue
            _move(item, f"data/{item.name}")

    logs = repo_root / "logs"
    if logs.is_dir():
        for item in sorted(logs.iterdir()):
            _move(item, f"logs/{item.name}")

    trash = repo_root / "trash"
    if trash.is_dir():
        _move(trash, "trash")

    return {"dest": str(dest), "moved": moved, "dry_run": dry_run, "kept_in_data": sorted(KEEP_IN_DATA)}


def write_merged(rows: list[dict], run_dir: Path) -> tuple[Path, Path]:
    import csv

    csv_path = run_dir / "all_camps.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=UNIFIED_FIELDS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            out = {k: r.get(k, "") for k in UNIFIED_FIELDS}
            out["serving_towns"] = ";".join(r.get("serving_towns", []) or [])
            out["discovered_via"] = ";".join(r.get("discovered_via", []) or [])
            w.writerow(out)

    txt_path = run_dir / "all_camps.txt"
    by_town: dict[str, list[dict]] = {}
    for r in rows:
        by_town.setdefault(r.get("geo_town") or r.get("town") or "Unknown", []).append(r)
    lines = [f"UNIFIED MA CAMP CATALOG — {len(rows)} camps", "=" * 60, ""]
    by_src: dict[str, int] = {}
    for r in rows:
        by_src[r["source"]] = by_src.get(r["source"], 0) + 1
    lines.append("By source: " + ", ".join(f"{k}={v}" for k, v in sorted(by_src.items())))
    lines.append("")
    for town in sorted(by_town):
        camps = by_town[town]
        lines.append(f"{town}  ({len(camps)})")
        lines.append("-" * 50)
        for r in camps:
            tags = "/".join(r.get("discovered_via", []) or [r.get("platform", "")])
            lines.append(f"  - {r.get('name', '')[:60]}  [{tags}]")
            meta = " ".join(p for p in (r.get("dates", ""), f"Ages {r['ages']}" if r.get("ages") else "", r.get("price", "")) if p)
            if meta:
                lines.append(f"      {meta}")
            if r.get("register_url"):
                lines.append(f"      {r['register_url']}")
        lines.append("")
    txt_path.write_text("\n".join(lines), encoding="utf-8")
    return csv_path, txt_path
