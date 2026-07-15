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
  KIBITZ_CODEX_MODEL      Codex model slug pin (e.g. "gpt-5.6-sol"; "" = auto-pick strongest).
  KIBITZ_AGY_MODEL        Antigravity display-name slug (default "Gemini 3.5 Flash (High)"; "" = agy default).
  KIBITZ_CLAUDE_BUDGET    Claude spend tier: low, medium, high, or plan (default "medium").
  KIBITZ_CLAUDE_MODEL     Claude model alias/slug override ("" = Claude default).
  KIBITZ_CLAUDE_EFFORT    Claude effort override (low/medium/high/max; "" = Claude default).
  KIBITZ_DRIVER           Active driver: auto, none, codex, claude, antigravity/agy.
  KIBITZ_QUOTA_CHECK      Set to 0/false/no to skip non-prompt quota preflight checks.
  KIBITZ_QUOTA_WARN_THRESHOLDS
                           Comma list of usage warning thresholds (default "50,70,90").
  KIBITZ_QUOTA_RETRY_AFTER Suggested retry window after quota exhaustion (default "1h").
  KIBITZ_<AGENT>_USAGE_PERCENT
                           Optional explicit usage percent for codex, agy, or claude.

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
import re
import shutil
import subprocess
import sys
import time
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


def _is_windowsapps_alias(path: str) -> bool:
    return "\\windowsapps\\" in str(path).lower().replace("/", "\\")


def _extra_candidates(name: str, extra_dirs: tuple[str, ...]) -> list[str]:
    found = []
    for d in extra_dirs:
        p = Path(d)
        if p.is_dir():
            for cand in p.rglob(name + ".exe"):
                found.append(str(cand))
    return found


def _which(name: str, *extra_dirs: str):
    exe = shutil.which(name)
    extras = _extra_candidates(name, extra_dirs)
    if exe and not _is_windowsapps_alias(exe):
        return exe
    if extras:
        return extras[0]
    if exe:
        return exe
    return None


# Codex model + reasoning policy: poll the LIVE catalog via `codex debug models`, prefer the
# strongest non-mini model, default reasoning_effort="high". xhigh is model-dependent -> try
# only if asked, retry once with high on failure. See COMPAT.md.
CODEX_REASONING = os.environ.get("KIBITZ_CODEX_REASONING", "high")
# Explicit model pin wins over auto-pick; "" (default) = poll catalog + preference order.
CODEX_MODEL_REQUEST = os.environ.get("KIBITZ_CODEX_MODEL", "").strip() or None
# Keep private/rollout names as live-catalog preferences only. They are never
# passed to Codex unless `codex debug models` confirms the exact slug exists.
CODEX_MODEL_PREFERENCE = (
    "gpt-5.6-sol",
    "gpt-5.6-terra",
    "gpt-5.6-luna",
    "gpt-5.5",
    "gpt-5-codex",
    "gpt-5",
)
# AgY has no separate reasoning flag and expects display-name slugs with spaces
# and parentheses, e.g. "Gemini 3.1 Pro (High)".
# DIVERSITY RULE (do NOT casually change): agy is MULTI-MODEL -- it can run Gemini AND
# claude-opus / claude-sonnet / gpt-oss. Keep agy on GEMINI: Codex is GPT-family
# and Claude Code can supply the Claude-family lane, so agy=Gemini gives three
# DISTINCT model families; agy=Opus duplicates Claude and agy=gpt-oss duplicates
# Codex, collapsing the panel's whole value.
AGY_MODEL = os.environ.get("KIBITZ_AGY_MODEL", "Gemini 3.5 Flash (High)")
AGY_PRINT_TIMEOUT = os.environ.get("KIBITZ_AGY_PRINT_TIMEOUT", "5m")
CLAUDE_BUDGET = os.environ.get("KIBITZ_CLAUDE_BUDGET", "medium").strip().lower()
CLAUDE_MODEL_ENV = os.environ.get("KIBITZ_CLAUDE_MODEL")
CLAUDE_EFFORT_ENV = os.environ.get("KIBITZ_CLAUDE_EFFORT")
CLAUDE_BUDGET_PROFILES = {
    "low": ("haiku", "medium"),
    "cheap": ("haiku", "medium"),
    "medium": ("sonnet", "high"),
    "med": ("sonnet", "high"),
    "standard": ("sonnet", "high"),
    "high": ("opus", "max"),
    "deep": ("opus", "max"),
    "plan": ("opusplan", "high"),
    "opusplan": ("opusplan", "high"),
}

