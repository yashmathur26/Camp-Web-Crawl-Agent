import csv
from datetime import datetime, timezone
from pathlib import Path

from src.cache import add_seen_urls, load_seen_urls
from src.data_layout import camp_links_csv
from src.link_quality import is_quality_camp_link
from src.urls import normalize_url

CAMP_LINKS_COLUMNS = [
    "url",
    "state",
    "town_hint",
    "source_type",
    "found_via",
    "found_on_page",
    "link_text",
    "status",
    "discovered_at",
]

DEFAULT_CAMP_LINKS_PATH = camp_links_csv()


def save_new_links(rows: list[dict], path: str | Path | None = None) -> int:
    output_path = Path(path) if path else DEFAULT_CAMP_LINKS_PATH
    output_path.parent.mkdir(parents=True, exist_ok=True)

    seen = load_seen_urls()
    new_rows: list[dict] = []
    now = datetime.now(timezone.utc).isoformat()

    for row in rows:
        normalized = normalize_url(row.get("url", ""))
        if not normalized or normalized in seen:
            continue
        if not is_quality_camp_link(normalized, row.get("link_text", "")):
            continue
        out = {col: row.get(col, "") for col in CAMP_LINKS_COLUMNS}
        out["url"] = normalized
        out["status"] = "new"
        if not out["discovered_at"]:
            out["discovered_at"] = now
        new_rows.append(out)
        seen.add(normalized)

    if not new_rows:
        return 0

    write_header = not output_path.exists() or output_path.stat().st_size == 0
    with open(output_path, "a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CAMP_LINKS_COLUMNS)
        if write_header:
            writer.writeheader()
        writer.writerows(new_rows)

    add_seen_urls(r["url"] for r in new_rows)

    from src.camp_outputs import write_camp_links_txt_from_csv

    write_camp_links_txt_from_csv(output_path)
    return len(new_rows)


def count_camp_links(path: str | Path | None = None) -> int:
    output_path = Path(path) if path else DEFAULT_CAMP_LINKS_PATH
    if not output_path.exists():
        return 0
    with open(output_path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return sum(1 for _ in reader)
