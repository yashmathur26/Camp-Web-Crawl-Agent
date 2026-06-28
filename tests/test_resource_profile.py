"""W3W memory-crash fixes: resource profile, memory gate, gap URL cap, unload."""

from unittest.mock import patch

import config.resource as rp


def test_profiles_exist_and_16gb_is_conservative():
    p = rp.RESOURCE_PROFILES["16gb"]
    assert p["ollama_single_model"]              # one model only
    assert p["engine_concurrency"] == 1
    assert p["max_browsers"] == 1
    assert p["ollama_preload_models"] is False
    assert p["gap_max_urls_per_round"] <= 30
    # 32gb allows more
    assert rp.RESOURCE_PROFILES["32gb"]["engine_concurrency"] > 1


def test_detect_profile_env_override(monkeypatch):
    monkeypatch.setenv("FIREFLY_RESOURCE_PROFILE", "32gb")
    assert rp.detect_profile() == "32gb"
    monkeypatch.setenv("FIREFLY_RESOURCE_PROFILE", "16gb")
    assert rp.detect_profile() == "16gb"


def test_detect_profile_by_ram(monkeypatch):
    monkeypatch.delenv("FIREFLY_RESOURCE_PROFILE", raising=False)
    with patch("psutil.virtual_memory") as vm:
        vm.return_value.total = 16 * 1024 ** 3
        assert rp.detect_profile() == "16gb"
        vm.return_value.total = 64 * 1024 ** 3
        assert rp.detect_profile() == "32gb"


def test_settings_single_model_collapse():
    # The live settings (this machine = 16gb) collapse every role to one model.
    from config.settings import SETTINGS

    if SETTINGS.get("resource_profile") == "16gb":
        models = {SETTINGS["ollama_model"], SETTINGS["ollama_fast_model"],
                  SETTINGS["ollama_verify_model"], SETTINGS["ollama_filter_model"]}
        assert len(models) == 1
        assert SETTINGS["ollama_preload_models"] is False
        assert SETTINGS["ollama_keep_alive"] == "2m"


def test_memory_gate():
    from phase_b.resource_guard import MemoryBudgetError, require_memory

    with patch("phase_b.resource_guard.available_memory_mb", return_value=5000):
        require_memory(3000, "phase_c")            # ok, no raise
    with patch("phase_b.resource_guard.available_memory_mb", return_value=800):
        try:
            require_memory(3000, "phase_c")
            assert False, "expected MemoryBudgetError"
        except MemoryBudgetError as e:
            assert "phase_c" in str(e)


def test_gap_url_cap(monkeypatch, tmp_path):
    import phase_c.agentic_gap as ag

    captured = {}

    def fake_enum(town, urls):
        captured["urls"] = urls
        return []

    monkeypatch.setattr(ag, "enumerate_hosts_via_engine", fake_enum, raising=False)
    monkeypatch.setattr("phase_c.engine_bridge.enumerate_hosts_via_engine", fake_enum)
    monkeypatch.setattr(ag, "_seed_urls_for_hosts", lambda h, t: [])
    monkeypatch.setitem(ag.SETTINGS, "gap_max_urls_per_round", 5)
    # 20 urls across 20 hosts -> capped to 5
    urls = [f"https://h{i}.org/camp" for i in range(20)]
    ag._enumerate_new_hosts_engine("Lexington", set(), urls)
    assert len(captured["urls"]) == 5


def test_gap_url_cap_one_per_host_first(monkeypatch):
    import phase_c.agentic_gap as ag

    captured = {}
    monkeypatch.setattr("phase_c.engine_bridge.enumerate_hosts_via_engine",
                        lambda town, urls: captured.update(urls=urls) or [])
    monkeypatch.setattr(ag, "_seed_urls_for_hosts", lambda h, t: [])
    monkeypatch.setitem(ag.SETTINGS, "gap_max_urls_per_round", 3)
    # host A has 5 urls, hosts B/C/D one each — breadth should reach B,C,D
    urls = [f"https://a.org/{i}" for i in range(5)] + [
        "https://b.org/x", "https://c.org/x", "https://d.org/x"]
    ag._enumerate_new_hosts_engine("Lexington", set(), urls)
    hosts = {u.split("/")[2] for u in captured["urls"]}
    assert hosts == {"a.org", "b.org", "c.org"}    # one-per-host breadth, capped 3
