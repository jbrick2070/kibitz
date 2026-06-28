#!/usr/bin/env python3
"""kibitz.py - local-agent fan-out for the kibitz skill (FILE-HANDOFF contract).

Fans ONE hardening pass out to two file-reading CLI agents - Codex (`codex exec`)
and Antigravity (`agy`) - each of which reads your REAL repo on its own and returns
an independent review. No API key, no cloud spend, no copy-paste. Python standard
library only: no pip install, no third-party dependencies.

This script does the fan-out ONLY. Claude (the driver) then writes its own
code-grounded anchor review, verifies these agent reviews against the real code,
discards misreads, and merges the survivors into final.md -- "the panel proposes;
Claude disposes." See SKILL.md for the full loop and COMPAT.md for the exact flags
and the versions this was proven on.

WHY FILE-HANDOFF (not stdout scraping): both CLIs swallow stdout when their output
is redirected, so success is judged by EXIT CODE + an output FILE existing and being
non-empty, never by terminal text. Each agent writes its FINAL review to a known file:
  * Codex: native -o/--output-last-message <file>; prompt piped via stdin; sandbox
    read-only (the reviewer literally cannot edit -- the correct posture for a reviewer).
  * Antigravity: `agy` has no such flag and its -p swallows stdout, so we INSTRUCT it
    in the prompt to WRITE its review to <file> with its own write tool;
    --dangerously-skip-permissions auto-approves that one write (agy has no
    read-only-that-still-writes sandbox).

Usage:
  python kibitz.py --doc plan.md --round r2 --repo /path/to/repo
  python kibitz.py --doc plan.md --round r3 --only codex
  python kibitz.py "harden the ending-mode plan" --round r1
  python kibitz.py --doc plan.md --round r1 --timeout 600

Configuration is via CLI args and environment variables only -- no hardcoded paths.
  KIBITZ_CODEX_REASONING  Codex reasoning effort (default "high"; "xhigh" retries to "high").
  KIBITZ_AGY_MODEL        Antigravity model slug (default "gemini-3.5-pro"; "" = agy default).

SAFETY: Codex runs read-only (hard guarantee). Antigravity runs UNSANDBOXED
(--dangerously-skip-permissions) because the file-handoff needs write approval; it is
gated by a strict review-only prompt directive, and your repo is git-committed so any
stray edit shows in `git status` and is revertible. For untrusted prompts, run agy in
a throwaway git worktree.
"""
from __future__ import annotations
import argparse
import datetime
import os
import shutil
import subprocess
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
PROMPTS_DIR = SKILL_DIR / "references"

# Default: do NOT kill long agent jobs -- they batch and can take minutes. A ceiling can be
# set per-run with --timeout (seconds); this module-level value is the fallback when unset.
PER_AGENT_TIMEOUT = None

# Windows install fallbacks if the launcher is not on PATH (Codex uses a hashed bin dir).
# These are standard per-user install locations, not user-specific paths.
_WIN_CODEX_BIN = os.path.expandvars(r"%LOCALAPPDATA%\OpenAI\Codex\bin")
_WIN_AGY_BIN = os.path.expandvars(r"%LOCALAPPDATA%\agy\bin")


def _which(name: str, *extra_dirs: str):
    exe = shutil.which(name)
    if exe:
        return exe
    for d in extra_dirs:
        p = Path(d)
        if p.is_dir():
            for cand in p.rglob(name + ".exe"):
                return str(cand)
    return None


# Codex model + reasoning policy: poll the LIVE catalog via `codex debug models`, prefer the
# strongest non-mini model, default reasoning_effort="high". xhigh is model-dependent -> try
# only if asked, retry once with high on failure. See COMPAT.md.
CODEX_REASONING = os.environ.get("KIBITZ_CODEX_REASONING", "high")
CODEX_MODEL_PREFERENCE = ("gpt-5.5", "gpt-5-codex", "gpt-5")
# Antigravity has NO reasoning flag -- reasoning rides the model slug's -high/-low suffix
# (e.g. gemini-3.1-pro-high). Default to a strong pro model (gemini-3.5-pro); set
# KIBITZ_AGY_MODEL=gemini-3.1-pro-high for max reasoning, or "" to use agy's own default.
# DIVERSITY RULE (do NOT casually change): agy is MULTI-MODEL -- it can run Gemini AND
# claude-opus / claude-sonnet / gpt-oss. Keep agy on GEMINI: the judge is Claude and Codex is
# GPT, so agy=Gemini gives three DISTINCT model families; agy=Opus would duplicate the Claude
# judge (and agy=gpt-oss duplicates Codex), collapsing the panel's whole value.
AGY_MODEL = os.environ.get("KIBITZ_AGY_MODEL", "gemini-3.5-pro")


