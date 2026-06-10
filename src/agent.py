"""Autonomous Ollama agent: observe → plan → act → reflect → remember."""

import asyncio
import json
import logging
from typing import Any

from config.keywords import PHASE_A_KEYWORDS
from config.prompts import ORCHESTRATOR_SYSTEM
from config.settings import SETTINGS, STATE
from config.towns import TOWNS
from src.agent_memory import memory_summary
from src.agent_tools import (
    tool_crawl,
    tool_get_status,
    tool_list_uncrawled_candidates,
    tool_memory_context,
    tool_reflect,
    tool_save_candidates,
    tool_search,
)
from src.llm import OllamaError, chat, is_available
from src.store import count_camp_links

logger = logging.getLogger(__name__)


def _build_observation(step: int, search_limit: int | None) -> dict[str, Any]:
    status = tool_get_status()
    pending = tool_list_uncrawled_candidates(15)
    mem = tool_memory_context()
    return {
        "step": step,
        "camp_links": status["camp_links"],
        "target": status["target"],
        "search_limit": search_limit,
        "pending_crawls": [
            {"url": p["url"], "town": p.get("town", ""), "preferred": p.get("preferred")}
            for p in pending
        ],
        "memory_summary": memory_summary(),
        "top_queries": sorted(
            mem.get("query_scores", {}).items(),
            key=lambda x: x[1].get("avg_yield", 0),
            reverse=True,
        )[:8],
        "sample_keywords": PHASE_A_KEYWORDS[:10],
        "towns": TOWNS[:10],
        "state": STATE,
    }


def _plan(observation: dict[str, Any]) -> dict[str, Any]:
    user = json.dumps(observation)
    return chat(ORCHESTRATOR_SYSTEM, user)


async def run_agent(*, search_limit: int | None = None, dry_run: bool = False) -> dict[str, Any]:
    if dry_run:
        obs = _build_observation(0, search_limit)
        print("\n=== AGENT DRY RUN ===")
        print(json.dumps(obs, indent=2))
        print(f"\nWould run up to {SETTINGS['agent_max_steps']} steps with Ollama.")
        return {"steps": 0, "camp_links": count_camp_links()}

    if not is_available():
        raise OllamaError(
            f"Ollama not running at {SETTINGS['ollama_base_url']}. "
            f"Run: ollama serve && ollama pull {SETTINGS['ollama_model']}"
        )

    steps = 0
    searches_done = 0

    while steps < SETTINGS["agent_max_steps"]:
        if count_camp_links() >= SETTINGS["target_count"]:
            logger.info("Target count reached")
            break

        if search_limit is not None and searches_done >= search_limit:
            logger.info("Search limit reached")
            break

        observation = _build_observation(steps, search_limit)
        try:
            plan = _plan(observation)
        except OllamaError as exc:
            logger.error("Planning failed: %s", exc)
            break

        action = plan.get("action", "stop")
        args = plan.get("args") or {}
        logger.info("Step %d thought: %s", steps, plan.get("thought", ""))
        logger.info("Step %d action: %s %s", steps, action, args)

        if action == "stop":
            break

        if action == "crawl_page":
            url = args.get("url", "")
            town = args.get("town", "")
            if not url and observation["pending_crawls"]:
                first = observation["pending_crawls"][0]
                url, town = first["url"], first.get("town", "")
            outcome = await tool_crawl(url, town)
            tool_reflect("crawl_page", {"url": url, "town": town}, outcome)
            if outcome.get("added", 0) > 0:
                from src.run import _load_candidates, _save_candidates

                candidates = _load_candidates()
                for i, c in enumerate(candidates):
                    if c.get("url") == url:
                        candidates[i]["crawled"] = "true"
                        break
                _save_candidates(candidates)

        elif action == "search":
            query = args.get("query", "")
            town = args.get("town", "")
            keyword = args.get("keyword", "")
            if not query:
                if not town:
                    town = TOWNS[steps % len(TOWNS)]
                keyword = keyword or PHASE_A_KEYWORDS[steps % len(PHASE_A_KEYWORDS)]
                query = f"{keyword} {town}, {STATE}"

            outcome = tool_search(query, town, keyword)
            searches_done += 0 if outcome.get("skipped") else 1
            saved = 0
            if outcome.get("kept"):
                for item in outcome["kept"]:
                    item["town"] = town
                    item["keyword"] = keyword
                saved = tool_save_candidates(outcome["kept"])
            outcome["saved"] = saved
            tool_reflect("search", {"query": query, "town": town}, outcome)

            pending = tool_list_uncrawled_candidates(1)
            if pending and saved > 0:
                crawl_out = await tool_crawl(pending[0]["url"], pending[0].get("town", ""))
                tool_reflect(
                    "crawl_page",
                    {"url": pending[0]["url"], "town": pending[0].get("town", "")},
                    crawl_out,
                )
        else:
            logger.warning("Unknown action %s, stopping", action)
            break

        steps += 1

    return {
        "steps": steps,
        "searches_done": searches_done,
        "camp_links": count_camp_links(),
        "memory": memory_summary(),
    }
