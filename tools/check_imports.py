"""R2 import-boundary check: engine/ must never import from src/.

Wanted old code is PORTED into engine/, never imported. Run standalone
(`python tools/check_imports.py`) or via the pytest wrapper in
tests/test_engine_boundary.py so every test run enforces the boundary.
Exit code 1 + offending file:line list on violation.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parent.parent / "engine"


def find_violations(root: Path = ENGINE_ROOT) -> list[str]:
    violations: list[str] = []
    if not root.exists():
        return violations
    for py in sorted(root.rglob("*.py")):
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        except SyntaxError as exc:
            violations.append(f"{py}:{exc.lineno}: syntax error blocks boundary check: {exc.msg}")
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "src" or alias.name.startswith("src."):
                        violations.append(f"{py}:{node.lineno}: import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                # level>0 relative imports can't reach src/ from engine/.
                if node.level == 0 and (mod == "src" or mod.startswith("src.")):
                    violations.append(f"{py}:{node.lineno}: from {mod} import ...")
    return violations


def main() -> int:
    violations = find_violations()
    if violations:
        print("R2 violation: engine/ imports from src/ (port the code instead):")
        for v in violations:
            print(f"  {v}")
        return 1
    print("import boundary OK: engine/ does not import src/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