QUOTA_CHECK_ENABLED = os.environ.get("KIBITZ_QUOTA_CHECK", "1").strip().lower() not in (
    "0", "false", "no", "off",
)
QUOTA_STATUS_TIMEOUT = float(os.environ.get("KIBITZ_QUOTA_STATUS_TIMEOUT", "15"))
QUOTA_WARN_THRESHOLDS_RAW = os.environ.get("KIBITZ_QUOTA_WARN_THRESHOLDS", "50,70,90")
QUOTA_RETRY_AFTER_RAW = os.environ.get("KIBITZ_QUOTA_RETRY_AFTER", "1h")
QUOTA_LOG_LOOKBACK_SECONDS = float(os.environ.get("KIBITZ_QUOTA_LOG_LOOKBACK_SECONDS", "3600"))
QUOTA_BLOCK_ON_RECENT = os.environ.get("KIBITZ_QUOTA_BLOCK_ON_RECENT", "1").strip().lower() not in (
    "0", "false", "no", "off",
)

QUOTA_MARKERS = (
    "resource_exhausted",
    "insufficient_quota",
    "code 429",
    '"code": 429',
    "http 429",
    "429 too many requests",
    "too many requests",
    "check quota",
    "quota reached",
    "quota limit",
    "quota exceeded",
    "usage limit",
    "limit reached",
    "rate limit",
    "rate_limit",
    "credit balance",
    "out of credits",
    "individual quota",
    "contact your administrator to enable overages",
    "enable overages",
)
AGY_QUOTA_MARKERS = QUOTA_MARKERS
AGY_LOG_LOOKBACK_SECONDS = float(os.environ.get("KIBITZ_AGY_LOG_LOOKBACK_SECONDS", "60"))

AGENT_LABELS = {
    "codex": "Codex",
    "antigravity": "Antigravity",
    "claude": "Claude",
}


def resolve_claude_budget():
    """Return (budget, model, effort, note) for the Claude reviewer lane."""
    budget = CLAUDE_BUDGET or "medium"
    note = ""
    if budget not in CLAUDE_BUDGET_PROFILES:
        note = f"unknown KIBITZ_CLAUDE_BUDGET={budget!r}; using medium"
        budget = "medium"
    profile_model, profile_effort = CLAUDE_BUDGET_PROFILES[budget]
    model = CLAUDE_MODEL_ENV if CLAUDE_MODEL_ENV is not None else profile_model
    effort = CLAUDE_EFFORT_ENV if CLAUDE_EFFORT_ENV is not None else profile_effort
    return budget, model, effort, note


def pick_codex_model(exe: str, repo: Path, run_dir: Path):
    """Poll `codex debug models`, log it, pick the strongest non-mini model. Returns a slug or
    None (let Codex use its default). Never picks mini/fast/spark unless nothing else exists.

    An explicit KIBITZ_CODEX_MODEL is accepted only when the live catalog lists
    that exact slug. This prevents stale/private model names from causing an
    avoidable invalid-model failure.
    """
    import json as _json
    resolution_file = run_dir / "codex_model_resolution.txt"
    try:
        raw = (subprocess.run([exe, "debug", "models"], cwd=str(repo), stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=120).stdout
               or "")
    except Exception:  # noqa: BLE001
        resolution_file.write_text(
            "catalog=unavailable\n"
            f"requested={CODEX_MODEL_REQUEST or '(none)'}\n"
            "selected=(codex default)\n",
            encoding="utf-8",
        )
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
    if CODEX_MODEL_REQUEST:
        if CODEX_MODEL_REQUEST in slugs:
            resolution_file.write_text(
                "catalog=available\n"
                f"requested={CODEX_MODEL_REQUEST}\n"
                f"selected={CODEX_MODEL_REQUEST}\n",
                encoding="utf-8",
            )
            return CODEX_MODEL_REQUEST
        resolution_file.write_text(
            "catalog=available\n"
            f"requested={CODEX_MODEL_REQUEST}\n"
            "selected=(automatic catalog preference)\n"
            "reason=requested slug is absent from the live catalog\n"
            f"available={','.join(slugs) or '(none)'}\n",
            encoding="utf-8",
        )
        print(
            f"  [WARN] codex: requested model {CODEX_MODEL_REQUEST!r} is not in the live catalog; "
            "using an available catalog model"
        )
    for pref in CODEX_MODEL_PREFERENCE:
        if pref in slugs:
            resolution_file.write_text(
                "catalog=available\n"
                f"requested={CODEX_MODEL_REQUEST or '(none)'}\n"
                f"selected={pref}\n",
                encoding="utf-8",
            )
            return pref
    g5 = sorted((s for s in slugs if s.startswith("gpt-5")), reverse=True)
    selected = g5[0] if g5 else None
    resolution_file.write_text(
        "catalog=available\n"
        f"requested={CODEX_MODEL_REQUEST or '(none)'}\n"
        f"selected={selected or '(codex default)'}\n",
        encoding="utf-8",
    )
    return selected


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


