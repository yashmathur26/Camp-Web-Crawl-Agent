"""Phase 6: proposer — fingerprinting + proposals-only output."""

from __future__ import annotations

from engine.registry.proposer import fingerprint_vendor, propose_town
from engine.registry.schema import TOWNS_DIR


def test_fingerprint_vendors():
    assert fingerprint_vendor(
        "https://x.org", [{"url": "https://majwhaydenweb.myvscloud.com/webtrac/web/search.html"}], "x.org"
    )[:2] == ("webtrac", "majwhaydenweb")
    assert fingerprint_vendor(
        "https://lexrecma.myrec.com/info", [], "lexrecma.myrec.com"
    )[:2] == ("myrec", "lexrecma")
    assert fingerprint_vendor(
        "https://x.org", [{"url": "https://campscui.active.com/orgs/TheMunroe?season=1"}], "x.org"
    )[:2] == ("active", "TheMunroe")
    assert fingerprint_vendor("https://plain.org", [], "plain.org")[0] == "unknown"


def test_propose_writes_proposals_never_registry(tmp_path, monkeypatch):
    class _F:
        log = []

        def fetch_text(self, url, **kw):
            return ("some provider page " * 30,
                    [{"url": "https://lexrecma.myrec.com/info/activities.aspx"}], "")

    before = (TOWNS_DIR / "zztest.yaml").exists()
    out = propose_town("zztest", "MA",
                       ["https://townrec.org/camps", "https://facebook.com/x"],
                       fetch=_F())
    try:
        assert out.name == "zztest.proposals.yaml" and out.exists()
        body = out.read_text()
        assert "townrec.org" in body and "myrec" in body
        assert "facebook" not in body                     # denylist
        assert not (TOWNS_DIR / "zztest.yaml").exists() or before  # 6.1 DoD
    finally:
        out.unlink(missing_ok=True)
