"""R2: engine/ never imports src/ — enforced on every test run."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from check_imports import find_violations  # noqa: E402


def test_engine_has_no_src_imports():
    violations = find_violations()
    assert violations == [], "engine/ must PORT old code, never import it:\n" + "\n".join(violations)


def test_checker_catches_a_violation(tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text("import phase_b.platforms\nfrom shared.urls import normalize_url\n")
    violations = find_violations(tmp_path)
    assert len(violations) == 2
    assert "import phase_b.platforms" in violations[0]