def parse_quota_thresholds(raw: str) -> list[float]:
    thresholds = []
    for part in raw.split(","):
        part = part.strip().rstrip("%")
        if not part:
            continue
        try:
            value = float(part)
        except ValueError:
            continue
        if 0 <= value <= 100 and value not in thresholds:
            thresholds.append(value)
    return sorted(thresholds)


def parse_duration_seconds(raw: str) -> int:
    text = raw.strip().lower()
    if not text:
        return 3600
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([smhd]?)", text)
    if not match:
        return 3600
    value = float(match.group(1))
    unit = match.group(2) or "s"
    multiplier = {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]
    seconds = int(value * multiplier)
    return max(60, seconds)


def format_duration(seconds: int) -> str:
    if seconds % 86400 == 0:
        return f"{seconds // 86400}d"
    if seconds % 3600 == 0:
        return f"{seconds // 3600}h"
    if seconds % 60 == 0:
        return f"{seconds // 60}m"
    return f"{seconds}s"


QUOTA_WARN_THRESHOLDS = parse_quota_thresholds(QUOTA_WARN_THRESHOLDS_RAW) or [50.0, 70.0, 90.0]


def safe_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def redact_status_text(text: str) -> str:
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "<email>", text)
    text = re.sub(r'("(?:access|refresh|id)_?token"\s*:\s*")[^"]+', r"\1<redacted>", text)
    text = re.sub(r'("(?:api[_-]?key|secret)"\s*:\s*")[^"]+', r"\1<redacted>", text, flags=re.I)
    return text


def usage_percent_from_env(agent: str):
    keys_by_agent = {
        "codex": ("KIBITZ_CODEX_USAGE_PERCENT", "KIBITZ_CODEX_QUOTA_PERCENT"),
        "antigravity": (
            "KIBITZ_ANTIGRAVITY_USAGE_PERCENT",
            "KIBITZ_AGY_USAGE_PERCENT",
            "KIBITZ_ANTIGRAVITY_QUOTA_PERCENT",
            "KIBITZ_AGY_QUOTA_PERCENT",
        ),
        "claude": ("KIBITZ_CLAUDE_USAGE_PERCENT", "KIBITZ_CLAUDE_QUOTA_PERCENT"),
    }
    for key in keys_by_agent.get(agent, ()):
        raw = os.environ.get(key)
        if raw is None or raw.strip() == "":
            continue
        text = raw.strip().rstrip("%")
        try:
            return float(text), key
        except ValueError:
            return None, f"{key} (unparseable: {raw!r})"
    return None, ""