def pick_codex_model(exe: str, repo: Path, run_dir: Path):
    """Poll `codex debug models`, log it, pick the strongest non-mini model. Returns a slug or
    None (let Codex use its default). Never picks mini/fast/spark unless nothing else exists."""
    import json as _json
    try:
        raw = (subprocess.run([exe, "debug", "models"], cwd=str(repo), capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=120).stdout
               or "")
    except Exception:  # noqa: BLE001
        return None
    (run_dir / "codex_models.json").write_text(raw, encoding="utf-8")
    slugs = []
    try:
        for m in _json.loads(raw).get("models", []):
            s = str(m.get("slug", ""))
            if s and not any(b in s for b in ("mini", "fast", "spark", "nano")):
                slugs.append(s)
    except Exception:  # noqa: BLE001
        slugs = []
    for pref in CODEX_MODEL_PREFERENCE:
        if pref in slugs:
            return pref
    g5 = sorted((s for s in slugs if s.startswith("gpt-5")), reverse=True)
    return g5[0] if g5 else None


GROUNDING_FOOTER = """

------------------------------------------------------------------
YOU ARE RUNNING INSIDE A REAL REPOSITORY. Read whatever files in your current
working directory you need to ground this review in the REAL code.

The document to review is at: {input_path}

Hard rules:
- You do NOT see the other reviewers. Do NOT assume they are correct.
- Do NOT write, edit, or apply any code. Review only.
- Cite real file paths for every concrete claim. If you cannot verify
  something against the code, write "verify: <what>" instead of asserting it.

Return ONLY your review in the structure specified above. No preamble.
"""

# Antigravity has no --output-last-message flag, so the file-handoff is injected into the prompt.
AGY_OUTPUT_DIRECTIVE = """

------------------------------------------------------------------
OUTPUT CONTRACT (MANDATORY): You are a READ-ONLY reviewer. Do NOT modify, create, or delete any
file EXCEPT the single output file below. Write your COMPLETE review (only the review, in the
structure specified above) to this exact path, then stop:
  {out_path}
Do not rely on stdout. After writing the file, exit immediately.
"""


def load_round_prompt(round_id: str) -> str:
    path = PROMPTS_DIR / f"review-prompt-{round_id}.md"
    if not path.is_file():
        sys.exit(f"ERROR: round prompt not found: {path}\n"
                 f"Expected the skill's references/ folder next to scripts/.")
    return path.read_text(encoding="utf-8")


def run_codex(prompt: str, repo: Path, out_file: Path, log_file: Path) -> bool:
    """Codex: read-only sandbox; -o writes the final answer to out_file; model auto-picked
    from the live catalog; reasoning_effort=high (xhigh retries to high)."""
    exe = _which("codex", _WIN_CODEX_BIN)
    if exe is None:
        log_file.write_text(r"codex not found on PATH or in %LOCALAPPDATA%\OpenAI\Codex\bin",
                            encoding="utf-8")
        print("  x codex: command not found")
        return False
    if out_file.exists():
        out_file.unlink()
    run_dir = out_file.parent
    model = pick_codex_model(exe, repo, run_dir)
    (run_dir / "codex_model_selected.txt").write_text(model or "(codex default)", encoding="utf-8")
    (run_dir / "codex_reasoning_selected.txt").write_text(CODEX_REASONING, encoding="utf-8")

    def _run(reff: str):
        cmd = [exe, "exec", "-C", str(repo), "--sandbox", "read-only",
               "--json", "--color", "never",
               "-c", 'model_reasoning_effort="%s"' % reff]
        if model:
            cmd += ["-m", model]
        cmd += ["-o", str(out_file), "-"]
        print(f"  -> codex: model={model or 'default'} reasoning={reff} -> {out_file.name}")
        with log_file.open("w", encoding="utf-8") as log:
            return subprocess.run(cmd, input=prompt, text=True, cwd=str(repo),
                                  stdout=log, stderr=subprocess.STDOUT,
                                  encoding="utf-8", errors="replace",
                                  timeout=PER_AGENT_TIMEOUT)

    proc = _run(CODEX_REASONING)
    ok = proc.returncode == 0 and out_file.exists() and out_file.stat().st_size > 0
    if not ok and CODEX_REASONING == "xhigh":
        print("  .. xhigh failed -> retry once with high")
        (run_dir / "codex_reasoning_selected.txt").write_text("high (xhigh failed)",
                                                              encoding="utf-8")
        proc = _run("high")
        ok = proc.returncode == 0 and out_file.exists() and out_file.stat().st_size > 0
    print(f"  [{'OK' if ok else 'FAILED'}] codex (rc={proc.returncode}, model={model or 'default'})")
    return ok


