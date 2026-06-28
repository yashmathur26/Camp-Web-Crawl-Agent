"""Ollama client for agent mode."""

import json
import logging
import re
from typing import Any

import requests

from config.settings import SETTINGS

logger = logging.getLogger(__name__)

_installed_models: set[str] | None = None


class OllamaError(Exception):
    pass


def list_installed_models(*, refresh: bool = False) -> set[str]:
    global _installed_models
    if _installed_models is not None and not refresh:
        return _installed_models
    base = SETTINGS["ollama_base_url"].rstrip("/")
    try:
        response = requests.get(f"{base}/api/tags", timeout=5)
        response.raise_for_status()
        names = {m.get("name", "") for m in response.json().get("models", [])}
        _installed_models = {n for n in names if n}
    except requests.RequestException:
        _installed_models = set()
    return _installed_models


def resolve_model(preferred: str | None) -> str:
    """Pick an installed Ollama model, falling back when *preferred* is missing."""
    model = preferred or SETTINGS["ollama_model"]
    installed = list_installed_models()
    if not installed:
        return model
    if model in installed:
        return model
    base = model.split(":")[0]
    base_match = _pick_base_match(base, installed)
    if base_match:
        if base_match != model:
            logger.info("Ollama model %s not installed; using %s", model, base_match)
        return base_match
    for fallback in (
        SETTINGS.get("ollama_fast_model"),
        "gemma3:4b",
        "gemma3:1b",
        SETTINGS.get("ollama_verify_model"),
        SETTINGS.get("ollama_filter_model"),
        SETTINGS["ollama_model"],
        "gemma3:12b",
        "llama3.2",          # legacy safety net
        "llama3.2:latest",
    ):
        if fallback and fallback in installed:
            if fallback != model:
                logger.info("Ollama model %s unavailable; using %s", model, fallback)
            return fallback
        if fallback:
            fb_match = _pick_base_match(fallback.split(":")[0], installed)
            if fb_match:
                if fb_match != model:
                    logger.info("Ollama model %s unavailable; using %s", model, fb_match)
                return fb_match
    return model


# Parameter-size tags we must never silently upgrade *to* when a bare base name
# (e.g. "llama3.2") was requested — "llama3.2" means the default 3B instruct
# model, not "llama3.2:1b".
_SIZE_TAG_RE = re.compile(r":\d+(?:\.\d+)?b$", re.I)


def _pick_base_match(base: str, installed: set[str]) -> str | None:
    """Deterministically choose an installed model whose base name == *base*.

    Set iteration order is hash-randomized per process, so the old
    `for name in installed: ...` returned `llama3.2:1b` or `llama3.2:latest`
    at random. Prefer `<base>:latest`, then any non-size-tagged variant, then
    a stable sorted fallback — so navigation never downgrades to a smaller
    param model by accident.
    """
    matches = sorted(n for n in installed if n.split(":")[0] == base)
    if not matches:
        return None
    latest = f"{base}:latest"
    if latest in matches:
        return latest
    non_size = [n for n in matches if not _SIZE_TAG_RE.search(n)]
    return (non_size or matches)[0]


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    raise OllamaError(f"Could not parse JSON from model output: {text[:200]}")


def _summarize_user(user: str) -> str:
    try:
        data = json.loads(user)
        if not isinstance(data, dict):
            return user[:160]
        parts: list[str] = []
        for key in ("url", "name", "link_text", "town_hint"):
            val = data.get(key)
            if val:
                parts.append(f"{key}={str(val)[:120]}")
        if data.get("page_text"):
            parts.append(f"page_text={len(str(data['page_text']))} chars")
        if data.get("text"):
            parts.append(f"text={len(str(data['text']))} chars")
        return "; ".join(parts) or user[:160]
    except (json.JSONDecodeError, TypeError):
        return user[:160]


def _log_ollama(
    *,
    purpose: str,
    model: str,
    user: str,
    response: dict[str, Any] | None = None,
    error: str = "",
) -> None:
    if not purpose:
        return
    try:
        from shared import session_log

        session_log.ollama_call(
            purpose=purpose,
            model=model,
            input_summary=_summarize_user(user),
            response=response,
            error=error,
        )
    except Exception:
        pass


