#!/usr/bin/env python3
"""doctor.py - a friendly preflight check for the kibitz skill.

Run this BEFORE you try to use kibitz. It tells you, in plain English, whether
your machine has everything kibitz needs - and if not, exactly what to install.

It checks five things WITHOUT ever calling the agents (so it is fast and safe):
  1. Python is new enough (3.9 or later).
  2. The OpenAI Codex CLI (the `codex` command) is installed.
  3. The Google Antigravity CLI (the `agy` command) is installed.
  4. The Anthropic Claude Code CLI (the `claude` command) is installed.
  5. The kibitz package files are all present and the main script parses.

It does NOT check whether you are signed in to Codex, Antigravity, or Claude -
that can only happen when you run them yourself the first time. The doctor
confirms they are INSTALLED; you will confirm sign-in the first time you run
them.

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
WIN_CLAUDE_DIR = os.path.expandvars(r"%USERPROFILE%\.local\bin")

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
CLAUDE_HINT = (
    "Install Claude Code from Anthropic, then run `claude` once and sign in. "
    "On this Windows setup it is usually under %USERPROFILE%\\.local\\bin."
)

# The package files kibitz needs to run.
REQUIRED_FILES = [
    "SKILL.md",
    "scripts/kibitz.py",
    "scripts/comfyui_profile.py",
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

    # --- 4. Claude Code CLI ------------------------------------------------
    claude_path = find_agent("claude", WIN_CLAUDE_DIR)
    print("[4] Anthropic Claude Code CLI (the `claude` command)")
    if claude_path:
        print(f"    FOUND   {claude_path}")
    else:
        print("    NOT FOUND")
        print(f"            {CLAUDE_HINT}")
    print()

    # --- 5. kibitz package files + script parse ----------------------------
    print("[5] kibitz package files")
    missing = []
    for rel in REQUIRED_FILES:
        present = (ROOT / rel).is_file()
        print(f"    {'ok' if present else 'MISSING':>7}  {rel}")
        if not present:
            missing.append(rel)
    pkg_files_ok = not missing

    parse_ok = True
    parse_errs = []
    for rel in ("scripts/kibitz.py", "scripts/comfyui_profile.py"):
        target = ROOT / rel
        if not target.is_file():
            parse_ok = False
            parse_errs.append(f"{rel} is missing")
            continue
        try:
            ast.parse(target.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            parse_ok = False
            parse_errs.append(f"{rel}: {exc}")
    if parse_ok:
        print("    ok       scripts/kibitz.py is valid Python")
        print("    ok       scripts/comfyui_profile.py is valid Python")
    else:
        for parse_err in parse_errs:
            print(f"    FAILED   {parse_err}")
    package_ok = pkg_files_ok and parse_ok
    print()

    # --- summary -----------------------------------------------------------
    agent_paths = {
        "Codex": codex_path,
        "Antigravity": agy_path,
        "Claude Code": claude_path,
    }
    installed_agents = [name for name, path in agent_paths.items() if path]
    missing_agents = [name for name, path in agent_paths.items() if not path]
    agents_found = len(installed_agents)
    ready = py_ok and package_ok and agents_found >= 1

    print("=" * 64)
    if ready:
        print("  RESULT: READY")
        print()
        if agents_found == 3:
            print("  Codex, Antigravity, and Claude Code are installed.")
            print("  Driver-aware defaults are ready.")
        else:
            print(f"  Installed agents: {', '.join(installed_agents)}")
            print(f"  Missing agents: {', '.join(missing_agents)}")
            if codex_path and claude_path and not agy_path:
                print("  Antigravity is missing or out of quota; use:")
                print("    --only codex --only claude")
            elif claude_path and not codex_path and not agy_path:
                print("  You can run a Claude-only lane with `--only claude`.")
            else:
                print("  Use repeated `--only` flags for whichever installed agents you want.")
        print()
        print("  Last step: the first time you run `codex`, `agy`, or `claude`,")
        print("  sign in when they ask. Then point your driver at a plan and say")
        print("  'run kibitz'.")
        print("  If host auto-detection misses, pass --driver codex, --driver claude,")
        print("  --driver agy, or set KIBITZ_DRIVER.")
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
                print(f"    - Python entrypoint parse failed: {'; '.join(parse_errs)}")
        if agents_found == 0:
            print("    - Install at least one agent (Codex, Antigravity, or Claude Code;")
            print("      all three gives the fullest panel). See the hints above.")
        rc = 1
    print("=" * 64)
    return rc


if __name__ == "__main__":
    sys.exit(main())
