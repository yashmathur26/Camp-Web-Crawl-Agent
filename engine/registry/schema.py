"""Registry YAML schema + loader (plan §4). The registry is the engine's input:
a hand-curated list of (vendor, org_id) providers per town. The proposer
(Phase 6) writes *.proposals.yaml; humans promote entries into towns/<town>.yaml.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

TOWNS_DIR = Path(
    os.environ.get(
        "FIREFLY_REGISTRY_DIR",
        str(Path(__file__).resolve().parent / "towns"),
    )
)

KNOWN_VENDORS = (
    "webtrac", "myrec", "active", "sawyer", "campbrain", "enrollsy", "daxko",
    "communityed", "recdesk", "civicrec", "communitypass", "ultracamp", "viking",
    "unknown",
)


class RegistryError(ValueError):
    """Malformed registry file — message names the file and the exact problem."""


@dataclass
class RegistryEntry:
    name: str
    host: str
    seed: str
    vendor: str = "unknown"
    org_id: str = ""
    aliases: list[str] = field(default_factory=list)
    notes: str = ""


@dataclass
class TownRegistry:
    town: str
    state: str
    providers: list[RegistryEntry]


def _require(d: dict, key: str, ctx: str, path: Path) -> object:
    if key not in d or d[key] in (None, ""):
        raise RegistryError(f"{path}: {ctx}: missing required field '{key}'")
    return d[key]


def load_registry(path: Path | str) -> TownRegistry:
    path = Path(path)
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise RegistryError(f"{path}: invalid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise RegistryError(f"{path}: top level must be a mapping")

    town = str(_require(data, "town", "top level", path))
    state = str(_require(data, "state", "top level", path))
    raw_providers = data.get("providers")
    if not isinstance(raw_providers, list) or not raw_providers:
        raise RegistryError(f"{path}: 'providers' must be a non-empty list")

    entries: list[RegistryEntry] = []
    seen_hosts: set[str] = set()
    for i, raw in enumerate(raw_providers):
        ctx = f"providers[{i}]"
        if not isinstance(raw, dict):
            raise RegistryError(f"{path}: {ctx}: must be a mapping")
        name = str(_require(raw, "name", ctx, path))
        host = str(_require(raw, "host", ctx, path)).lower()
        seed = str(_require(raw, "seed", ctx, path))
        vendor = str(raw.get("vendor", "unknown")).lower()
        if vendor not in KNOWN_VENDORS:
            raise RegistryError(
                f"{path}: {ctx} ({name}): unknown vendor '{vendor}'; "
                f"use one of {KNOWN_VENDORS}"
            )
        if not seed.startswith(("http://", "https://")):
            raise RegistryError(f"{path}: {ctx} ({name}): seed must be an absolute URL")
        aliases = raw.get("aliases") or []
        if not isinstance(aliases, list) or not all(isinstance(a, str) for a in aliases):
            raise RegistryError(f"{path}: {ctx} ({name}): aliases must be a list of strings")
        if host in seen_hosts:
            raise RegistryError(f"{path}: {ctx} ({name}): duplicate host '{host}'")
        seen_hosts.add(host)
        entries.append(
            RegistryEntry(
                name=name, host=host, seed=seed, vendor=vendor,
                org_id=str(raw.get("org_id", "") or ""),
                aliases=[a.lower() for a in aliases],
                notes=str(raw.get("notes", "") or ""),
            )
        )
    return TownRegistry(town=town, state=state, providers=entries)


def load_town(town: str) -> TownRegistry:
    return load_registry(TOWNS_DIR / f"{town.lower()}.yaml")
