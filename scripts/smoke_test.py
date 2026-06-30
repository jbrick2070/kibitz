#!/usr/bin/env python3
"""smoke_test.py - offline package check for the kibitz skill.

Verifies the package is structurally sound WITHOUT calling Codex, Antigravity,
or Claude:
  (a) the expected file tree exists,
  (b) scripts/kibitz.py is valid Python (AST parse),
  (c) `codex`, `agy`, and `claude` availability on PATH is reported
      (soft warning, not a failure).

Exit 0 if the tree + parse pass; exit 1 otherwise. Python standard library only.
"""
from __future__ import annotations
import ast
import shutil
import sys
from pathlib import Path
from typing import Dict, Optional

ROOT = Path(__file__).resolve().parent.parent

REQUIRED_FILES = [
    "SKILL.md",
    "scripts/kibitz.py",
    "COMPAT.md",
    "references/review-prompt-r1.md",
    "references/review-prompt-r2.md",
    "references/review-prompt-r3.md",
    "references/review-prompt-r4.md",
    "references/profiles/comfyui.md",
    "README.md",
    "LICENSE",
]


def check_tree() -> list[str]:
    """Return a list of missing required files (empty == all present)."""
    missing = []
    for rel in REQUIRED_FILES:
        if not (ROOT / rel).is_file():
            missing.append(rel)
    return missing


def check_parse() -> Optional[str]:
    """AST-parse scripts/kibitz.py. Return an error string on failure, else None."""
    target = ROOT / "scripts" / "kibitz.py"
    if not target.is_file():
        return "scripts/kibitz.py is missing"
    try:
        ast.parse(target.read_text(encoding="utf-8"))
    except SyntaxError as exc:  # noqa: BLE001
        return f"SyntaxError in kibitz.py: {exc}"
    return None


def check_agents() -> Dict[str, bool]:
    """Soft check: is each agent CLI on PATH? Reported, never fatal."""
    return {name: shutil.which(name) is not None for name in ("codex", "agy", "claude")}


def main() -> int:
    print("kibitz smoke test")
    print(f"  package root: {ROOT}")
    print()

    # (a) tree
    missing = check_tree()
    print("[1] package tree")
    for rel in REQUIRED_FILES:
        mark = "MISSING" if rel in missing else "ok"
        print(f"    {mark:>7}  {rel}")
    tree_ok = not missing

    # (b) parse
    print("\n[2] kibitz.py parse")
    parse_err = check_parse()
    if parse_err is None:
        print("    ok      scripts/kibitz.py is valid Python")
    else:
        print(f"    FAILED  {parse_err}")
    parse_ok = parse_err is None

    # (c) agents on PATH (soft warning)
    print("\n[3] agent CLIs on PATH (informational, not a gate)")
    for name, present in check_agents().items():
        print(f"    {'AVAILABLE' if present else 'MISSING':>9}  {name}")

    # summary
    print()
    passed = tree_ok and parse_ok
    if passed:
        print("RESULT: PASS  (tree complete, kibitz.py parses)")
    else:
        print("RESULT: FAIL")
        if not tree_ok:
            print(f"  - {len(missing)} required file(s) missing: {', '.join(missing)}")
        if not parse_ok:
            print(f"  - parse error: {parse_err}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
