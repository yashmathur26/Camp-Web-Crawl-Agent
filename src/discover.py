import base64
import os
import time

import requests
from dotenv import load_dotenv

from config.settings import SETTINGS

load_dotenv()

SearchResult = dict[str, str]  # keys: url, title, snippet


class ConfigError(Exception):
    """Raised when configuration or API keys are missing or invalid."""


def _get_api_key(env_var: str) -> str:
    key = os.getenv(env_var)
    if not key:
        raise ConfigError(
            f"Missing API key: set {env_var} in .env for provider "
            f"'{SETTINGS['search_provider']}'"
        )
    return key


def _normalize_result(item: dict) -> SearchResult | None:
    url = item.get("link") or item.get("url") or item.get("href") or ""
    if not url.startswith(("http://", "https://")):
        return None
    return {
        "url": url,
        "title": item.get("title") or item.get("name") or "",
        "snippet": item.get("snippet") or item.get("body") or item.get("description") or "",
    }


def _request_with_backoff(
    method: str, url: str, *, headers: dict, json_payload: dict | None = None
) -> requests.Response:
    max_retries = 3
    delay = 1.0
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            response = requests.request(
                method,
                url,
                headers=headers,
                json=json_payload,
                timeout=SETTINGS["request_timeout"],
            )
            if response.status_code in (429,) or response.status_code >= 500:
                if attempt < max_retries:
                    time.sleep(delay)
                    delay = min(delay * 2, 30.0)
                    continue
            return response
        except requests.RequestException as exc:
            last_exc = exc
            if attempt < max_retries:
                time.sleep(delay)
                delay = min(delay * 2, 30.0)
                continue
            raise
    if last_exc:
        raise last_exc
    raise RuntimeError("Unexpected backoff failure")


def _search_serper(query: str, limit: int) -> list[SearchResult]:
    api_key = _get_api_key("SERPER_API_KEY")
    response = _request_with_backoff(
        "POST",
        "https://google.serper.dev/search",
        headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
        json_payload={"q": query, "num": limit},
    )
    if response.status_code in (401, 403):
        raise ConfigError(
            "SERPER_API_KEY rejected by Serper (Unauthorized). Verify the key at "
            "https://serper.dev/api-key and that the account is active with credits."
        )
    response.raise_for_status()
    data = response.json()
    results: list[SearchResult] = []
    for item in data.get("organic", []):
        normalized = _normalize_result(item)
        if normalized:
            results.append(normalized)
    return results


_DATAFORSEO_BASE = "https://api.dataforseo.com/v3/serp/google/organic"
# Task-status codes that mean "not finished yet" — keep polling, don't fail.
_DATAFORSEO_PENDING_CODES = frozenset({40601, 40602, 40100})


def _dataforseo_credentials() -> str:
    login = os.getenv("DATAFORSEO_LOGIN")
    password = os.getenv("DATAFORSEO_PASSWORD")
    if not login or not password:
        raise ConfigError(
            "Set DATAFORSEO_LOGIN and DATAFORSEO_PASSWORD in .env for provider "
            "'dataforseo' (from https://app.dataforseo.com/api-access)"
        )
    return base64.b64encode(f"{login}:{password}".encode()).decode()


def _dataforseo_payload(query: str, limit: int) -> list[dict]:
    return [
        {
            "keyword": query,
            "location_code": SETTINGS.get("dataforseo_location_code", 2840),  # United States
            "language_code": SETTINGS.get("dataforseo_language_code", "en"),
            "depth": max(10, limit),
        }
    ]


def _dataforseo_items_to_results(data: dict, limit: int) -> list[SearchResult]:
    results: list[SearchResult] = []
    for task in data.get("tasks") or []:
        for res in task.get("result") or []:
            for item in res.get("items") or []:
                if item.get("type") != "organic":
                    continue
                normalized = _normalize_result(item)
                if normalized:
                    results.append(normalized)
                    if len(results) >= limit:
                        return results
    return results


def _search_dataforseo_live(query: str, limit: int, headers: dict) -> list[SearchResult]:
    response = _request_with_backoff(
        "POST",
        f"{_DATAFORSEO_BASE}/live/advanced",
        headers=headers,
        json_payload=_dataforseo_payload(query, limit),
    )
    if response.status_code == 401:
        raise ConfigError("Invalid DataForSEO credentials")
    response.raise_for_status()
    data = response.json()
    if data.get("status_code") not in (20000, None):
        raise ConfigError(f"DataForSEO error: {data.get('status_message')}")
    return _dataforseo_items_to_results(data, limit)


