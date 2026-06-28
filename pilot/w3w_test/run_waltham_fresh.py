#!/usr/bin/env python3
"""Fresh, from-scratch Waltham run with detailed per-phase logging and a
LIVE-updating output CSV + readable TXT in pilot/w3w_test/waltham_run/.

- Wipes prior pilot state (forgets all previously-found camps).
- Runs Phase A (budgeted) -> Phase B harvest -> Engine v3 -> Phase C gap-fill,
  logging every phase to waltham_run/run.log (line-buffered, tail-able live).
- A background thread re-exports waltham_camps.csv + waltham_camps.txt every
  ~15s from the engine checkpoint + Phase C output, so the files fill in as the
  engine confirms each provider's camps (not just at the end).

Usage:  ./venv/bin/python pilot/w3w_test/run_waltham_fresh.py
"""

from __future__ import annotations

import csv
import json
import logging
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import run_pilot as rp  # sibling module; sets FIREFLY_* env on import

TOWN = "Waltham"
PILOT_ROOT = rp.PILOT_ROOT
OUT_DIR = PILOT_ROOT / "waltham_run"
ENGINE_CKPT = PILOT_ROOT / "data" / "waltham" / "engine" / "checkpoint.json"
GAP_CSV = PILOT_ROOT / "data" / "waltham" / "phase_gap" / "new_sessions.csv"
CSV_OUT = OUT_DIR / "waltham_camps.csv"
TXT_OUT = OUT_DIR / "waltham_camps.txt"
LOG_OUT = OUT_DIR / "run.log"

COLUMNS = ["name", "dates", "ages", "price", "verdict", "source",
           "register_url", "info_url", "host"]


def _host(url: str) -> str:
    h = urlparse(url or "").netloc.lower()
    return h[4:] if h.startswith("www.") else h


def _collect_rows() -> list[dict]:
    """Current camps from the engine checkpoint (per-provider, live) + Phase C."""
    rows: list[dict] = []
    seen: set[str] = set()

    if ENGINE_CKPT.exists():
        try:
            ckpt = json.loads(ENGINE_CKPT.read_text() or "{}")
        except (json.JSONDecodeError, ValueError):
            ckpt = {}  # mid-write; try again next tick
        for res in ckpt.values():
            for prog in res.get("programs", []):
                for s in prog.get("sessions", []):
                    url = s.get("register_url") or s.get("info_url") or ""
                    key = (s.get("name", ""), url)
                    if key in seen:
                        continue
                    seen.add(key)
                    rows.append({
                        "name": s.get("name", ""), "dates": s.get("dates", ""),
                        "ages": s.get("ages", ""), "price": s.get("price", ""),
                        "verdict": s.get("verdict", ""), "source": "engine",
                        "register_url": s.get("register_url", ""),
                        "info_url": s.get("info_url", ""),
                        "host": _host(s.get("info_url") or s.get("register_url")),
                    })

    if GAP_CSV.exists():
        try:
            with open(GAP_CSV, encoding="utf-8", newline="") as f:
                for r in csv.DictReader(f):
                    url = r.get("register_url") or r.get("info_url") or ""
                    key = (r.get("name", ""), url)
                    if key in seen:
                        continue
                    seen.add(key)
                    rows.append({
                        "name": r.get("name", ""), "dates": r.get("dates", ""),
                        "ages": r.get("ages", ""), "price": r.get("price", ""),
                        "verdict": r.get("parent_verdict", ""), "source": "phase_c",
                        "register_url": r.get("register_url", ""),
                        "info_url": r.get("info_url", ""),
                        "host": _host(r.get("info_url") or r.get("register_url")),
                    })
        except (OSError, csv.Error):
            pass  # mid-write; try again next tick
    rows.sort(key=lambda x: (x["host"], x["name"]))
    return rows


def _export(phase_label: str = "") -> int:
    rows = _collect_rows()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(CSV_OUT, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)

    by_host: dict[str, list[dict]] = {}
    for r in rows:
        by_host.setdefault(r["host"] or "(unknown)", []).append(r)
    lines = [
        "=" * 74,
        "WALTHAM SUMMER CAMPS — live export",
        "=" * 74,
        f"Updated: {time.strftime('%Y-%m-%d %H:%M:%S')}  |  phase: {phase_label or 'running'}",
        f"Total camps so far: {len(rows)}  (providers: {len(by_host)})",
        "",
    ]
    for host in sorted(by_host):
        items = by_host[host]
        lines.append(f"▶ {host}  ({len(items)})")
        for r in items:
            meta = " | ".join(x for x in (r["dates"], r["ages"], r["price"]) if x)
            lines.append(f"   • {r['name']}" + (f"  [{r['verdict']}/{r['source']}]" if r['verdict'] else f"  [{r['source']}]"))
            if meta:
                lines.append(f"       {meta}")
            lines.append(f"       {r['register_url'] or r['info_url']}")
        lines.append("")
    TXT_OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(rows)


_stop = threading.Event()


def _watcher() -> None:
    while not _stop.is_set():
        try:
            n = _export()
            logging.getLogger("live").info("live export → %d camps so far", n)
        except Exception as exc:  # noqa: BLE001
            logging.getLogger("live").warning("live export hiccup: %s", exc)
        _stop.wait(15)


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)
    fh = logging.FileHandler(LOG_OUT, mode="w")
    sh = logging.StreamHandler()
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s", "%H:%M:%S")
    for h in (fh, sh):
        h.setFormatter(fmt)
        root.addHandler(h)

    t0 = time.time()
    logging.info("================= FRESH WALTHAM RUN =================")
    logging.info("Resetting all prior pilot state (forgetting previous camps)...")
    rp._reset_pilot_state()
    _export("reset")

    watcher = threading.Thread(target=_watcher, daemon=True)
    watcher.start()

    logging.info("Starting pipeline: Phase A (budgeted) -> B -> Engine v3 -> Phase C")
    result = rp.run_town_pipeline(
        TOWN, gap_rounds=1, gap_searches=-1,  # gap_searches=-1 -> auto population budget
        max_registry_providers=35,
    )
    logging.info("Pipeline phases summary: %s", json.dumps(result.get("phases", {}), default=str)[:2000])

    _stop.set()
    watcher.join(timeout=5)

    # Final authoritative export from the written CSVs (engine sessions + gap).
    eng = rp._read_engine_sessions(TOWN)
    gap = rp._read_gap_sessions(TOWN)
    n = _export("DONE")

    # Institution (college/school) camps file in the same folder.
    try:
        from phase_c.institution_output import write_institution_camps_txt
        inst_rows = [{**r, "town": TOWN} for r in (eng + gap)]
        write_institution_camps_txt(TOWN, inst_rows, OUT_DIR / "waltham_institution_camps.txt")
    except Exception as exc:  # noqa: BLE001
        logging.warning("institution export skipped: %s", exc)

    mins = (time.time() - t0) / 60
    logging.info("================= DONE in %.1f min — %d camps =================", mins, n)
    logging.info("CSV: %s", CSV_OUT)
    logging.info("TXT: %s", TXT_OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