def run_agy(prompt: str, repo: Path, out_file: Path, log_file: Path) -> bool:
    """Antigravity: stdout is swallowed when redirected, so agy writes its review to out_file
    itself (file-handoff). --dangerously-skip-permissions auto-approves the write."""
    exe = _which("agy", _WIN_AGY_BIN)
    if exe is None:
        log_file.write_text(r"agy not found on PATH or in %LOCALAPPDATA%\agy\bin",
                            encoding="utf-8")
        print("  x antigravity: command not found")
        return False
    if out_file.exists():
        out_file.unlink()
    full = prompt + AGY_OUTPUT_DIRECTIVE.format(out_path=str(out_file))
    cmd = [exe, "--dangerously-skip-permissions", "-p", full]
    if AGY_MODEL:
        cmd[1:1] = ["--model", AGY_MODEL]
    (out_file.parent / "agy_model_selected.txt").write_text(
        AGY_MODEL or "(agy default)", encoding="utf-8")
    print(f"  -> antigravity: model={AGY_MODEL or 'default'} file-handoff -> {out_file.name}")
    with log_file.open("w", encoding="utf-8") as log:
        proc = subprocess.run(cmd, text=True, cwd=str(repo),
                              stdout=log, stderr=subprocess.STDOUT,
                              encoding="utf-8", errors="replace",
                              timeout=PER_AGENT_TIMEOUT)
    ok = proc.returncode == 0 and out_file.exists() and out_file.stat().st_size > 0
    print(f"  [{'OK' if ok else 'FAILED'}] antigravity (rc={proc.returncode}) -> {out_file.name}")
    return ok


RUNNERS = {"codex": run_codex, "antigravity": run_agy}


def main() -> None:
    global PER_AGENT_TIMEOUT
    ap = argparse.ArgumentParser(
        description="kibitz local-agent fan-out (Codex + Antigravity, file-handoff)")
    ap.add_argument("problem", nargs="?", help="the plan / problem text to harden")
    ap.add_argument("--doc", help="path to an existing plan .md (instead of inline text)")
    ap.add_argument("--round", choices=["r1", "r2", "r3", "r4"], default="r1")
    ap.add_argument("--topic", default="kibitz", help="short slug for the run folder")
    ap.add_argument("--repo", type=Path, default=Path.cwd())
    ap.add_argument("--only", choices=list(RUNNERS), action="append",
                    help="run only this agent (repeatable). Default: all.")
    ap.add_argument("--timeout", type=float, default=None,
                    help="per-agent timeout in seconds (default: none -- agents batch).")
    args = ap.parse_args()

    if args.timeout is not None:
        PER_AGENT_TIMEOUT = args.timeout

    repo = args.repo.resolve()
    if not repo.is_dir():
        sys.exit(f"ERROR: --repo is not a directory: {repo}")
    if args.doc:
        input_text = Path(args.doc).read_text(encoding="utf-8")
    elif args.problem:
        input_text = args.problem
    else:
        ap.error("provide a problem string, or use --doc <path>")

    selected = args.only or list(RUNNERS)
    date = datetime.date.today().isoformat()
    run_dir = repo / "kibitz-runs" / f"{date}-{args.topic}" / args.round
    run_dir.mkdir(parents=True, exist_ok=True)
    input_path = run_dir / "input.md"
    input_path.write_text(input_text, encoding="utf-8")

    prompt = (load_round_prompt(args.round)
              + GROUNDING_FOOTER.format(input_path=input_path.as_posix()))

    print(f"Repo:       {repo}")
    print(f"Round:      {args.round}")
    print(f"Run folder: {run_dir}")
    print(f"Agents:     {', '.join(selected)}")
    print("Fanning out (each agent reads the repo + writes its review to a FILE):")

    results = {}
    for name in selected:
        results[name] = RUNNERS[name](
            prompt, repo, run_dir / f"{name}.md", run_dir / f"{name}.log")

    print("\nReviews collected:")
    for name, ok in results.items():
        print(f"  {name}: {'OK' if ok else 'FAILED - check the .log'}")
    print("\nNext (Claude, NOT the script):")
    print(f"  1. Write your own code-grounded anchor review of {input_path.name}.")
    print("  2. Verify every claim in the agent reviews against the real code; discard misreads.")
    print(f"  3. Merge the survivors into {run_dir / 'final.md'}.")
    print("  4. For the full arc, advance r1 -> r2 -> r3 -> r4.")

    if not any(results.values()):
        sys.exit(1)


if __name__ == "__main__":
    main()

# ---------------------------------------------------------------------------
# IMPLEMENTATION NOTES (see COMPAT.md for the proven versions and the flags caveat):
#  - Codex: `codex exec -C <repo> --sandbox read-only --json --color never -o <file> -`
#    (prompt on stdin) writes the final answer to <file>.
#  - Antigravity: headless `agy -p` swallows stdout when redirected; the file-handoff
#    (tell agy to write its review to <file> + --dangerously-skip-permissions) works.
#    The `| clip` clipboard bypass does NOT work (still a stdout redirect = empty).
#  - Never scrape terminal output for DONE/FINISHED. Never set a short subprocess timeout
#    unless you explicitly want to bail on a hung agent (use --timeout for that).
# ---------------------------------------------------------------------------
