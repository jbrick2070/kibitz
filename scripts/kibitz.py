#!/usr/bin/env python3
"""kibitz.py - local-agent fan-out for the kibitz skill (FILE-HANDOFF contract).

Fans ONE hardening pass out to local file-reading CLI agents - Codex
(`codex exec`), Antigravity (`agy`), and Claude Code (`claude -p`). Each reads
your REAL repo on its own and returns an independent review. No API key, no
copy-paste. Python standard library only: no pip install, no third-party
dependencies.

The default panel is driver-aware: if Claude is driving, run Codex + Antigravity;
if Codex is driving, run Antigravity + Claude; if Antigravity is driving, run
Codex + Claude. If no driver is detected, run all three agents. Use `--driver`
or `KIBITZ_DRIVER` to make the driver explicit, and repeated `--only` flags for
manual fallbacks. `--only agy` is accepted as an alias for `--only antigravity`.

This script does the fan-out ONLY. The driver (Claude, Codex, or another host)
then writes its own code-grounded anchor review, verifies these agent reviews
against the real code, discards misreads, and merges the survivors into final.md
-- "the panel proposes; the driver disposes." See SKILL.md for the full loop and
COMPAT.md for the exact flags and the versions this was proven on.

WHY FILE-HANDOFF (not stdout scraping): some CLIs swallow stdout when their output
is redirected, so success is judged by EXIT CODE + an output FILE existing and being
non-empty, never by terminal text. Each file-handoff agent writes its FINAL review
to a known file:
  * Codex: native -o/--output-last-message <file>; prompt passed as an arg; sandbox
    read-only (the reviewer literally cannot edit -- the correct posture for a reviewer).
  * Antigravity: `agy` has no such flag and its -p swallows stdout, so we INSTRUCT it
    in the prompt to WRITE its review to <file> with its own write tool;
    --dangerously-skip-permissions auto-approves that one write (agy has no
    read-only-that-still-writes sandbox).
  * Claude: no native -o flag, so it uses the same file-handoff contract as
    Antigravity. The prompt is passed as an arg; Claude may write only <file>.

Usage:
  python kibitz.py --doc plan.md --round r2 --repo /path/to/repo
  python kibitz.py --doc plan.md --round r2 --repo /path/to/repo --profile comfyui
  python kibitz.py --doc plan.md --round r2 --repo /path/to/repo --driver codex
  python kibitz.py --doc plan.md --round r2 --repo /path/to/repo --driver none
  python kibitz.py --doc plan.md --round r3 --only codex --only claude
  python kibitz.py --doc plan.md --round r3 --only agy
  python kibitz.py --doc plan.md --round r3 --only claude
  python kibitz.py --doc plan.md --round r3 --driver codex --dry-run
  python kibitz.py "harden the ending-mode plan" --round r1
  python kibitz.py --doc plan.md --round r1 --timeout 600

Configuration is via CLI args and environment variables only -- no hardcoded paths.
  KIBITZ_CODEX_REASONING  Codex reasoning effort (default "high"; "xhigh" retries to "high").
  KIBITZ_AGY_MODEL        Antigravity model slug (default "gemini-3.5-pro"; "" = agy default).
  KIBITZ_CLAUDE_MODEL     Claude model alias/slug (default "sonnet"; "" = Claude default).
  KIBITZ_CLAUDE_EFFORT    Claude effort level (default "high"; low/medium/high/max).
  KIBITZ_DRIVER           Active driver: auto, none, codex, claude, antigravity/agy.

SAFETY: Codex runs read-only (hard guarantee). Antigravity runs UNSANDBOXED
(--dangerously-skip-permissions) because the file-handoff needs write approval; it is
gated by a strict review-only prompt directive, and your repo is git-committed so any
stray edit shows in `git status` and is revertible. Claude also uses
--dangerously-skip-permissions for its file-handoff, but its tool list is narrowed
to Read/Glob/Grep/Write. For untrusted prompts, run writable lanes in a throwaway
git worktree.
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
PROFILE_ALIASES = {
    "comfyui": PROMPTS_DIR / "profiles" / "comfyui.md",
}
LOCAL_COMFYUI_PROFILE = Path(".kibitz") / "comfyui.local.md"

# Default: do NOT kill long agent jobs -- they batch and can take minutes. A ceiling can be
# set per-run with --timeout (seconds); this module-level value is the fallback when unset.
PER_AGENT_TIMEOUT = None

# Windows install fallbacks if the launcher is not on PATH (Codex uses a hashed bin dir).
# These are standard per-user install locations, not user-specific paths.
_WIN_CODEX_BIN = os.path.expandvars(r"%LOCALAPPDATA%\OpenAI\Codex\bin")
_WIN_AGY_BIN = os.path.expandvars(r"%LOCALAPPDATA%\agy\bin")
_WIN_CLAUDE_BIN = os.path.expandvars(r"%USERPROFILE%\.local\bin")


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
# claude-opus / claude-sonnet / gpt-oss. Keep agy on GEMINI: Codex is GPT-family
# and Claude Code can supply the Claude-family lane, so agy=Gemini gives three
# DISTINCT model families; agy=Opus duplicates Claude and agy=gpt-oss duplicates
# Codex, collapsing the panel's whole value.
AGY_MODEL = os.environ.get("KIBITZ_AGY_MODEL", "gemini-3.5-pro")
AGY_PRINT_TIMEOUT = os.environ.get("KIBITZ_AGY_PRINT_TIMEOUT", "5m")
CLAUDE_MODEL = os.environ.get("KIBITZ_CLAUDE_MODEL", "sonnet")
CLAUDE_EFFORT = os.environ.get("KIBITZ_CLAUDE_EFFORT", "high")


def pick_codex_model(exe: str, repo: Path, run_dir: Path):
    """Poll `codex debug models`, log it, pick the strongest non-mini model. Returns a slug or
    None (let Codex use its default). Never picks mini/fast/spark unless nothing else exists."""
    import json as _json
    try:
        raw = (subprocess.run([exe, "debug", "models"], cwd=str(repo), stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=120).stdout
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

# Antigravity and Claude have no --output-last-message flag, so file-handoff is injected into
# their prompt. Codex uses its native -o channel, then the same collector verifies the file.
FILE_OUTPUT_DIRECTIVE = """

