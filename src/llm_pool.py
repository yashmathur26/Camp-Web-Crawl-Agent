"""Parallel Ollama batch executor for camp-page classification."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from config.settings import SETTINGS


@dataclass
class LLMMetrics:
    fast_calls: int = 0
    verify_calls: int = 0
    skipped_rules: int = 0
    cache_hits: int = 0
    rejected_cap: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "llm_fast_calls": self.fast_calls,
            "llm_verify_calls": self.verify_calls,
            "llm_skipped_rules": self.skipped_rules,
            "llm_cache_hits": self.cache_hits,
            "llm_rejected_cap": self.rejected_cap,
        }


_METRICS = LLMMetrics()


def get_metrics() -> LLMMetrics:
    return _METRICS


def reset_metrics() -> None:
    global _METRICS
    _METRICS = LLMMetrics()


async def run_batch(
    items: list[tuple],
    fn,
    *,
    concurrency: int | None = None,
) -> list:
    if not items:
        return []
    sem = asyncio.Semaphore(concurrency or int(SETTINGS.get("ollama_classify_concurrency", 3)))

    async def one(item):
        async with sem:
            return await asyncio.to_thread(fn, item)

    return list(await asyncio.gather(*[one(a) for a in items]))