def usage_percent_from_text(text: str):
    patterns = (
        r"\b(?:usage|used|credits?|quota|limit|budget)[^\n\r%]{0,80}?(\d{1,3}(?:\.\d+)?)\s*%",
        r"(\d{1,3}(?:\.\d+)?)\s*%[^\n\r]{0,80}\b(?:usage|used|credits?|quota|limit|budget)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I)
        if not match:
            continue
        try:
            return float(match.group(1))
        except ValueError:
            continue
    return None


def quota_marker_lines(text: str, limit: int = 6) -> list[str]:
    if not text:
        return []
    lines = [
        line.strip()
        for line in text.splitlines()
        if any(marker in line.lower() for marker in QUOTA_MARKERS)
    ]
    return lines[-limit:]


def append_quota_warning(run_dir: Path, message: str) -> None:
    warning_file = run_dir / "quota_warnings.md"
    with warning_file.open("a", encoding="utf-8") as handle:
        handle.write(f"- {datetime.datetime.now().isoformat(timespec='seconds')} {message}\n")


def reached_threshold(percent: float):
    reached = [threshold for threshold in QUOTA_WARN_THRESHOLDS if percent >= threshold]
    return reached[-1] if reached else None


def run_status_command(exe: str, args: list[str], repo: Path) -> str:
    label = " ".join([Path(exe).name] + args)
    try:
        proc = subprocess.run(
            [exe] + args,
            cwd=str(repo),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=QUOTA_STATUS_TIMEOUT,
        )
    except Exception as exc:  # noqa: BLE001
        return f"$ {label}\nFAILED: {exc}\n"
    output = []
    output.append(f"$ {label}")
    output.append(f"rc={proc.returncode}")
    if proc.stdout:
        output.append("STDOUT:\n" + redact_status_text(proc.stdout.rstrip()))
    if proc.stderr:
        output.append("STDERR:\n" + redact_status_text(proc.stderr.rstrip()))
    return "\n".join(output).rstrip() + "\n"


def recent_agy_log_files(started_at: float, lookback_seconds: float = AGY_LOG_LOOKBACK_SECONDS) -> list[Path]:
    """Return recent Antigravity CLI logs that could belong to this agy run."""
    base = Path.home() / ".gemini" / "antigravity-cli"
    candidates = []
    direct = base / "cli.log"
    if direct.is_file():
        candidates.append(direct)
    log_dir = base / "log"
    if log_dir.is_dir():
        candidates.extend(log_dir.glob("*.log"))

    cutoff = started_at - lookback_seconds
    recent = []
    for path in candidates:
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if mtime >= cutoff:
            recent.append((mtime, path))
    recent.sort(reverse=True)
    return [path for _mtime, path in recent[:8]]


def tail_text(path: Path, max_bytes: int = 200_000) -> str:
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - max_bytes))
            data = handle.read()
    except OSError:
        return ""
    return data.decode("utf-8", errors="replace")


def output_quota_diagnostic(agent: str, stdout_text: str = "", stderr_text: str = "") -> str:
    """Detect quota/backend exhaustion in an agent's own output."""
    combined = "\n".join(part for part in (stdout_text, stderr_text) if part)
    lines = quota_marker_lines(combined)
    if lines:
        label = AGENT_LABELS.get(agent, agent)
        return (
            f"{label} quota/rate-limit marker detected in agent output:\n"
            + "\n".join(lines)
        )
    return ""


def agy_log_quota_diagnostic(started_at: float, lookback_seconds: float = AGY_LOG_LOOKBACK_SECONDS) -> str:
    """Detect Antigravity quota/backend exhaustion in recent CLI logs."""
    for path in recent_agy_log_files(started_at, lookback_seconds):
        text = tail_text(path)
        lines = quota_marker_lines(text)
        if not lines:
            continue
        excerpt = "\n".join(lines)
        if excerpt:
            return (
                "Antigravity quota/backend exhaustion detected in recent CLI log "
                f"{path}:\n{excerpt}"
            )
        return f"Antigravity quota/backend exhaustion detected in recent CLI log {path}."
    return ""


def quota_diagnostic(agent: str, started_at: float, stdout_text: str = "", stderr_text: str = "") -> str:
    diagnostic = output_quota_diagnostic(agent, stdout_text, stderr_text)
    if diagnostic:
        return diagnostic
    if agent == "antigravity":
        return agy_log_quota_diagnostic(started_at, AGY_LOG_LOOKBACK_SECONDS)
    return ""


