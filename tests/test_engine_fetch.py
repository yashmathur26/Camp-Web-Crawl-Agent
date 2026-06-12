"""Engine v3 Phase 2: cache, plain client, render — offline stub-server tests."""

from __future__ import annotations

import asyncio
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import config_engine
from engine.fetch.cache import FetchCache
from engine.fetch.client import Budget, BudgetExceeded, FetchClient, html_to_text
from engine.fetch.urls import is_media_url, normalize_url

# --- stub server -------------------------------------------------------------

HITS: dict[str, int] = {}


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def do_GET(self):
        HITS[self.path] = HITS.get(self.path, 0) + 1
        if self.path == "/robots.txt":
            self._send(200, "User-agent: *\nDisallow: /private/\n", "text/plain")
        elif self.path == "/page":
            self._send(200, "<html><body><h1>Soccer Camp</h1>"
                            '<a href="/detail">Details</a>' + "x" * 500 + "</body></html>")
        elif self.path == "/hang":
            time.sleep(10)  # longer than the test timeout
            self._send(200, "<html>late</html>")
        elif self.path == "/private/secret":
            self._send(200, "<html>robots should block this</html>")
        elif self.path == "/json":
            self._send(200, '{"items": [{"name": "Art & Crafts Camp"}]}', "application/json")
        else:
            self._send(404, "nope")

    def _send(self, code, body, ctype="text/html"):
        data = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture(scope="module")
def stub_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    yield base
    server.shutdown()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setitem(config_engine.ENGINE, "politeness_delay_s", 0.0)
    monkeypatch.setitem(config_engine.ENGINE, "fetch_timeout_s", 1.5)
    c = FetchClient(cache=FetchCache(tmp_path / "cache.db"))
    yield c
    c.close()


# --- 2.1 cache ---------------------------------------------------------------


def test_normalize_url_port():
    assert normalize_url("https://WWW.X.org/a/?utm_source=z") == "https://x.org/a"
    a = normalize_url("https://x.org/p?b=2&a=1")
    b = normalize_url("http://www.x.org/p/?a=1&b=2")
    assert a == b
    # WebTrac volatile params stripped
    assert "csrf" not in normalize_url("https://x.org/w?_csrf_token=abc&FMID=1")


def test_cache_repeat_url_hits(stub_server, client):
    HITS.clear()
    t1, _, _ = client.fetch_text(f"{stub_server}/page")
    t2, _, _ = client.fetch_text(f"{stub_server}/page")
    assert "Soccer Camp" in t1 and t1 == t2
    assert HITS["/page"] == 1  # second call served from cache
    assert client.cache.hits >= 1


def test_cache_persists_across_instances(stub_server, tmp_path, monkeypatch):
    monkeypatch.setitem(config_engine.ENGINE, "politeness_delay_s", 0.0)
    HITS.clear()
    c1 = FetchClient(cache=FetchCache(tmp_path / "c.db"))
    c1.fetch_text(f"{stub_server}/page")
    c1.close()
    c2 = FetchClient(cache=FetchCache(tmp_path / "c.db"))
    text, _, _ = c2.fetch_text(f"{stub_server}/page")
    c2.close()
    assert "Soccer Camp" in text
    assert HITS["/page"] == 1  # sqlite warm rerun


def test_cache_ttl_expiry(stub_server, tmp_path, monkeypatch):
    monkeypatch.setitem(config_engine.ENGINE, "politeness_delay_s", 0.0)
    HITS.clear()
    c1 = FetchClient(cache=FetchCache(tmp_path / "t.db", ttl_h=0.000001))
    c1.fetch_text(f"{stub_server}/page")
    c1.close()
    time.sleep(0.05)
    c2 = FetchClient(cache=FetchCache(tmp_path / "t.db", ttl_h=0.000001))
    c2.fetch_text(f"{stub_server}/page")
    c2.close()
    assert HITS["/page"] == 2  # expired -> refetched


# --- 2.2 client --------------------------------------------------------------


def test_timeout_not_retried(stub_server, client):
    HITS.clear()
    t0 = time.monotonic()
    text, links, _ = client.fetch_text(f"{stub_server}/hang")
    elapsed = time.monotonic() - t0
    assert text == "" and links == []
    assert HITS["/hang"] == 1            # ONE attempt — timeouts never retried
    assert elapsed < 5                    # cost <= timeout once, not 3x
    assert any(r.status == "error" and "timeout" in r.note for r in client.log)


def test_media_url_refused_before_network(client):
    text, links, _ = client.fetch_text("https://x.org/brochure.pdf")
    assert text == "" and links == []
    rec = client.log[-1]
    assert rec.status == "refused" and rec.ms == 0


def test_robots_disallow_refused(stub_server, client):
    text, _, _ = client.fetch_text(f"{stub_server}/private/secret")
    assert text == ""
    assert any(r.status == "refused" and "robots" in r.note for r in client.log)


def test_budget_exhaustion(stub_server, client):
    budget = Budget(seconds=0.0)
    with pytest.raises(BudgetExceeded):
        client.fetch_text(f"{stub_server}/page", budget=budget)


def test_fetch_json_raw_body(stub_server, client):
    data = client.fetch_json(f"{stub_server}/json")
    assert data == {"items": [{"name": "Art & Crafts Camp"}]}  # & not corrupted


def test_html_to_text_and_links(stub_server, client):
    text, links, html = client.fetch_text(f"{stub_server}/page")
    assert "Soccer Camp" in text and "<h1>" not in text
    assert links and links[0]["url"].endswith("/detail") and links[0]["text"] == "Details"


# --- 2.3 render --------------------------------------------------------------


def test_render_cap_enforced_once(stub_server):
    """A page that never settles costs <= cap, exactly one attempt."""
    from engine.fetch.render import fetch_rendered

    never_settle = (
        "<html><body><div id='x'>start</div><script>"
        "setInterval(function(){document.getElementById('x').innerHTML += ' mut';}, 100);"
        "</script></body></html>"
    )

    class _JS(_Handler):
        def do_GET(self):
            HITS[self.path] = HITS.get(self.path, 0) + 1
            if self.path == "/never":
                self._send(200, never_settle)
            elif self.path == "/normal":
                self._send(200, "<html><body><div id='y'>plain</div>"
                                "<script>document.getElementById('y').innerHTML='JS Rendered Camp List';</script>"
                                "</body></html>")
            else:
                self._send(404, "nope")

    server = ThreadingHTTPServer(("127.0.0.1", 0), _JS)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        HITS.clear()
        t0 = time.monotonic()
        text, _, _ = asyncio.run(fetch_rendered(f"{base}/never", cap_s=3.0))
        elapsed = time.monotonic() - t0
        assert elapsed < 6.0              # cap + teardown slack, never minutes
        assert HITS["/never"] == 1        # SINGLE attempt
        # cap hit mid-mutation still returns whatever rendered
        assert "start" in text

        text2, _, _ = asyncio.run(fetch_rendered(f"{base}/normal", cap_s=8.0))
        assert "JS Rendered Camp List" in text2   # rendered, not the static shell
    finally:
        server.shutdown()
