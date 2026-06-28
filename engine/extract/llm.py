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
navigation/menu labels; empty list is valid.
Do NOT extract any of these (they are not youth summer camps): job/counselor
postings or hiring pages; recurring lessons, clinics, open-gym/open-play or
drop-in activities; year-round childcare / early-learning / preschool that runs
all year; school-district service pages (ESL, farm-to-school, transition
services, enrollment/change-of-address); resource/PDF/newsletter/blog pages.
For ages, copy only a real range the text states (e.g. "5-12", "grades 1-3");
never output a bare "0", "1", "2", or a zero-padded number — leave ages "" if
unsure. For dates, copy a real session date range; leave "" if none is stated."""


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


# --------------------------------------------------------------------------- #
# Phase 4 — page-role verifier + weak-name normalizer (same ONE call site, R3).
# Perception only: classify/format from CONTENT, never the URL. Fail open (None).
# --------------------------------------------------------------------------- #

def _chat(system: str, user: str, *, purpose: str) -> str | None:
    """One Ollama chat round, JSON-forced, temp 0. Returns content or None
    (fail open) on any transport error."""
    base = ENGINE["ollama_base_url"].rstrip("/")
    try:
        resp = requests.post(
            f"{base}/api/chat",
            json={"model": ENGINE["ollama_model"],
                  "messages": [{"role": "system", "content": system},
                               {"role": "user", "content": user}],
                  "stream": False, "format": "json", "options": {"temperature": 0}},
            timeout=90,
        )
        resp.raise_for_status()
        return resp.json().get("message", {}).get("content", "")
    except requests.RequestException as exc:
        logger.warning("llm %s failed: %s", purpose, exc)
        return None


_ROLE_SYSTEM = """You classify ONE web page's role for a youth summer camp directory.
Read the page text and reply with ONLY JSON: {"role":"registration"|"info"|"peripheral"}.
registration = the page to sign up / enroll / book / add to cart for a specific camp.
info = describes a specific camp (dates, ages, activities) but is not the signup page.
peripheral = about/history/staff/alumni/news/policies/directions — not a specific camp.
Decide from the page CONTENT only; you are never given the URL."""

_ROLES = {"registration", "info", "peripheral"}


def verify_page_role(page_text: str, *, title: str = "", h1: str = "") -> str | None:
    """Content-based role for the RESIDUE Phase 2/3 couldn't resolve. Returns one
    of registration|info|peripheral, or None when the text is too thin to answer
    (no call) or the model fails (fail open → caller routes to review)."""
    text = (page_text or "").strip()
    if len(text) < MIN_INPUT_CHARS:
        return None  # not answerable — no call; caller flags thin → review
    user = json.dumps({"title": title, "h1": h1, "page_text": text[:6000]})
    content = _chat(_ROLE_SYSTEM, user, purpose="role")
    if content is None:
        return None
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", content)
        data = json.loads(m.group()) if m else {}
    role = str((data or {}).get("role") or "").strip().lower()
    logger.info("llm role in=%d chars -> %s", len(text), role or "unparseable")
    return role if role in _ROLES else None


_NAME_SYSTEM = """You clean ONE messy program/camp NAME into a short human title.
Reply with ONLY JSON: {"name":"..."}. Keep it faithful — do NOT invent words and
do NOT add an organization/provider. Strip file extensions, slugs and stray
punctuation. If the input is not a real program name (navigation/file/boilerplate),
return {"name":""}."""


def normalize_name_llm(raw_name: str) -> str | None:
    """Format a weak-source (slug/link/llm) name into a clean one. Returns the
    cleaned name, "" when the model judges it not a real name, or None on failure
    (fail open → caller keeps the original). Never call on clean adapter rows."""
    name = (raw_name or "").strip()
    if not name:
        return None
    content = _chat(_NAME_SYSTEM, json.dumps({"raw_name": name}), purpose="name")
    if content is None:
        return None
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", content)
        data = json.loads(m.group()) if m else {}
    cleaned = str((data or {}).get("name") or "").strip()
    logger.info("llm name %r -> %r", name, cleaned)
    return cleaned