------------------------------------------------------------------
OUTPUT CONTRACT (MANDATORY): You are a READ-ONLY reviewer. Do NOT modify, create, or delete any
file EXCEPT the single output file below. Write your COMPLETE review (only the review, in the
structure specified above) to this exact path, then stop:
  {out_path}
Do not rely on stdout. After writing the file, exit immediately.
"""


def write_process_log(log_file: Path, stdout_text: str, stderr_text: str, extra: str = "") -> None:
    chunks = []
    if extra:
        chunks.append(extra.rstrip())
    if stdout_text:
        chunks.append("STDOUT:\n" + stdout_text.rstrip())
    if stderr_text:
        chunks.append("STDERR:\n" + stderr_text.rstrip())
    log_file.write_text(("\n\n".join(chunks) + ("\n" if chunks else "")), encoding="utf-8")


def append_process_log(log_file: Path, text: str) -> None:
    with log_file.open("a", encoding="utf-8") as log:
        log.write(text.rstrip() + "\n")


def collect_review(
    name: str,
    out_file: Path,
    log_file: Path,
    returncode: int,
    stdout_text: str = "",
) -> bool:
    """Read the review from the explicit file first, then stdout as a fallback."""
    review = ""
    if out_file.exists():
        review = out_file.read_text(encoding="utf-8", errors="replace").strip()
    if not review and stdout_text.strip():
        review = stdout_text.strip()
    if review:
        out_file.write_text(review + "\n", encoding="utf-8")
    ok = returncode == 0 and bool(review)
    if returncode == 0 and not review:
        msg = (f"{name}: rc=0 but NO review text (agy #76 / strict read-only). "
               "Failing this leg.")
        print(f"  [FAILED] {msg}")
        append_process_log(log_file, msg)
    return ok


def load_round_prompt(round_id: str) -> str:
    path = PROMPTS_DIR / f"review-prompt-{round_id}.md"
    if not path.is_file():
        sys.exit(f"ERROR: round prompt not found: {path}\n"
                 f"Expected the skill's references/ folder next to scripts/.")
    return path.read_text(encoding="utf-8")


def resolve_profile_path(raw: str, repo: Path) -> Path:
    key = raw.strip().lower()
    if key in PROFILE_ALIASES:
        return PROFILE_ALIASES[key]
    path = Path(raw)
    if path.is_absolute():
        return path
    repo_path = repo / path
    if repo_path.exists():
        return repo_path
    return SKILL_DIR / path


def load_profiles(repo: Path, requested: list[str], no_profiles: bool):
    """Return (profile_entries, combined_profile_text).

    A repo-local .kibitz/comfyui.local.md opt-in file auto-enables both the
    shipped generic ComfyUI profile and the local overlay. That keeps the user
    profile small while preserving the durable ComfyUI invariants.
    """
    if no_profiles:
        return [], ""

    entries = []
    seen = set()

    def add(label: str, path: Path) -> None:
        if not path.is_file():
            sys.exit(f"ERROR: profile not found: {path}")
        resolved = path.resolve()
        if resolved in seen:
            return
        seen.add(resolved)
        entries.append((label, resolved))

    for raw in requested:
        add(raw, resolve_profile_path(raw, repo))

    local_profile = repo / LOCAL_COMFYUI_PROFILE
    if local_profile.is_file():
        add("comfyui", PROFILE_ALIASES["comfyui"])
        add(str(LOCAL_COMFYUI_PROFILE), local_profile)

    chunks = []
    for label, path in entries:
        chunks.append(
            "\n\n"
            "------------------------------------------------------------------\n"
            f"DOMAIN PROFILE: {label}\n"
            "------------------------------------------------------------------\n"
            + path.read_text(encoding="utf-8").strip()
            + "\n"
        )
    return entries, "".join(chunks)


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
        cmd += ["-o", str(out_file), prompt]
        print(f"  -> codex: model={model or 'default'} reasoning={reff} -> {out_file.name}")
        proc = subprocess.run(cmd, stdin=subprocess.DEVNULL, text=True, cwd=str(repo),
                              capture_output=True, encoding="utf-8", errors="replace",
                              timeout=PER_AGENT_TIMEOUT)
        write_process_log(log_file, proc.stdout or "", proc.stderr or "")
        return proc

    proc = _run(CODEX_REASONING)
    ok = collect_review("codex", out_file, log_file, proc.returncode, proc.stdout or "")
    if not ok and CODEX_REASONING == "xhigh":
        print("  .. xhigh failed -> retry once with high")
        (run_dir / "codex_reasoning_selected.txt").write_text("high (xhigh failed)",
                                                              encoding="utf-8")
        proc = _run("high")
        ok = collect_review("codex", out_file, log_file, proc.returncode, proc.stdout or "")
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
    full = prompt + FILE_OUTPUT_DIRECTIVE.format(out_path=str(out_file))
    cmd = [exe, "--dangerously-skip-permissions", "--print-timeout", AGY_PRINT_TIMEOUT, "-p", full]
    if AGY_MODEL:
        cmd[1:1] = ["--model", AGY_MODEL]
    (out_file.parent / "agy_model_selected.txt").write_text(
        AGY_MODEL or "(agy default)", encoding="utf-8")
    print(f"  -> antigravity: model={AGY_MODEL or 'default'} file-handoff -> {out_file.name}")
    try:
        proc = subprocess.run(cmd, stdin=subprocess.DEVNULL, text=True, cwd=str(repo),
                              capture_output=True, encoding="utf-8", errors="replace",
                              timeout=PER_AGENT_TIMEOUT)
        write_process_log(log_file, proc.stdout or "", proc.stderr or "")
    except subprocess.TimeoutExpired:
        print(f"  [FAILED] antigravity (timeout after {PER_AGENT_TIMEOUT}s)")
        return False
    ok = collect_review("antigravity", out_file, log_file, proc.returncode,
                        getattr(proc, "stdout", "") or "")
    print(f"  [{'OK' if ok else 'FAILED'}] antigravity (rc={proc.returncode}) -> {out_file.name}")
    return ok


def run_claude(prompt: str, repo: Path, out_file: Path, log_file: Path) -> bool:
    """Claude Code: no native -o flag, so file-handoff like Antigravity.
    Prompt is passed as an arg; --dangerously-skip-permissions approves the output write."""
    exe = _which("claude", _WIN_CLAUDE_BIN)
    if exe is None:
        log_file.write_text(r"claude not found on PATH or in %USERPROFILE%\.local\bin",
                            encoding="utf-8")
        print("  x claude: command not found")
        return False
    if out_file.exists():
        out_file.unlink()
    full = prompt + FILE_OUTPUT_DIRECTIVE.format(out_path=str(out_file))
    cmd = [
        exe,
        "-p",
        "--output-format", "text",
        "--no-session-persistence",
        "--dangerously-skip-permissions",
        "--tools", "Read,Glob,Grep,Write",
        "--add-dir", str(repo),
    ]
    if CLAUDE_MODEL:
        cmd += ["--model", CLAUDE_MODEL]
    if CLAUDE_EFFORT:
        cmd += ["--effort", CLAUDE_EFFORT]
    cmd.append(full)
    (out_file.parent / "claude_model_selected.txt").write_text(
        CLAUDE_MODEL or "(claude default)", encoding="utf-8")
    (out_file.parent / "claude_effort_selected.txt").write_text(
        CLAUDE_EFFORT or "(claude default)", encoding="utf-8")
    print(f"  -> claude: model={CLAUDE_MODEL or 'default'} effort={CLAUDE_EFFORT or 'default'} file-handoff -> {out_file.name}")
    try:
        proc = subprocess.run(cmd, stdin=subprocess.DEVNULL, cwd=str(repo),
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=PER_AGENT_TIMEOUT)
        write_process_log(log_file, proc.stdout or "", proc.stderr or "")
    except subprocess.TimeoutExpired:
        print(f"  [FAILED] claude (timeout after {PER_AGENT_TIMEOUT}s)")
        return False
    ok = collect_review("claude", out_file, log_file, proc.returncode, proc.stdout or "")
    print(f"  [{'OK' if ok else 'FAILED'}] claude (rc={proc.returncode}) -> {out_file.name}")
    return ok


RUNNERS = {"codex": run_codex, "antigravity": run_agy, "claude": run_claude}
AGENT_ALIASES = {
    "codex": "codex",
    "antigravity": "antigravity",
    "agy": "antigravity",
    "claude": "claude",
}
DRIVER_ALIASES = {
    **AGENT_ALIASES,
    "none": None,
    "all": None,
    "external": None,
    "standalone": None,
    "chatgpt": "codex",
    "gemini": "antigravity",
    "cowork": "claude",
    "claude-code": "claude",
}
DEFAULT_RUNNERS = ["codex", "antigravity", "claude"]


def normalize_driver(raw):
    if raw is None:
        return "auto"
    key = raw.strip().lower()
    if key == "":
        return "auto"
    if key == "auto":
        return "auto"
    if key in DRIVER_ALIASES:
        return DRIVER_ALIASES[key]
    raise ValueError(raw)


def detect_driver():
    """Best-effort host detection. Return (driver, source), where driver is one
    of codex/antigravity/claude or None when standalone/full-panel."""
    env_driver = os.environ.get("KIBITZ_DRIVER")
    if env_driver:
        try:
            driver = normalize_driver(env_driver)
        except ValueError:
            sys.exit(f"ERROR: unknown KIBITZ_DRIVER={env_driver!r}; "
                     f"use auto, none, codex, claude, antigravity, or agy")
        if driver != "auto":
            return driver, "KIBITZ_DRIVER"

    env = os.environ
    if env.get("CODEX_SHELL") or env.get("CODEX_THREAD_ID") or env.get("CODEX_INTERNAL_ORIGINATOR_OVERRIDE"):
        return "codex", "Codex environment"
    if env.get("AGY") or env.get("ANTIGRAVITY") or env.get("ANTIGRAVITY_CLI"):
        return "antigravity", "Antigravity environment"
    if env.get("CLAUDECODE") or env.get("CLAUDE_CODE") or env.get("CLAUDE_DESKTOP"):
        return "claude", "Claude environment"
    return None, "standalone"


def main() -> None:
    global PER_AGENT_TIMEOUT
    ap = argparse.ArgumentParser(
        description="kibitz local-agent fan-out (driver-aware Codex/Antigravity/Claude)")
    ap.add_argument("problem", nargs="?", help="the plan / problem text to harden")
    ap.add_argument("--doc", help="path to an existing plan .md (instead of inline text)")
    ap.add_argument("--round", choices=["r1", "r2", "r3", "r4"], default="r1")
    ap.add_argument("--topic", default="kibitz", help="short slug for the run folder")
    ap.add_argument("--repo", type=Path, default=Path.cwd())
    ap.add_argument("--profile", action="append", default=[], metavar="{comfyui|path}",
                    help="append a domain profile. Use 'comfyui' for the shipped ComfyUI profile; "
                         "repeatable. A repo-local .kibitz/comfyui.local.md auto-adds comfyui.")
    ap.add_argument("--no-profiles", action="store_true",
                    help="disable requested profiles and .kibitz/comfyui.local.md auto-detection.")
    ap.add_argument("--only", action="append", metavar="{codex,antigravity,agy,claude}",
                    help="run only this agent (repeatable). Overrides driver-aware defaults.")
    ap.add_argument("--driver", default="auto",
                    metavar="{auto,none,codex,claude,antigravity,agy}",
                    help="active driver to exclude from default reviewers. Default: auto.")
    ap.add_argument("--all-agents", action="store_true",
                    help="run codex + antigravity + claude, ignoring detected driver.")
    ap.add_argument("--with-claude", action="store_true",
                    help="compatibility flag: include Claude even if the driver-aware default excludes it.")
    ap.add_argument("--dry-run", action="store_true",
                    help="print selected driver/agents and exit without calling agents.")
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

    detected_driver, driver_source = detect_driver()
    try:
        explicit_driver = normalize_driver(args.driver)
    except ValueError:
        ap.error(f"unknown driver: {args.driver} "
                 f"(choose auto, none, codex, claude, antigravity/agy)")
    driver = detected_driver if explicit_driver == "auto" else explicit_driver

    if args.only:
        selected = []
        for raw_name in args.only:
            name = AGENT_ALIASES.get(raw_name.lower())
            if name is None:
                ap.error(f"unknown agent for --only: {raw_name} "
                         f"(choose codex, antigravity/agy, or claude)")
            if name not in selected:
                selected.append(name)
    elif args.all_agents:
        selected = list(DEFAULT_RUNNERS)
    else:
        selected = [name for name in DEFAULT_RUNNERS if name != driver]
    if args.with_claude and "claude" not in selected:
        selected.append("claude")
    if not selected:
        selected = list(DEFAULT_RUNNERS)
    date = datetime.date.today().isoformat()
    run_dir = repo / "kibitz-runs" / f"{date}-{args.topic}" / args.round
    run_dir.mkdir(parents=True, exist_ok=True)
    input_path = run_dir / "input.md"
    input_path.write_text(input_text, encoding="utf-8")

    profile_entries, profile_text = load_profiles(repo, args.profile, args.no_profiles)
    profiles_used = "\n".join(f"{label}: {path}" for label, path in profile_entries) or "(none)"
    (run_dir / "profiles_used.txt").write_text(profiles_used + "\n", encoding="utf-8")

    prompt = (load_round_prompt(args.round)
              + profile_text
              + GROUNDING_FOOTER.format(input_path=input_path.as_posix()))

    print(f"Repo:       {repo}")
    print(f"Round:      {args.round}")
    print(f"Run folder: {run_dir}")
    print(f"Driver:     {driver or 'none'} ({driver_source if explicit_driver == 'auto' else 'explicit'})")
    print(f"Agents:     {', '.join(selected)}")
    print(f"Profiles:   {', '.join(label for label, _path in profile_entries) if profile_entries else 'none'}")
    if args.dry_run:
        print("Dry run:    no agents called")
        return
    print("Fanning out (each agent reads the repo + writes its review to a FILE):")

    results = {}
    for name in selected:
        results[name] = RUNNERS[name](
            prompt, repo, run_dir / f"{name}.md", run_dir / f"{name}.log")

    print("\nReviews collected:")
    for name, ok in results.items():
        print(f"  {name}: {'OK' if ok else 'FAILED - check the .log'}")
    print("\nNext (the driver, NOT the script):")
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
#  - Codex: `codex exec -C <repo> --sandbox read-only --json --color never -o <file> <prompt>`
#    writes the final answer to <file>.
#  - Antigravity: headless `agy -p` swallows stdout when redirected; the file-handoff
#    (tell agy to write its review to <file> + --dangerously-skip-permissions) works.
#    The `| clip` clipboard bypass does NOT work (still a stdout redirect = empty).
#  - Claude: `claude -p` has no native -o flag, so it uses the same file-handoff
#    pattern as agy. Prompt is passed as an arg.
#  - Never scrape terminal output for DONE/FINISHED. Never set a short subprocess timeout
#    unless you explicitly want to bail on a hung agent (use --timeout for that).
# ---------------------------------------------------------------------------
