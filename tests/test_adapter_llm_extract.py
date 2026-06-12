"""Task 3.1: LLM extraction adapter — gates, cache, firecrawl queue."""

from __future__ import annotations

import asyncio
import csv
import json
from pathlib import Path

import src.adapter_llm_extract as ax
from src.adapter_llm_extract import extract_programs_llm

SEED = "https://customcamp.org/summer"
PAGE_TEXT = (
    "Custom Camp runs youth summer programs. Register at "
    "https://customcamp.org/register. Sessions run July 6-31."
)


def _canned_programs():
    return [
        {
            "name": "Custom Adventure Camp",
            "dates": "July 6 - July 31",
            "ages": "6-12",
            "price": "$400",
            "register_url": "https://customcamp.org/register",
            "confidence": 0.9,
        },
        {
            "name": "Low Confidence Camp",
            "dates": "",
            "ages": "",
            "price": "",
            "register_url": "https://customcamp.org/other",
            "confidence": 0.3,
        },
        {
            "name": "Offsite Camp",
            "dates": "July 6-10",
            "ages": "",
            "price": "",
            "register_url": "https://totally-unrelated.io/signup",
            "confidence": 0.95,
        },
    ]


def _setup(monkeypatch, tmp_path, chat_calls):
    monkeypatch.setattr(ax, "CACHE_PATH", tmp_path / "llm_extract.json")
    monkeypatch.setattr(ax, "FIRECRAWL_QUEUE_PATH", tmp_path / "firecrawl_queue.csv")

    import src.llm as llm

    monkeypatch.setattr(llm, "is_available", lambda: True)

    def fake_chat(system, user, **kw):
        chat_calls.append(json.loads(user)["page_url"])
        return {"programs": _canned_programs()}

    monkeypatch.setattr(llm, "chat", fake_chat)

    import src.platforms as platforms

    async def fake_fetch(url, tries=3, *, caller="", wait_until=None, kind=""):
        if url == SEED:
            return PAGE_TEXT, [
                {"url": "https://customcamp.org/summer/schedule", "text": "Camp Schedule"},
                {"url": "https://customcamp.org/about", "text": "About"},
            ]
        return "Schedule page text with camps.", []

    monkeypatch.setattr(platforms, "_fetch", fake_fetch)


def test_confidence_and_same_host_gates(monkeypatch, tmp_path):
    chat_calls: list[str] = []
    _setup(monkeypatch, tmp_path, chat_calls)
    sessions = asyncio.run(extract_programs_llm(SEED, town="Lexington"))
    # 3 canned programs per page, but only the confident same-host one survives
    names = {s["name"] for s in sessions}
    assert names == {"Custom Adventure Camp"}
    s = sessions[0]
    assert s["platform"] == "llm_extract"
    # concrete date range -> granularity session
    assert s["granularity"] == "session"


def test_cache_hit_second_call_makes_zero_chat_calls(monkeypatch, tmp_path):
    chat_calls: list[str] = []
    _setup(monkeypatch, tmp_path, chat_calls)
    asyncio.run(extract_programs_llm(SEED, town="Lexington"))
    first = len(chat_calls)
    assert first >= 1
    asyncio.run(extract_programs_llm(SEED, town="Lexington"))
    assert len(chat_calls) == first  # all pages served from cache


def test_zero_yield_host_queued_for_firecrawl(monkeypatch, tmp_path):
    chat_calls: list[str] = []
    _setup(monkeypatch, tmp_path, chat_calls)

    import src.llm as llm

    monkeypatch.setattr(llm, "chat", lambda *a, **k: {"programs": []})
    sessions = asyncio.run(extract_programs_llm(SEED, town="Lexington"))
    assert sessions == []
    queue = tmp_path / "firecrawl_queue.csv"
    assert queue.exists()
    with open(queue, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["host"] == "customcamp.org"
    assert rows[0]["reason"] == "llm_no_programs"

    # dedupe on host: a second failure doesn't append another row
    asyncio.run(extract_programs_llm(SEED, town="Lexington"))
    with open(queue, newline="", encoding="utf-8") as f:
        assert len(list(csv.DictReader(f))) == 1


def test_ollama_down_returns_empty_and_queues(monkeypatch, tmp_path):
    monkeypatch.setattr(ax, "CACHE_PATH", tmp_path / "llm_extract.json")
    monkeypatch.setattr(ax, "FIRECRAWL_QUEUE_PATH", tmp_path / "q.csv")

    import src.llm as llm

    monkeypatch.setattr(llm, "is_available", lambda: False)
    sessions = asyncio.run(extract_programs_llm(SEED, town="Lexington"))
    assert sessions == []
    with open(tmp_path / "q.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["reason"] == "ollama_unavailable"


def test_program_without_dates_gets_program_granularity(monkeypatch, tmp_path):
    chat_calls: list[str] = []
    _setup(monkeypatch, tmp_path, chat_calls)

    import src.llm as llm

    monkeypatch.setattr(
        llm,
        "chat",
        lambda *a, **k: {
            "programs": [
                {
                    "name": "Dateless Summer Program",
                    "dates": "",
                    "ages": "",
                    "price": "",
                    "register_url": "https://customcamp.org/register",
                    "confidence": 0.8,
                }
            ]
        },
    )
    sessions = asyncio.run(extract_programs_llm(SEED, town="Lexington"))
    assert sessions[0]["granularity"] == "program"
