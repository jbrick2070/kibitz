#!/usr/bin/env python3
"""smoke_test.py - offline package check for the kibitz skill.

Verifies the package is structurally sound WITHOUT calling Codex, Antigravity,
Claude, or Cursor:
  (a) the expected file tree exists,
  (b) scripts/kibitz.py is valid Python (AST parse),
  (c) `codex`, `agy`, `claude` and the Cursor CLI availability is reported
      (soft warning, not a failure). Cursor is looked up in its install
      directory as well as on PATH, because it is not placed on PATH.

Exit 0 if the tree + parse pass; exit 1 otherwise. Python standard library only.
"""
from __future__ import annotations
import ast
import os
import shutil
import sys
from pathlib import Path
from typing import Dict, Optional

ROOT = Path(__file__).resolve().parent.parent

REQUIRED_FILES = [
    "SKILL.md",
    "agents/openai.yaml",
    "scripts/build_skill_bundle.py",
    "scripts/kibitz.py",
    "scripts/comfyui_profile.py",
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
    """AST-parse Python entry points. Return an error string on failure, else None."""
    for rel in (
        "scripts/build_skill_bundle.py",
        "scripts/kibitz.py",
        "scripts/comfyui_profile.py",
    ):
        target = ROOT / rel
        if not target.is_file():
            return f"{rel} is missing"
        try:
            ast.parse(target.read_text(encoding="utf-8"))
        except SyntaxError as exc:  # noqa: BLE001
            return f"SyntaxError in {rel}: {exc}"
    return None


#: Cursor installs agent.cmd here and does NOT put it on PATH, so a which()-only
#: probe reports it missing on a machine where it is installed and working. The
#: Cursor EDITOR is not involved -- the CLI is standalone.
WIN_CURSOR_DIR = os.path.expandvars(r"%LOCALAPPDATA%\cursor-agent")
CURSOR_LAUNCHERS = ("cursor-agent.cmd", "agent.cmd", "cursor-agent.exe", "agent.exe")


def _cursor_present() -> bool:
    # Same order as kibitz.py's _which_cursor: KIBITZ_CURSOR_BIN, install dir, PATH.
    for candidate_dir in (os.environ.get("KIBITZ_CURSOR_BIN", "").strip(), WIN_CURSOR_DIR):
        if not candidate_dir:
            continue
        root = Path(candidate_dir)
        if root.is_dir() and any((root / c).is_file() for c in CURSOR_LAUNCHERS):
            return True
    return any(shutil.which(n) is not None for n in ("cursor-agent", "agent"))


def check_agents() -> Dict[str, bool]:
    """Soft check: is each agent CLI available? Reported, never fatal."""
    found = {name: shutil.which(name) is not None for name in ("codex", "agy", "claude")}
    found["cursor"] = _cursor_present()
    return found


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
    print("\n[2] Python entrypoint parse")
    parse_err = check_parse()
    if parse_err is None:
        print("    ok      scripts/build_skill_bundle.py is valid Python")
        print("    ok      scripts/kibitz.py is valid Python")
        print("    ok      scripts/comfyui_profile.py is valid Python")
    else:
        print(f"    FAILED  {parse_err}")
    parse_ok = parse_err is None

    # (c) agent CLIs available (soft warning)
    print("\n[3] agent CLIs available (informational, not a gate)")
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