def agy_quota_diagnostic(started_at: float, stdout_text: str = "", stderr_text: str = "") -> str:
    """Backward-compatible wrapper for Antigravity quota/backend detection."""
    return quota_diagnostic("antigravity", started_at, stdout_text, stderr_text)


def quota_preflight(agent: str, exe: str, repo: Path, run_dir: Path) -> str:
    """Write a cheap per-agent quota/auth status file. Return a hard quota blocker, if any."""
    status_file = run_dir / f"{agent}_quota_status.txt"
    label = AGENT_LABELS.get(agent, agent)
    if not QUOTA_CHECK_ENABLED:
        status_file.write_text("quota_check=disabled\n", encoding="utf-8")
        return ""

    commands = {
        "codex": [["login", "status"]],
        "antigravity": [["models"]],
        "claude": [["auth", "status"]],
    }.get(agent, [])
    command_text = "\n".join(run_status_command(exe, args, repo) for args in commands)
    percent, percent_source = usage_percent_from_env(agent)
    if percent is None:
        percent = usage_percent_from_text(command_text)
        if percent is not None:
            percent_source = "status output"

    lines = [
        f"agent={agent}",
        "quota_check=enabled",
        "thresholds=" + ",".join("%g" % threshold for threshold in QUOTA_WARN_THRESHOLDS),
    ]
    if percent is None:
        lines.append("usage_percent=unknown")
        if percent_source:
            lines.append(f"usage_percent_source={percent_source}")
    else:
        lines.append(f"usage_percent={percent:g}")
        lines.append(f"usage_percent_source={percent_source or 'detected'}")
        threshold = reached_threshold(percent)
        if threshold is not None:
            message = f"{label} usage {percent:g}% is at/above the {threshold:g}% warning threshold."
            print(f"  [QUOTA] {message}")
            append_quota_warning(run_dir, message)

    blocker = ""
    output_diagnostic = output_quota_diagnostic(agent, command_text, "")
    if output_diagnostic:
        lines.append("")
        lines.append("[quota diagnostic]")
        lines.append(output_diagnostic)
        print(f"  [QUOTA] {output_diagnostic.splitlines()[0]}")
        append_quota_warning(run_dir, output_diagnostic.splitlines()[0])
        blocker = output_diagnostic
    if agent == "antigravity":
        log_diagnostic = agy_log_quota_diagnostic(time.time(), QUOTA_LOG_LOOKBACK_SECONDS)
        if log_diagnostic:
            lines.append("")
            lines.append("[recent antigravity log diagnostic]")
            lines.append(log_diagnostic)
            print(f"  [QUOTA] {log_diagnostic.splitlines()[0]}")
            append_quota_warning(run_dir, log_diagnostic.splitlines()[0])
            blocker = blocker or log_diagnostic
    if command_text:
        lines.append("")
        lines.append("[status commands]")
        lines.append(command_text.rstrip())
    status_file.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return blocker if QUOTA_BLOCK_ON_RECENT else ""


def record_quota_hold(name: str, out_file: Path, diagnostic: str) -> None:
    label = AGENT_LABELS.get(name, name)
    seconds = parse_duration_seconds(QUOTA_RETRY_AFTER_RAW)
    retry_at = datetime.datetime.now().astimezone() + datetime.timedelta(seconds=seconds)
    retry_window = format_duration(seconds)
    summary = (
        f"{label} failed on quota/credit/rate-limit usage. Suggested retry after "
        f"{retry_window} ({retry_at.isoformat(timespec='minutes')})."
    )
    print(f"  [QUOTA] {summary}")
    print("  [QUOTA] Driver should ask the user when to retry, or continue without this lane.")
    append_quota_warning(out_file.parent, summary)
    hold_file = out_file.parent / f"{name}_quota_hold.md"
    hold_file.write_text(
        "\n".join([
            f"# {label} Quota Hold",
            "",
            summary,
            "",
            "Kibitz detected provider quota, credit, or rate-limit markers for this lane.",
            "The active driver should acknowledge this to the user and ask when to retry.",
            "If the user does not choose a time, use the suggested retry window above.",
            "",
            "To change the built-in retry window, set `KIBITZ_QUOTA_RETRY_AFTER`",
            "(examples: `30m`, `1h`, `4h`, `1d`) before rerunning Kibitz.",
            "",
            "## Diagnostic",
            "",
            diagnostic.strip(),
            "",
        ]),
        encoding="utf-8",
    )


