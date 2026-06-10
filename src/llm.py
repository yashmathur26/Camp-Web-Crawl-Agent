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
    for name in installed:
        if name.split(":")[0] == base:
            return name
    for fallback in (
        SETTINGS.get("ollama_fast_model"),
        "llama3.2:1b",
        SETTINGS.get("ollama_verify_model"),
        SETTINGS.get("ollama_filter_model"),
        SETTINGS["ollama_model"],
        "llama3.2",
        "llama3.2:latest",
    ):
        if fallback and fallback in installed:
            if fallback != model:
                logger.info("Ollama model %s unavailable; using %s", model, fallback)
            return fallback
        if fallback:
            fb_base = fallback.split(":")[0]
            for name in installed:
                if name.split(":")[0] == fb_base:
                    if name != model:
                        logger.info("Ollama model %s unavailable; using %s", model, name)
                    return name
    return model


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
        from src import session_log

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


def is_available() -> bool:
    base = SETTINGS["ollama_base_url"].rstrip("/")
    try:
        response = requests.get(f"{base}/api/tags", timeout=5)
        return response.status_code == 200
    except requests.RequestException:
        return False
