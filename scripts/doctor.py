#!/usr/bin/env python3
"""doctor.py - a friendly preflight check for the kibitz skill.

Run this BEFORE you try to use kibitz. It tells you, in plain English, whether
your machine has everything kibitz needs - and if not, exactly what to install.

It checks four things WITHOUT ever calling the agents (so it is fast and safe):
  1. Python is new enough (3.9 or later).
  2. The OpenAI Codex CLI (the `codex` command) is installed.
  3. The Google Antigravity CLI (the `agy` command) is installed.
  4. The kibitz package files are all present and the main script parses.

It does NOT check whether you are signed in to Codex or Antigravity - that can
only happen when you run them yourself the first time. The doctor confirms they
are INSTALLED; you will confirm sign-in the first time you run them.

Exit code 0 means "READY". Exit code 1 means "not ready yet, here is what to fix".
Python standard library only - no pip install, no dependencies.
"""
from __future__ import annotations
import ast
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Standard per-user install locations on Windows (not user-specific paths).
WIN_CODEX_DIR = os.path.expandvars(r"%LOCALAPPDATA%\OpenAI\Codex")
WIN_AGY_DIR = os.path.expandvars(r"%LOCALAPPDATA%\agy\bin")

CODEX_HINT = (
    "Install Codex - Windows: powershell -ExecutionPolicy ByPass -c "
    '"irm https://chatgpt.com/codex/install.ps1 | iex"  |  '
    "Mac/Linux: npm install -g @openai/codex  (needs Node.js 22+; "
    "must be the scoped @openai/codex). Then run `codex` once and sign in."
)
AGY_HINT = (
    "Install Antigravity - Windows: irm https://antigravity.google/cli/install.ps1 | iex  |  "
    "Mac/Linux: curl -fsSL https://antigravity.google/cli/install.sh | bash. "
    "Then run `agy` once and sign in with your Google account."
)

# The package files kibitz needs to run.
REQUIRED_FILES = [
    "SKILL.md",
    "scripts/kibitz.py",
    "COMPAT.md",
    "references/review-prompt-r1.md",
    "references/review-prompt-r2.md",
    "references/review-prompt-r3.md",
    "references/review-prompt-r4.md",
    "references/profiles/comfyui.md",
]


def find_agent(name: str, win_dir: str):
    """Find an agent CLI: PATH first, then the Windows per-user install dir.
    Returns the full path string, or None if not found."""
    exe = shutil.which(name)
    if exe:
        return exe
    d = Path(win_dir)
    if d.is_dir():
        for cand in d.rglob(name + ".exe"):
            return str(cand)
    return None


def main() -> int:
    print("=" * 64)
    print("  kibitz doctor - checking your machine is ready")
    print("=" * 64)
    print()
    print("  (This does not call the agents. It only checks they are installed.")
    print("   You will confirm sign-in the first time you run them.)")
    print()

    # --- 1. Python version -------------------------------------------------
    py_ok = sys.version_info >= (3, 9)
    pv = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    print("[1] Python 3.9 or later")
    if py_ok:
        print(f"    PASS    you have Python {pv}")
    else:
        print(f"    FAIL    you have Python {pv} - kibitz needs 3.9 or later")
    print()

    # --- 2. Codex CLI ------------------------------------------------------
    codex_path = find_agent("codex", WIN_CODEX_DIR)
    print("[2] OpenAI Codex CLI (the `codex` command)")
    if codex_path:
        print(f"    FOUND   {codex_path}")
    else:
        print("    NOT FOUND")
        print(f"            {CODEX_HINT}")
    print()

    # --- 3. Antigravity CLI ------------------------------------------------
    agy_path = find_agent("agy", WIN_AGY_DIR)
    print("[3] Google Antigravity CLI (the `agy` command)")
    if agy_path:
        print(f"    FOUND   {agy_path}")
    else:
        print("    NOT FOUND")
        print(f"            {AGY_HINT}")
    print()

    # --- 4. kibitz package files + script parse ----------------------------
    print("[4] kibitz package files")
    missing = []
    for rel in REQUIRED_FILES:
        present = (ROOT / rel).is_file()
        print(f"    {'ok' if present else 'MISSING':>7}  {rel}")
        if not present:
            missing.append(rel)
    pkg_files_ok = not missing

    parse_ok = True
    parse_err = None
    target = ROOT / "scripts" / "kibitz.py"
    if target.is_file():
        try:
            ast.parse(target.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            parse_ok = False
            parse_err = str(exc)
    else:
        parse_ok = False
        parse_err = "scripts/kibitz.py is missing"
    if parse_ok:
        print("    ok       scripts/kibitz.py is valid Python")
    else:
        print(f"    FAILED   scripts/kibitz.py: {parse_err}")
    package_ok = pkg_files_ok and parse_ok
    print()

    # --- summary -----------------------------------------------------------
    agents_found = int(bool(codex_path)) + int(bool(agy_path))
    ready = py_ok and package_ok and agents_found >= 1

    print("=" * 64)
    if ready:
        print("  RESULT: READY")
        print()
        if agents_found == 2:
            print("  Both agents are installed. You will get a full two-agent panel.")
        else:
            only = "Codex" if codex_path else "Antigravity"
            missing_one = "Antigravity" if codex_path else "Codex"
            print(f"  Only {only} is installed, so you can run, but you'll get a")
            print(f"  one-agent panel. Install {missing_one} for the full second opinion.")
        print()
        print("  Last step: the first time you run `codex` and `agy`, sign in when")
        print("  they ask. Then point your Claude at a plan and say 'run kibitz'.")
        rc = 0
    else:
        print("  RESULT: NOT READY YET")
        print()
        print("  Fix these, then run the doctor again:")
        if not py_ok:
            print(f"    - Install Python 3.9 or later (you have {pv}).")
        if not package_ok:
            if missing:
                print(f"    - Missing package files: {', '.join(missing)}")
                print("      Re-clone the kibitz repo - some files did not copy.")
            if not parse_ok:
                print(f"    - scripts/kibitz.py did not parse: {parse_err}")
        if agents_found == 0:
            print("    - Install at least one agent (kibitz needs Codex OR Antigravity;")
            print("      both is best). See the hints above under [2] and [3].")
        rc = 1
    print("=" * 64)
    return rc


if __name__ == "__main__":
    sys.exit(main())
