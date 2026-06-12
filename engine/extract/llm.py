"""Extraction-only LLM wrapper (task 5.1, R3). The ONLY module that calls the
model. Perception only: structure programs from rendered text. Never traversal,
never keep/drop. Hard >=400-char input guard; JSON-repair + one retry; None on
failure (caller fails open)."""

from __future__ import annotations

import json
import logging
import re

import requests

from config_engine import ENGINE

logger = logging.getLogger("engine.llm")

MIN_INPUT_CHARS = 400

_SYSTEM = """You extract youth summer program records from one web page's text.
Return ONLY JSON: {"programs":[{"name":"...","dates":"","ages":"","price":""}]}
Rules: only programs actually described in the text (never invent); skip
navigation/menu labels; empty list is valid."""


def _parse(content: str) -> list[dict] | None:
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", content)
        if not m:
            return None
        try:
            data = json.loads(m.group())
        except json.JSONDecodeError:
            return None
    progs = data.get("programs") if isinstance(data, dict) else None
    if not isinstance(progs, list):
        return None
    out = []
    for p in progs:
        if isinstance(p, dict) and str(p.get("name") or "").strip():
            out.append({k: str(p.get(k) or "").strip() for k in ("name", "dates", "ages", "price")})
    return out


def extract_programs(page_text: str, url: str, town: str) -> list[dict] | None:
    """Returns extracted program dicts, or None on model failure (fail open)."""
    if len((page_text or "").strip()) < MIN_INPUT_CHARS:
        raise ValueError(
            f"R3.2: refusing LLM extraction on {len((page_text or '').strip())} chars (<{MIN_INPUT_CHARS})"
        )
    user = json.dumps({"url": url, "town": town, "page_text": page_text[:6000]})
    base = ENGINE["ollama_base_url"].rstrip("/")
    for attempt, system in enumerate(
        (_SYSTEM, _SYSTEM + "\nIMPORTANT: respond with a single valid JSON object only.")
    ):
        try:
            resp = requests.post(
                f"{base}/api/chat",
                json={"model": ENGINE["ollama_model"],
                      "messages": [{"role": "system", "content": system},
                                   {"role": "user", "content": user}],
                      "stream": False, "format": "json",
                      "options": {"temperature": 0}},
                timeout=90,
            )
            resp.raise_for_status()
            content = resp.json().get("message", {}).get("content", "")
            parsed = _parse(content)
            logger.info("llm extract url=%s in=%d chars attempt=%d -> %s",
                        url, len(page_text), attempt + 1,
                        f"{len(parsed)} programs" if parsed is not None else "unparseable")
            if parsed is not None:
                return parsed
        except requests.RequestException as exc:
            logger.warning("llm extract failed (%s): %s", url, exc)
            return None
    return None