def record_failure_diagnostic(name: str, out_file: Path, log_file: Path, diagnostic: str) -> None:
    if not diagnostic:
        return
    print(f"  [DIAG] {name}: {diagnostic.splitlines()[0]}")
    append_process_log(log_file, f"{name}: {diagnostic}")
    existing = ""
    if out_file.exists():
        existing = out_file.read_text(encoding="utf-8", errors="replace").rstrip()
    note = "[KIBITZ DIAGNOSTIC]\n" + diagnostic.strip()
    if existing:
        out_file.write_text(existing + "\n\n" + note + "\n", encoding="utf-8")
    else:
        out_file.write_text(note + "\n", encoding="utf-8")
    record_quota_hold(name, out_file, diagnostic)


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
    run_dir = out_file.parent
    preflight_blocker = quota_preflight("codex", exe, repo, run_dir)
    if preflight_blocker:
        record_failure_diagnostic("codex", out_file, log_file, preflight_blocker)
        print("  [FAILED] codex (quota preflight)")
        return False
    if out_file.exists():
        out_file.unlink()
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

    started_at = time.time()
    proc = _run(CODEX_REASONING)
    ok = collect_review("codex", out_file, log_file, proc.returncode, proc.stdout or "")
    diagnostic = "" if ok else quota_diagnostic("codex", started_at, proc.stdout or "", proc.stderr or "")
    if not ok and diagnostic:
        record_failure_diagnostic("codex", out_file, log_file, diagnostic)
    if not ok and not diagnostic and CODEX_REASONING == "xhigh":
        print("  .. xhigh failed -> retry once with high")
        (run_dir / "codex_reasoning_selected.txt").write_text("high (xhigh failed)",
                                                              encoding="utf-8")
        started_at = time.time()
        proc = _run("high")
        ok = collect_review("codex", out_file, log_file, proc.returncode, proc.stdout or "")
        if not ok:
            diagnostic = quota_diagnostic("codex", started_at, proc.stdout or "", proc.stderr or "")
            record_failure_diagnostic("codex", out_file, log_file, diagnostic)
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
    preflight_blocker = quota_preflight("antigravity", exe, repo, out_file.parent)
    if preflight_blocker:
        record_failure_diagnostic("antigravity", out_file, log_file, preflight_blocker)
        print("  [FAILED] antigravity (quota preflight)")
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
    started_at = time.time()
    try:
        proc = subprocess.run(cmd, stdin=subprocess.DEVNULL, text=True, cwd=str(repo),
                              capture_output=True, encoding="utf-8", errors="replace",
                              timeout=PER_AGENT_TIMEOUT)
        write_process_log(log_file, proc.stdout or "", proc.stderr or "")
    except subprocess.TimeoutExpired as exc:
        diagnostic = quota_diagnostic(
            "antigravity", started_at, safe_text(exc.stdout), safe_text(exc.stderr))
        record_failure_diagnostic("antigravity", out_file, log_file, diagnostic)
        print(f"  [FAILED] antigravity (timeout after {PER_AGENT_TIMEOUT}s)")
        return False
    ok = collect_review("antigravity", out_file, log_file, proc.returncode,
                        getattr(proc, "stdout", "") or "")
    if not ok:
        diagnostic = agy_quota_diagnostic(
            started_at, getattr(proc, "stdout", "") or "", getattr(proc, "stderr", "") or "")
        record_failure_diagnostic("antigravity", out_file, log_file, diagnostic)
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
    preflight_blocker = quota_preflight("claude", exe, repo, out_file.parent)
    if preflight_blocker:
        record_failure_diagnostic("claude", out_file, log_file, preflight_blocker)
        print("  [FAILED] claude (quota preflight)")
        return False
    if out_file.exists():
        out_file.unlink()
    full = prompt + FILE_OUTPUT_DIRECTIVE.format(out_path=str(out_file))
    claude_budget, claude_model, claude_effort, claude_budget_note = resolve_claude_budget()
    cmd = [
        exe,
        "-p",
        "--output-format", "text",
        "--no-session-persistence",
        "--dangerously-skip-permissions",
        "--tools", "Read,Glob,Grep,Write",
        "--add-dir", str(repo),
    ]
    if claude_model:
        cmd += ["--model", claude_model]
    if claude_effort:
        cmd += ["--effort", claude_effort]
    cmd.append(full)
    (out_file.parent / "claude_budget_selected.txt").write_text(
        "\n".join([
            f"budget={claude_budget}",
            f"model={claude_model or '(claude default)'}",
            f"effort={claude_effort or '(claude default)'}",
            f"note={claude_budget_note or '(none)'}",
        ]) + "\n",
        encoding="utf-8",
    )
    (out_file.parent / "claude_model_selected.txt").write_text(
        claude_model or "(claude default)", encoding="utf-8")
    (out_file.parent / "claude_effort_selected.txt").write_text(
        claude_effort or "(claude default)", encoding="utf-8")
    if claude_budget_note:
        print(f"  [WARN] claude: {claude_budget_note}")
    print(f"  -> claude: budget={claude_budget} model={claude_model or 'default'} effort={claude_effort or 'default'} file-handoff -> {out_file.name}")
    started_at = time.time()
    try:
        proc = subprocess.run(cmd, stdin=subprocess.DEVNULL, cwd=str(repo),
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=PER_AGENT_TIMEOUT)
        write_process_log(log_file, proc.stdout or "", proc.stderr or "")
    except subprocess.TimeoutExpired as exc:
        diagnostic = quota_diagnostic("claude", started_at, safe_text(exc.stdout), safe_text(exc.stderr))
        record_failure_diagnostic("claude", out_file, log_file, diagnostic)
        print(f"  [FAILED] claude (timeout after {PER_AGENT_TIMEOUT}s)")
        return False
    ok = collect_review("claude", out_file, log_file, proc.returncode, proc.stdout or "")
    if not ok:
        diagnostic = quota_diagnostic("claude", started_at, proc.stdout or "", proc.stderr or "")
        record_failure_diagnostic("claude", out_file, log_file, diagnostic)
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
                    help="run all external agents; the active driver is still excluded.")
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
    input_bytes = None
    if args.doc:
        doc_path = Path(args.doc)
        input_bytes = doc_path.read_bytes()
        try:
            input_text = input_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            sys.exit(f"ERROR: --doc must be UTF-8 text: {doc_path} ({exc})")
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
        if driver and driver in selected:
            selected.remove(driver)
            print(
                f"[WARN] {driver} is the active driver; its own CLI lane is excluded. "
                "Use --driver none --only " + driver + " only for an intentional standalone CLI test."
            )
    elif args.all_agents:
        selected = [name for name in DEFAULT_RUNNERS if name != driver]
    else:
        selected = [name for name in DEFAULT_RUNNERS if name != driver]
    if args.with_claude and "claude" not in selected:
        if driver != "claude":
            selected.append("claude")
    if not selected:
        if driver:
            ap.error(
                f"no external reviewers selected; active driver {driver!r} is not launched "
                "as its own CLI. Choose another --only agent, or use --driver none for a "
                "standalone CLI test."
            )
        selected = list(DEFAULT_RUNNERS)
    date = datetime.date.today().isoformat()
    run_dir = repo / "kibitz-runs" / f"{date}-{args.topic}" / args.round
    run_dir.mkdir(parents=True, exist_ok=True)
    input_path = run_dir / "input.md"
    if input_bytes is not None:
        # A continuation receipt hashes the predecessor final.md. Preserve that
        # exact byte stream in input.md; text-mode writes normalize LF/CRLF on
        # Windows and would make an honest resume hash impossible.
        input_path.write_bytes(input_bytes)
    else:
        with input_path.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(input_text)

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
    print("  1. Confirm the driver anchor was written before this fan-out; preserve it as driver_anchor.md.")
    print("  2. Verify every claim in the agent reviews against the real code; discard misreads.")
    print(f"  3. Record the judgment and merge survivors into {run_dir / 'final.md'}.")
    print("  4. Advance sequentially within the full arc or the explicit scoped/resume receipt.")

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
