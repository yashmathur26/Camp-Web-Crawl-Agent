"""Append-only CSV audit log for Phase B harvest events."""

import csv
from datetime import datetime, timezone
from pathlib import Path

ACTIVITY_COLUMNS = [
    "timestamp",
    "event",
    "town",
    "source_kind",
    "source_url",
    "url",
    "link_text",
    "source_type",
    "status",
    "detail",
    "pages",
    "links_found",
    "rule_kept",
    "llm_kept",
    "llm_rejected",
    "added",
]

_path: Path | None = None
_context: dict[str, str] = {}


def init(path: str | Path) -> Path:
    global _path
    _path = Path(path)
    _path.parent.mkdir(parents=True, exist_ok=True)
    if not _path.exists() or _path.stat().st_size == 0:
        with open(_path, "w", encoding="utf-8", newline="") as f:
            csv.DictWriter(f, fieldnames=ACTIVITY_COLUMNS).writeheader()
    return _path


def set_context(
    *,
    town: str = "",
    source_kind: str = "",
    source_url: str = "",
) -> None:
    if town:
        _context["town"] = town
    if source_kind:
        _context["source_kind"] = source_kind
    if source_url:
        _context["source_url"] = source_url


def record(
    event: str,
    *,
    town: str = "",
    source_kind: str = "",
    source_url: str = "",
    url: str = "",
    link_text: str = "",
    source_type: str = "",
    status: str = "",
    detail: str = "",
    pages: int | str = "",
    links_found: int | str = "",
    rule_kept: int | str = "",
    llm_kept: int | str = "",
    llm_rejected: int | str = "",
    added: int | str = "",
) -> None:
    if _path is None:
        return
    row = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event,
        "town": town or _context.get("town", ""),
        "source_kind": source_kind or _context.get("source_kind", ""),
        "source_url": source_url or _context.get("source_url", ""),
        "url": url,
        "link_text": (link_text or "")[:200],
        "source_type": source_type,
        "status": status,
        "detail": (detail or "")[:500],
        "pages": pages,
        "links_found": links_found,
        "rule_kept": rule_kept,
        "llm_kept": llm_kept,
        "llm_rejected": llm_rejected,
        "added": added,
    }
    with open(_path, "a", encoding="utf-8", newline="") as f:
        csv.DictWriter(f, fieldnames=ACTIVITY_COLUMNS).writerow(row)
