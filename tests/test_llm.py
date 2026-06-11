"""resolve_model: deterministic, never silently downgrades to a smaller variant."""

from __future__ import annotations

from unittest.mock import patch

from src import llm


def _with_installed(models):
    return patch.object(llm, "list_installed_models", return_value=set(models))


def test_resolve_prefers_latest_over_size_variant():
    # Both installed; a bare "llama3.2" must pick :latest, never :1b — and the
    # choice must not depend on set iteration order (the bug this fixes).
    with _with_installed(["llama3.2:1b", "llama3.2:latest"]):
        assert llm.resolve_model("llama3.2") == "llama3.2:latest"
    with _with_installed(["llama3.2:latest", "llama3.2:1b"]):
        assert llm.resolve_model("llama3.2") == "llama3.2:latest"


def test_resolve_exact_tag_wins():
    with _with_installed(["llama3.2:1b", "llama3.2:latest"]):
        assert llm.resolve_model("llama3.2:1b") == "llama3.2:1b"


def test_resolve_degrades_gracefully_when_requested_missing():
    # Requested model not installed; fall back to something that IS installed
    # (here the fast model from the fallback chain) rather than erroring.
    with _with_installed(["llama3.2:1b"]):
        assert llm.resolve_model("gemma3:12b") == "llama3.2:1b"


def test_resolve_returns_requested_when_nothing_installed():
    with _with_installed([]):
        assert llm.resolve_model("llama3.2") == "llama3.2"