def _search_dataforseo_standard(query: str, limit: int, headers: dict) -> list[SearchResult]:
    """Queued mode (~3x cheaper than live): POST a task, then poll task_get."""
    post = _request_with_backoff(
        "POST",
        f"{_DATAFORSEO_BASE}/task_post",
        headers=headers,
        json_payload=_dataforseo_payload(query, limit),
    )
    if post.status_code == 401:
        raise ConfigError("Invalid DataForSEO credentials")
    post.raise_for_status()
    task = (post.json().get("tasks") or [{}])[0]
    task_id = task.get("id")
    if not task_id:
        raise ConfigError(f"DataForSEO task_post failed: {task.get('status_message')}")

    deadline = time.monotonic() + SETTINGS.get("dataforseo_poll_timeout_s", 180)
    delay = 3.0
    while time.monotonic() < deadline:
        time.sleep(delay)
        get = _request_with_backoff(
            "GET", f"{_DATAFORSEO_BASE}/task_get/advanced/{task_id}", headers=headers
        )
        get.raise_for_status()
        data = get.json()
        gtask = (data.get("tasks") or [{}])[0]
        status = gtask.get("status_code")
        if status == 20000 and gtask.get("result"):
            return _dataforseo_items_to_results(data, limit)
        if status is not None and status >= 40000 and status not in _DATAFORSEO_PENDING_CODES:
            raise ConfigError(f"DataForSEO task error ({status}): {gtask.get('status_message')}")
        delay = min(delay * 1.5, 15.0)

    raise ConfigError(
        f"DataForSEO standard task timed out after "
        f"{SETTINGS.get('dataforseo_poll_timeout_s', 180)}s; try dataforseo_mode='live'"
    )


def _search_dataforseo(query: str, limit: int) -> list[SearchResult]:
    headers = {
        "Authorization": f"Basic {_dataforseo_credentials()}",
        "Content-Type": "application/json",
    }
    mode = SETTINGS.get("dataforseo_mode", "standard")
    if mode == "live":
        return _search_dataforseo_live(query, limit, headers)
    return _search_dataforseo_standard(query, limit, headers)


def _search_brave(query: str, limit: int) -> list[SearchResult]:
    raise ConfigError("Provider 'brave' not yet implemented")


def _search_serpapi(query: str, limit: int) -> list[SearchResult]:
    raise ConfigError("Provider 'serpapi' not yet implemented")


def _search_google_cse(query: str, limit: int) -> list[SearchResult]:
    raise ConfigError("Provider 'google_cse' not yet implemented")


def _search_ddgs(query: str, limit: int, backend: str) -> list[SearchResult]:
    """Free search from your machine via the ddgs library (no API key)."""
    try:
        from ddgs import DDGS
    except ImportError as exc:
        raise ConfigError("Install ddgs: pip install ddgs") from exc

    max_retries = 3
    delay = 1.0
    last_exc: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            time.sleep(SETTINGS["delay_seconds"])
            with DDGS() as ddgs:
                raw = list(ddgs.text(query, max_results=limit, backend=backend))
            results: list[SearchResult] = []
            for item in raw:
                normalized = _normalize_result(item)
                if normalized:
                    results.append(normalized)
            return results
        except Exception as exc:
            last_exc = exc
            msg = str(exc).lower()
            if attempt < max_retries and (
                "rate" in msg or "429" in msg or "timeout" in msg
            ):
                time.sleep(delay)
                delay = min(delay * 2, 30.0)
                continue
            break

    raise ConfigError(
        f"Free search failed ({backend}): {last_exc}. "
        "Try again later, increase delay_seconds, or switch search_provider."
    ) from last_exc


def _search_duckduckgo(query: str, limit: int) -> list[SearchResult]:
    return _search_ddgs(query, limit, backend="duckduckgo")


def _search_local_google(query: str, limit: int) -> list[SearchResult]:
    """Google results scraped locally — free, no API key, may hit rate limits."""
    return _search_ddgs(query, limit, backend="google")


_PROVIDERS = {
    "serper": _search_serper,
    "dataforseo": _search_dataforseo,
    "duckduckgo": _search_duckduckgo,
    "local_google": _search_local_google,
    "brave": _search_brave,
    "serpapi": _search_serpapi,
    "google_cse": _search_google_cse,
}

FREE_PROVIDERS = frozenset({"duckduckgo", "local_google"})


def search(query: str, limit: int) -> list[SearchResult]:
    """Return search hits with url, title, and snippet."""
    provider = SETTINGS["search_provider"]
    handler = _PROVIDERS.get(provider)
    if handler is None:
        raise ConfigError(f"Unknown search provider: {provider}")
    return handler(query, limit)