def chat(
    system: str,
    user: str,
    *,
    model: str | None = None,
    temperature: float = 0.2,
    timeout: int = 120,
    num_predict: int | None = None,
    purpose: str = "",
) -> dict[str, Any]:
    base = SETTINGS["ollama_base_url"].rstrip("/")
    model_name = resolve_model(model or SETTINGS["ollama_model"])
    options: dict[str, Any] = {"temperature": temperature}
    if num_predict is not None:
        options["num_predict"] = num_predict
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "format": "json",
        # Keep the model resident between calls so we don't pay reload cost per page.
        "keep_alive": SETTINGS.get("ollama_keep_alive", "10m"),
        "options": options,
    }
    try:
        response = requests.post(
            f"{base}/api/chat",
            json=payload,
            timeout=timeout,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise OllamaError(
            f"Ollama unavailable at {base}. Run: ollama serve && ollama pull {model_name}"
        ) from exc

    data = response.json()
    content = data.get("message", {}).get("content", "")
    try:
        parsed = _extract_json(content)
        _log_ollama(purpose=purpose, model=model_name, user=user, response=parsed)
        return parsed
    except OllamaError as exc:
        _log_ollama(purpose=purpose, model=model_name, user=user, error=str(exc))
        if content and "Could not parse JSON" in str(exc):
            _log_ollama(
                purpose=f"{purpose}:raw" if purpose else "raw",
                model=model_name,
                user="(unparsed)",
                error=content[:500],
            )
        raise


def chat_with_repair(
    system: str,
    user: str,
    *,
    model: str | None = None,
    temperature: float = 0.2,
    timeout: int = 120,
    num_predict: int | None = None,
    purpose: str = "",
) -> dict[str, Any]:
    """`chat()` hardened for navigation/extraction: one JSON-repair retry.

    Rule 8 ("fail open on the model, not on the data"): when the model returns
    unparseable JSON, retry once at temperature 0 with an explicit "valid JSON
    only" nudge before giving up. Routes navigation to the larger instruct model
    (`ollama_verify_model`) by default — the 1B fast model is reserved for the
    binary classifier path elsewhere.
    """
    nav_model = model or SETTINGS.get("ollama_verify_model") or SETTINGS["ollama_model"]
    try:
        return chat(
            system,
            user,
            model=nav_model,
            temperature=temperature,
            timeout=timeout,
            num_predict=num_predict,
            purpose=purpose,
        )
    except OllamaError as exc:
        if "Could not parse JSON" not in str(exc):
            raise
        logger.warning("navigator LLM returned bad JSON (%s); retrying once", purpose or "chat")
        repair_system = (
            f"{system}\n\nIMPORTANT: Respond with a SINGLE valid JSON object and nothing "
            "else — no markdown fences, no commentary, no trailing commas."
        )
        return chat(
            repair_system,
            user,
            model=nav_model,
            temperature=0.0,
            timeout=timeout,
            num_predict=num_predict,
            purpose=f"{purpose}:repair" if purpose else "repair",
        )


def unload_model(model: str | None = None) -> None:
    """Tell Ollama to evict a model now (keep_alive: 0), freeing its RAM.

    On 16GB the W3W pilot kept gemma3:4b + gemma3:1b resident (~9GB workers
    each in the Jetsam log). Calling this between phases — or before loading a
    different model — keeps at most one model in memory."""
    base = SETTINGS["ollama_base_url"].rstrip("/")
    name = resolve_model(model or SETTINGS.get("ollama_model"))
    try:
        requests.post(
            f"{base}/api/chat",
            json={"model": name, "messages": [], "keep_alive": 0},
            timeout=10,
        )
        logger.info("Unloaded Ollama model: %s", name)
    except requests.RequestException as exc:
        logger.debug("unload_model(%s) failed (non-fatal): %s", name, exc)


def unload_all_models() -> None:
    """Evict every currently-loaded model (read from /api/ps)."""
    base = SETTINGS["ollama_base_url"].rstrip("/")
    try:
        resp = requests.get(f"{base}/api/ps", timeout=5)
        loaded = [m.get("name", "") for m in resp.json().get("models", [])]
    except requests.RequestException:
        loaded = []
    # Also try the configured roles in case /api/ps is unavailable.
    for name in set(loaded) | {
        SETTINGS.get("ollama_model"), SETTINGS.get("ollama_fast_model"),
        SETTINGS.get("ollama_verify_model"), SETTINGS.get("ollama_filter_model"),
    }:
        if name:
            unload_model(name)


def is_available() -> bool:
    base = SETTINGS["ollama_base_url"].rstrip("/")
    try:
        response = requests.get(f"{base}/api/tags", timeout=5)
        return response.status_code == 200
    except requests.RequestException:
        return False
