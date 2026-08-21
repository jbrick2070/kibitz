#!/usr/bin/env python3
"""kibitz.py - local-agent fan-out for the kibitz skill (FILE-HANDOFF contract).

Fans ONE hardening pass out to local file-reading CLI agents - Codex
(`codex exec`), Antigravity (`agy`), Claude Code (`claude -p`), and Cursor
(`agent -p`). Each reads your REAL repo on its own and returns an independent
review. No API key, no copy-paste. Python standard library only: no pip install,
no third-party dependencies.

ONE FAMILY PER SEAT: codex=GPT, agy=Gemini, claude=Claude, cursor=Grok. The point
of the panel is four INDEPENDENT readings, so pointing a multi-model launcher at a
family another lane already holds collapses its value. See the DIVERSITY RULE below.

THE HOST BOUNDARY: a driver never reviews itself. If Codex is driving, the codex
CLI is not a second opinion - it is the same system grading its own homework, and
the same goes for agy driving agy, Claude driving Claude, and Cursor driving Cursor.
So the default panel is driver-aware: it is all four lanes MINUS the detected
driver. Driving from Claude/Cowork runs codex + antigravity + cursor; driving from
Cursor runs codex + antigravity + claude. With no driver detected, all four run.
Use `--driver` or `KIBITZ_DRIVER` to make the driver explicit, and repeated `--only`
flags for manual fallbacks. `--only agy` is an alias for `--only antigravity`;
`--only agent` and `--only cursor-agent` are aliases for `--only cursor`.

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
  * Cursor: the odd one out, and the best-postured of the four. `--mode ask` is
    genuinely read-only, so it CANNOT write a handoff file and does not need to:
    its review is captured from STDOUT, which Cursor does not swallow. It needs
    no --force and no skip-permissions. The prompt goes in on STDIN, because the
    Windows launcher is a .cmd behind cmd.exe and a real round prompt is well past
    cmd.exe's 8191-character ceiling.

Usage:
  python kibitz.py --doc plan.md --round r2 --repo /path/to/repo
  python kibitz.py --doc plan.md --round r2 --repo /path/to/repo --profile comfyui
  python kibitz.py --doc plan.md --round r2 --repo /path/to/repo --driver codex
  python kibitz.py --doc plan.md --round r2 --repo /path/to/repo --driver none
  python kibitz.py --doc plan.md --round r3 --only codex --only claude
  python kibitz.py --doc plan.md --round r3 --only agy
  python kibitz.py --doc plan.md --round r3 --only cursor
  python kibitz.py --doc plan.md --round r3 --only claude
  python kibitz.py --doc plan.md --round r3 --driver codex --dry-run
  python kibitz.py "harden the ending-mode plan" --round r1
  python kibitz.py --doc plan.md --round r1 --timeout 600

Configuration is via CLI args and environment variables only -- no hardcoded paths.
  KIBITZ_CODEX_REASONING  Codex reasoning effort (default "high"; "xhigh" retries to "high").
  KIBITZ_CODEX_MODEL      Codex model slug pin, validated against the live catalog
                          (e.g. "gpt-5.6-sol"; "" = auto-pick strongest). A slug the
                          catalog does not list warns and falls back rather than failing.
  KIBITZ_AGY_MODEL        Antigravity picker display name (default "Gemini 3.7 Flash (High)"; "" = agy default).
  KIBITZ_CURSOR_MODEL     Cursor model id (default "cursor-grok-4.6-high"; "" = cursor default).
                          Keep this on GROK -- see the DIVERSITY RULE.
  KIBITZ_CURSOR_MODE      Cursor execution mode, ask or plan (default "ask"). Both are
                          read-only; the lane never gets write access.
  KIBITZ_CURSOR_BIN       Directory holding the Cursor launcher. Overrides the default
                          %LOCALAPPDATA%\\cursor-agent lookup and PATH.
  KIBITZ_CLAUDE_BUDGET    Claude spend tier: low, medium, high, or plan (default "medium").
  KIBITZ_CLAUDE_MODEL     Claude model alias/slug override ("" = Claude default).
  KIBITZ_CLAUDE_EFFORT    Claude effort override (low/medium/high/max; "" = Claude default).
  KIBITZ_DRIVER           Active driver: auto, none, codex, claude, antigravity/agy.
  KIBITZ_QUOTA_CHECK      Set to 0/false/no to skip non-prompt quota preflight checks.
  KIBITZ_QUOTA_WARN_THRESHOLDS
                           Comma list of usage warning thresholds (default "50,70,90").
  KIBITZ_QUOTA_RETRY_AFTER Suggested retry window after quota exhaustion (default "1h").
  KIBITZ_QUOTA_SCAN_ALL_RECENT
                          Set to 1 to scan every CLI log in the lookback window
                          for quota markers. Default 0 = newest log only, so a
                          lane that has since recovered is not blocked by a
                          stale failure.
  KIBITZ_<AGENT>_USAGE_PERCENT
                           Optional explicit usage percent for codex, agy, or claude.

SAFETY: Codex and Cursor run read-only (hard guarantee: Cursor's ask mode has no
write tool, and the lane passes neither --force nor --yolo). Antigravity runs UNSANDBOXED
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
# Cursor ships the CLI as agent.cmd/.ps1 in this directory, with the real payload under
# versions/<YYYY.MM.DD-hash>/. The CLI is standalone: the Cursor EDITOR does not have to
# be installed, and on this machine never was.
_WIN_CURSOR_BIN = os.path.expandvars(r"%LOCALAPPDATA%\cursor-agent")


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


#: Cursor's launcher is agent.cmd / agent.ps1 -- NOT an .exe, so the generic
#: _extra_candidates rglob (which only looks for name + ".exe") cannot find it.
#: "agent" is also a dangerously generic name to take off PATH, so the install
#: directory is searched FIRST and a bare PATH hit is only a last resort.
_CURSOR_LAUNCHERS = ("cursor-agent.cmd", "agent.cmd", "cursor-agent.exe", "agent.exe")


def _which_cursor(extra_dir: str = ""):
    """Resolve the Cursor CLI launcher.

    Order: KIBITZ_CURSOR_BIN, then the known install directory, then PATH. The
    install directory beats PATH because "agent" is a dangerously generic name to
    pick up from PATH; KIBITZ_CURSOR_BIN beats both so a non-standard install -- or
    an offline test stub -- can point this lane wherever it needs to go.
    """
    configured = os.environ.get("KIBITZ_CURSOR_BIN", "").strip()
    # KIBITZ_CURSOR_BIN may name the launcher itself, not just its directory --
    # pointing an override at an executable is the obvious thing to try.
    if configured and Path(configured).is_file():
        return configured
    for base in (Path(configured or "."), Path(extra_dir or _WIN_CURSOR_BIN)):
        if str(base) == "." or not base.is_dir():
            continue
        for candidate in _CURSOR_LAUNCHERS:
            path = base / candidate
            if path.is_file():
                return str(path)
    for name in ("cursor-agent", "agent"):
        found = shutil.which(name)
        if found and not _is_windowsapps_alias(found):
            return found
    return None


#: Matches "cursor-grok-4.6-high" / "gemini-3.1-pro" style ids from `agent --list-models`.
_CURSOR_MODEL_LINE = re.compile(r"^\s*(?P<slug>[a-z0-9][a-z0-9.\-]*)\s+-\s+(?P<name>.+?)\s*$")


# Codex model + reasoning policy: poll the LIVE catalog via `codex debug models`, prefer the
# strongest non-mini model, default reasoning_effort="high". xhigh is model-dependent -> try
# only if asked, retry once with high on failure. See COMPAT.md.
CODEX_REASONING = os.environ.get("KIBITZ_CODEX_REASONING", "high")

# ---------------------------------------------------------------------------
# NAMING A MODEL: three different things, and mixing them up is how lanes go
# stale. The split is NOT api-vs-cli -- all three appear on both sides.
#
#   SLUG          the machine identifier: "gpt-5.6-sol", "gemini-3.1-pro-high",
#                 "claude-opus-5". What `agy models` prints, what an API wants.
#   ALIAS         an identifier that RESOLVES to whatever is current:
#                 "~openai/gpt-latest", or the Claude CLI's bare "opus" /
#                 "sonnet" / "haiku". Self-updating.
#   PIN           not a kind of name -- the ACT of fixing on one specific
#                 version so it cannot move. You pin a slug.
#
#   ...and agy is the awkward one: its --model wants neither the slug nor an
#   alias but the PICKER DISPLAY NAME, "Gemini 3.7 Flash (High)", parentheses
#   included, while `agy models` shows you slugs.
#
# THE RULE THIS BUYS: aliases do not rot; pinned slugs do. Both stale lanes
# found on 2026-08-17 were pinned (Codex's preference tuple, agy's display
# name), and the Claude lane -- which uses bare aliases -- had not drifted at
# all. Prefer an alias unless you specifically need a frozen version, and if you
# must pin, re-verify it against the live catalog when a campaign starts.
# ---------------------------------------------------------------------------

# Explicit model pin, VALIDATED against the live catalog; "" (default) = poll catalog +
# preference order. A pin is a REQUEST, not a command: pick_codex_model accepts it only
# when `codex debug models` actually lists it, so a slug that has been renamed or retired
# degrades to the catalog preference with a warning instead of failing the whole leg on
# an invalid-model error. Same reasoning as the pin-rot block below.
CODEX_MODEL_REQUEST = os.environ.get("KIBITZ_CODEX_MODEL", "").strip() or None
#: STALE PREFERENCE IS A SILENT DOWNGRADE (2026-07-27). This tuple read
#: ("gpt-5.5", "gpt-5-codex", "gpt-5") while the live catalog already carried
#: gpt-5.6-sol / -luna / -terra, so every arc quietly ran the older model and
#: only ``codex_model_selected.txt`` said so. The auto-pick FALLBACK below
#: (highest "gpt-5*" slug by reverse sort) would have chosen gpt-5.6-terra --
#: alphabetically last, not strongest -- so the fallback cannot be trusted to
#: age gracefully either. Keep the operator's model of record FIRST.
CODEX_MODEL_PREFERENCE = ("gpt-5.6-sol", "gpt-5.5", "gpt-5-codex", "gpt-5")
# Antigravity has NO reasoning flag -- reasoning rides the picker display name's
# parenthesized level. `agy models` exposes discovery slugs, but --model requires
# the exact PICKER DISPLAY NAME, parentheses and all.
#
# REFRESHED 2026-08-17 against live `agy models`, which listed:
#   gemini-3.7-flash-high/medium/low, gemini-3.6-flash-*, gemini-3.5-flash-*,
#   gemini-3.1-pro-high/low, claude-sonnet-4-6, claude-opus-4-6-thinking,
#   gpt-oss-120b-medium
# The default was "Gemini 3.6 Flash (High)" while 3.7 Flash had shipped, so every
# arc quietly ran a generation behind -- the SAME stale-pin failure recorded on
# CODEX_MODEL_PREFERENCE above. Both 3.7 Flash (High) and 3.1 Pro (High) returned
# real reviews the day this was refreshed, so both are proven, not guessed.
# 3.1 Pro is the CURRENT Pro lane (there is no 3.6/3.7 Pro) -- it is not "older",
# and the previous wording here said so incorrectly.
#
# TWO PROVEN LANES, and running BOTH in one round is the cheap way to get a
# second opinion when Codex is unavailable:
#   KIBITZ_AGY_MODEL="Gemini 3.7 Flash (High)"   (default, fast)
#   KIBITZ_AGY_MODEL="Gemini 3.1 Pro (High)"     (slower, needs a raised
#                                                 KIBITZ_AGY_PRINT_TIMEOUT)
# Give each lane its OWN --topic, or the second overwrites the first's review.
#
# DIVERSITY RULE (do NOT casually change): agy is MULTI-MODEL -- it can run Gemini AND
# claude-opus / claude-sonnet / gpt-oss. Keep agy on GEMINI. With four lanes the
# families must stay one-per-seat:
#     codex = GPT      agy = Gemini      claude = Claude      cursor = Grok
# agy=Opus duplicates Claude, agy=gpt-oss duplicates Codex, and a cursor lane pointed
# at Codex 5.3 or Claude Opus 5 duplicates two seats at once -- each collapses the
# panel's whole value, which is FOUR independent readings of the same code.
AGY_MODEL = os.environ.get("KIBITZ_AGY_MODEL", "Gemini 3.7 Flash (High)")
# A PRINT TIMEOUT IS NOT A QUOTA BLOCK (2026-08-17). `--timeout` on this script
# does NOT reach agy; this env var builds agy's own --print-timeout. The Pro lane
# died twice on "Error: timeout waiting for response" at the old 5m default and
# landed first try at 15m, while `agy models` returned rc=0 throughout -- so read
# the error before declaring a lane exhausted.
AGY_PRINT_TIMEOUT = os.environ.get("KIBITZ_AGY_PRINT_TIMEOUT", "15m")

# Cursor is the MOST multi-model launcher of the four -- `agent --list-models` returns
# roughly 200 ids spanning GPT, Claude, Gemini, Grok, Kimi, GLM and Composer. That makes
# the DIVERSITY RULE above matter MORE here, not less: this seat is Grok, because Grok is
# the only family the other three lanes cannot supply. Kimi K3 and GLM 5.2 are the
# defensible alternates if Grok is ever unavailable; GPT / Claude / Gemini are NOT, since
# each duplicates a seat the panel already holds.
#
# The pinned slug WILL rot -- Cursor's catalog is the largest and fastest-moving here, and
# this repo has already been bitten twice by stale pins that silently downgraded every
# arc. `--check-pins` validates this one against the live catalog for exactly that reason.
# `auto` exists and never rots, but it surrenders family control and would quietly break
# the diversity rule, so it is deliberately NOT the default.
#
# PRIVACY: every claude-fable-5-* id in Cursor's catalog is labelled "(NO ZDR)" -- no zero
# data retention. Do not select one as a silent default; it is a privacy change, not just
# a model change.
CURSOR_MODEL = os.environ.get("KIBITZ_CURSOR_MODEL", "cursor-grok-4.6-high").strip()
#: Read-only review posture. `ask` is Q&A-style and read-only, and is the mode actually
#: proven on this platform; `plan` is also read-only but untested here. Neither can edit,
#: so the lane never needs --force / --yolo and never gets write access at all.
#:
#: ALLOWLISTED, not passed through. Cursor's default agent mode HAS a write tool, so an
#: unrecognised KIBITZ_CURSOR_MODE reaching --mode would silently hand a reviewer the
#: ability to edit the repo it is reviewing. Read-only here is a guarantee, not a hope.
CURSOR_READ_ONLY_MODES = ("ask", "plan")
_requested_cursor_mode = os.environ.get("KIBITZ_CURSOR_MODE", "ask").strip().lower()
CURSOR_MODE = _requested_cursor_mode if _requested_cursor_mode in CURSOR_READ_ONLY_MODES else "ask"
#: Set when the requested mode was rejected, so run_cursor can say so out loud.
CURSOR_MODE_OVERRIDDEN = (
    f"KIBITZ_CURSOR_MODE={_requested_cursor_mode!r} is not a known READ-ONLY mode "
    f"({', '.join(CURSOR_READ_ONLY_MODES)}); forcing 'ask'. A reviewer must not be "
    f"able to write to the repo it is reviewing."
    if _requested_cursor_mode and _requested_cursor_mode not in CURSOR_READ_ONLY_MODES
    else ""
)
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
# A CLI-LOG MARKER WARNS; IT NO LONGER BLOCKS (default flipped 2026-08-18).
# Antigravity hits 429s internally, retries, and succeeds: a log from a run that
# produced a full 7.6 KB review carried 5x RESOURCE_EXHAUSTED and 4x "code 429".
# So a log marker is evidence about the provider's rate limiter, NOT evidence
# that this invocation will fail, and blocking on it costs a whole reviewer seat
# for a lane that would have answered. Same reasoning the pin check already uses:
# it warns, never blocks, because failing the run costs more than the drift.
# Direct evidence still blocks -- `output_quota_diagnostic` reads the agent's own
# output and sees whether THIS call actually died.
# Set KIBITZ_QUOTA_BLOCK_ON_RECENT=1 to restore log-marker blocking.
QUOTA_BLOCK_ON_RECENT = os.environ.get("KIBITZ_QUOTA_BLOCK_ON_RECENT", "0").strip().lower() in (
    "1", "true", "yes", "on",
)
# Scan every CLI log in the lookback window instead of only the newest one.
# OFF by default: a lane that failed and has since succeeded is not blocked.
# See agy_log_quota_diagnostic for why the newest log is the authority.
QUOTA_SCAN_ALL_RECENT = os.environ.get("KIBITZ_QUOTA_SCAN_ALL_RECENT", "0").strip().lower() in (
    "1", "true", "yes", "on",
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
    "cursor": "Cursor",
}


#: Matches "gemini-3.7-flash-high" style discovery slugs from `agy models`.
_AGY_SLUG = re.compile(r"^(?P<family>[a-z]+)-(?P<ver>\d+(?:\.\d+)?)-(?P<lane>[a-z]+)")


def _agy_catalog(exe: str) -> list[tuple[str, str]]:
    """(slug, display_name) pairs from `agy models`. [] if it cannot be read."""
    try:
        proc = subprocess.run([exe, "models"], capture_output=True, text=True,
                              timeout=90)
    except Exception:
        return []
    pairs = []
    for line in (proc.stdout or "").splitlines():
        parts = [p.strip() for p in line.split("\t") if p.strip()]
        if len(parts) >= 2 and _AGY_SLUG.match(parts[0]):
            pairs.append((parts[0], parts[1]))
    return pairs


def agy_pin_warnings(exe: str) -> list[str]:
    """Warn when the configured agy pin is invalid or a generation behind.

    A PIN THAT IS ONLY CHECKED BY HAND GOES STALE -- twice in one week here
    (the Codex preference tuple and this display name), and in both cases the
    arc kept running happily on the older model with nothing but a receipt file
    to say so. This is deliberately a WARNING and never an error: a stale pin
    still produces a real review, so blocking the run would cost more than the
    drift does.
    """
    catalog = _agy_catalog(exe)
    if not catalog:
        return []
    warnings: list[str] = []
    by_display = {display: slug for slug, display in catalog}
    if AGY_MODEL and AGY_MODEL not in by_display:
        return [f"KIBITZ_AGY_MODEL={AGY_MODEL!r} is not in `agy models`; "
                f"--model needs the exact picker display name. Available: "
                f"{', '.join(sorted(by_display)[:6])}..."]
    pinned_slug = by_display.get(AGY_MODEL, "")
    match = _AGY_SLUG.match(pinned_slug)
    if not match:
        return warnings
    family, lane = match.group("family"), match.group("lane")
    pinned_ver = float(match.group("ver"))
    newest = pinned_ver
    newest_display = AGY_MODEL
    for slug, display in catalog:
        other = _AGY_SLUG.match(slug)
        if not other or other.group("family") != family:
            continue
        # Compare like with like: a Flash pin is not stale because a Pro exists.
        if other.group("lane") != lane or slug.split("-")[2] != pinned_slug.split("-")[2]:
            continue
        ver = float(other.group("ver"))
        if ver > newest:
            newest, newest_display = ver, display
    if newest > pinned_ver:
        warnings.append(
            f"agy pin is a generation behind: using {AGY_MODEL!r} while "
            f"{newest_display!r} is available. Set KIBITZ_AGY_MODEL to refresh, "
            f"or update the default in this script."
        )
    return warnings


def _cursor_catalog(exe: str) -> list[tuple[str, str]]:
    """(slug, display_name) pairs from `agent --list-models`. [] if unreadable."""
    try:
        proc = subprocess.run([exe, "--list-models"], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=90)
    except Exception:  # noqa: BLE001
        return []
    pairs = []
    for line in (proc.stdout or "").splitlines():
        match = _CURSOR_MODEL_LINE.match(line)
        if match:
            pairs.append((match.group("slug"), match.group("name")))
    return pairs


def _version_tuple(raw: str) -> tuple:
    """Compare versions COMPONENT-WISE, not as floats.

    float("4.10") is 4.1, which sorts BELOW 4.6 -- so a float comparison would decide
    that a future Grok 4.10 is older than today's 4.6 and silently keep the stale pin.
    This is the same silent-downgrade class the pin check exists to catch, so it must
    not be reintroduced by the check itself.
    """
    parts = []
    for chunk in str(raw).split("."):
        try:
            parts.append(int(chunk))
        except ValueError:
            parts.append(0)
    return tuple(parts)


#: Splits "cursor-grok-4.6-high" into ("cursor-grok", 4.6, "high") so a pin is only
#: compared against its OWN family and effort lane -- a Grok High pin is not stale
#: because a Gemini exists, or because a Grok Low is newer.
_CURSOR_SLUG = re.compile(r"^(?P<family>[a-z][a-z0-9-]*?)-(?P<ver>\d+(?:\.\d+)?)-(?P<lane>[a-z0-9-]+)$")


#: Model-id prefixes mapped to the family they belong to. Used to enforce the
#: one-family-per-seat rule at runtime instead of only in a comment.
_CURSOR_FAMILY_PREFIXES = (
    ("cursor-grok", "grok"),
    ("grok", "grok"),
    ("claude", "claude"),
    ("gpt", "gpt"),
    ("composer", "composer"),
    ("gemini", "gemini"),
    ("kimi", "kimi"),
    ("glm", "glm"),
)
#: Families another lane already holds. Selecting one for the Cursor seat does not
#: fail the run -- the operator may be deliberately testing -- but it must never be
#: silent, because the whole value of the panel is four INDEPENDENT readings.
_FAMILIES_HELD_BY_OTHER_LANES = {
    "gpt": "codex",
    "composer": "codex",
    "gemini": "antigravity",
    "claude": "claude",
}


def cursor_model_family(model: str) -> str:
    """Best-effort family name for a Cursor model id ('' if unrecognised)."""
    low = (model or "").strip().lower()
    for prefix, family in _CURSOR_FAMILY_PREFIXES:
        if low.startswith(prefix):
            return family
    # Cursor vendors some ids behind its own name ("cursor-grok-..."). Strip that and
    # retry, so a hypothetical "cursor-claude-..." is still recognised as claude-family
    # rather than falling through as unknown and skipping the duplication check.
    if low.startswith("cursor-"):
        return cursor_model_family(low[len("cursor-"):])
    return ""


def cursor_family_warning() -> str:
    """Warn when the Cursor seat duplicates a family another lane already holds.

    THE RULE THIS ENFORCES: codex=GPT, agy=Gemini, claude=Claude, cursor=Grok. Cursor
    can serve ~200 ids across every family, so this seat is the easiest of the four to
    point somewhere that quietly collapses the panel into three opinions wearing four
    names. A comment cannot catch that; this can.
    """
    if not CURSOR_MODEL:
        return ("KIBITZ_CURSOR_MODEL is empty, so this lane runs whatever Cursor's own "
                "default happens to be -- which may duplicate another lane's family. "
                "Pin a Grok id to keep the four seats independent.")
    family = cursor_model_family(CURSOR_MODEL)
    owner = _FAMILIES_HELD_BY_OTHER_LANES.get(family)
    if owner:
        return (f"KIBITZ_CURSOR_MODEL={CURSOR_MODEL!r} is {family}-family, which the "
                f"{owner!r} lane already holds. The panel is only worth four calls if "
                f"the families are distinct -- prefer a Grok id (or Kimi/GLM).")
    if family and family != "grok":
        return ""
    if not family:
        return (f"KIBITZ_CURSOR_MODEL={CURSOR_MODEL!r} is not a recognised family; "
                f"cannot confirm it does not duplicate another lane.")
    return ""


def cursor_pin_warnings(exe: str) -> list[str]:
    """Warn when the configured Cursor pin is invalid or a generation behind.

    Cursor's catalog is the largest and fastest-moving of the four lanes, so this pin
    is the most likely of them to rot. Like the agy check this WARNS and never blocks:
    a stale pin still returns a real review, and killing the run would cost the seat.
    An INVALID pin is the one that actually breaks a leg, so it is reported first.
    """
    if not CURSOR_MODEL:
        return []
    catalog = _cursor_catalog(exe)
    if not catalog:
        # An unreadable catalog is NOT a clean bill of health. Returning [] here made
        # --check-pins print "cursor pin is current" after a CLI error or a parse miss,
        # which is worse than saying nothing -- it is a stale pin wearing a green light.
        return ["cursor catalog unreadable (`agent --list-models` returned nothing "
                "parseable); the pin was NOT verified."]
    slugs = [slug for slug, _display in catalog]
    if CURSOR_MODEL not in slugs:
        sample = ", ".join(s for s in slugs if s.startswith("cursor-grok"))[:160]
        return [f"KIBITZ_CURSOR_MODEL={CURSOR_MODEL!r} is not in `agent --list-models`; "
                f"the lane will fail on an invalid model. Grok ids available: "
                f"{sample or '(none)'}"]
    match = _CURSOR_SLUG.match(CURSOR_MODEL)
    if not match:
        return []
    family, lane = match.group("family"), match.group("lane")
    pinned_ver = _version_tuple(match.group("ver"))
    newest, newest_slug = pinned_ver, CURSOR_MODEL
    for slug in slugs:
        other = _CURSOR_SLUG.match(slug)
        if not other:
            continue
        if other.group("family") != family or other.group("lane") != lane:
            continue
        ver = _version_tuple(other.group("ver"))
        if ver > newest:
            newest, newest_slug = ver, slug
    if newest > pinned_ver:
        return [f"cursor pin is a generation behind: using {CURSOR_MODEL!r} while "
                f"{newest_slug!r} is available. Set KIBITZ_CURSOR_MODEL to refresh, "
                f"or update the default in this script."]
    return []


def report_pin_freshness(exe: str, run_dir: "Path | None" = None) -> list[str]:
    """Print (and optionally record) any stale-pin warnings. Never raises."""
    try:
        warnings = agy_pin_warnings(exe)
    except Exception as exc:  # pragma: no cover - a check must never break a run
        return [f"pin check skipped ({type(exc).__name__}: {exc})"]
    for warning in warnings:
        print(f"  [PIN] {warning}")
        if run_dir is not None:
            append_quota_warning(run_dir, warning)
    return warnings


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
    that exact slug. This prevents stale/private model names in config or the
    environment from turning a review into an avoidable invalid-model failure.

    Every branch writes codex_model_resolution.txt, so which model actually ran --
    and why -- is on disk next to the review instead of inferred afterwards.
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
TOOL HEALTH CHECK (DO THIS FIRST): Before reviewing anything, confirm your own file tools
actually work. Open ONE real source file in the repo under review and confirm you can read its
contents. If ANY tool call fails, errors, is blocked, or returns nothing -- STOP. Do not write a
review. Instead write ONLY this to the output file, with the error text quoted verbatim:
  TOOL CHECK: FAIL
  <the verbatim error>
  I cannot read the repository.
A refusal is a USEFUL answer and costs the driver nothing. A review written without file access
is WORSE THAN NO ANSWER, because it looks like evidence and gets folded into a plan. This check
exists because a lane once returned a confident, well-formatted trace whose middle steps read
"summary | summary | standard processing applied" while asserting it was proven from the real
filesystem, and named a file and a class that do not exist -- rc was 0 and nothing caught it.
NEVER pad a report to keep its shape. If you cannot trace a step, write "UNTRACED -- could not
follow". An honest gap is worth more than a smooth chain, and placeholder filler now FAILS the
leg automatically.

OUTPUT CONTRACT (MANDATORY): You are a READ-ONLY reviewer. Do NOT modify, create, or delete any
file EXCEPT the single output file below. Write your COMPLETE review (only the review, in the
structure specified above) to this exact path, then stop:
  {out_path}
Do not rely on stdout. After writing the file, exit immediately.
"""

# Cursor runs in a read-only mode that CANNOT write, so it gets the same tool-health
# gate with the opposite output channel. Do NOT hand this lane FILE_OUTPUT_DIRECTIVE:
# that directive orders a Write and says "Do not rely on stdout", so on a lane whose
# write tool is blocked it manufactures a guaranteed false failure -- the agent hits the
# health check, cannot write, dutifully emits "I cannot read the repository", and the
# leg is failed for a tool it was never given. Granting --force to satisfy the
# convention would be strictly worse: it trades a read-only reviewer for a writable one
# to no benefit. The collector already falls back to stdout, so nothing else changes.
STDOUT_OUTPUT_DIRECTIVE = """

------------------------------------------------------------------
TOOL HEALTH CHECK (DO THIS FIRST): Before reviewing anything, confirm your own file tools
actually work. Open ONE real source file in the repo under review and confirm you can read its
contents. If ANY tool call fails, errors, is blocked, or returns nothing -- STOP. Do not write a
review. Instead print ONLY this, with the error text quoted verbatim:
  TOOL CHECK: FAIL
  <the verbatim error>
  I cannot read the repository.
A refusal is a USEFUL answer and costs the driver nothing. A review written without file access
is WORSE THAN NO ANSWER, because it looks like evidence and gets folded into a plan. NEVER pad a
report to keep its shape. If you cannot trace a step, write "UNTRACED -- could not follow". An
honest gap is worth more than a smooth chain, and placeholder filler FAILS the leg automatically.

OUTPUT CONTRACT (MANDATORY): You are a READ-ONLY reviewer and you have NO write tool. Do NOT
attempt to create, modify, or delete any file, and do not ask for permission to do so. Print your
COMPLETE review -- only the review, in the structure specified above -- to STDOUT, then exit
immediately. Your stdout IS the deliverable: no preamble, no trailing commentary, no summary of
what you just wrote.
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
        "cursor": ("KIBITZ_CURSOR_USAGE_PERCENT", "KIBITZ_CURSOR_QUOTA_PERCENT"),
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
    """Detect Antigravity quota/backend exhaustion in recent CLI logs.

    A LANE'S STATE IS ITS LATEST STATE, NOT ITS WORST STATE IN THE WINDOW.
    This used to scan every log in the lookback window (default 1h) and block on
    the first one carrying a quota marker. Because the list is newest-first, a
    clean recent run did not clear an older failure -- it was simply skipped on
    the way to the stale one. Observed 2026-08-18: a 429 at 18:32 blocked the
    lane at 19:03 with two clean runs (18:46, 19:03) in between, and the retry
    reported the SAME 18:32 log. The lane had recovered half an hour earlier and
    kibitz refused to call it, so the round ran a reviewer short for no reason.

    So: inspect the newest log only. A quota block is a CURRENT condition, and
    the newest log is the only evidence of the current condition. If a lane
    failed and has since succeeded, it is not blocked.

    This trades a preflight false-POSITIVE (blocking a healthy lane, which costs
    a whole reviewer seat and is invisible unless someone reads the log paths)
    for a possible false-NEGATIVE (letting a doomed call through). That trade is
    deliberate and cheap: a genuinely exhausted lane still fails on its own
    output, and `output_quota_diagnostic` catches the marker from the attempt
    itself -- later than preflight, but from reality rather than from history.

    Set KIBITZ_QUOTA_SCAN_ALL_RECENT=1 to restore the scan-the-whole-window
    behaviour.
    """
    paths = recent_agy_log_files(started_at, lookback_seconds)
    if not paths:
        return ""
    # recent_agy_log_files sorts newest-first.
    scan = paths if QUOTA_SCAN_ALL_RECENT else paths[:1]
    for path in scan:
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
        "cursor": [["status", "--format", "text"]],
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


#: Markers of a review written WITHOUT working file access.
#:
#: An agent whose tools are broken does not fail loudly -- it returns a
#: confident, well-formatted report, so exit code and non-emptiness both pass.
#: Observed 2026-08-17: an Antigravity lane returned a code trace whose middle
#: steps read "summary | summary | summary | Standard processing applied" while
#: asserting it was "proven from the real filesystem", and named a source file
#: and a class that do not exist. The operator had separately hit a telemetry
#: plugin crash that killed that agent's tool execution outright.
#:
#: These tells are STRUCTURAL, not factual -- they need no knowledge of the repo
#: under review, which is what makes them safe to apply to every lane.
#: FILLER tells: padding a grounded reviewer never emits. Safe to match ANYWHERE,
#: because no honest review contains them at all.
UNREADABLE_REVIEW_FILLER_MARKERS = (
    "standard processing applied",
    "initial logic and parameters are validated",
)

#: REFUSAL tells: the exact wording FILE_OUTPUT_DIRECTIVE asks a tool-blind agent to
#: emit. These are NOT safe to match anywhere -- a genuine, grounded review that
#: ANALYSES the refusal path quotes them verbatim, and a bare substring match then
#: discards it. That is not hypothetical: on 2026-08-21 a 10,110-byte Cursor review
#: citing real line numbers was failed for the single quoted phrase
#: '"I cannot read the repository,"' inside its own argument about false fails --
#: the exact outcome this function's docstring warns about.
#:
#: The discriminator is SHAPE, not wording. FILE_OUTPUT_DIRECTIVE tells a blocked
#: agent to write ONLY the refusal, so a real refusal is SHORT and the marker sits at
#: the TOP. A review that merely quotes the phrase is long and buries it mid-document.
UNREADABLE_REVIEW_REFUSAL_MARKERS = (
    "i cannot read the repository",
    "cannot read the repository",
    "unable to access the file",
)

#: The explicit sentinel the output directives mandate. Anchored to the START OF THE
#: DOCUMENT (\A, no MULTILINE) because the directive says to LEAD with it.
#:
#: This was briefly written as `^...` + MULTILINE, which matches the sentinel on ANY
#: line -- and both output directives quote that line themselves, indented. So any
#: grounded review that quoted the output contract while reasoning about the refusal
#: path was discarded, with a VERDICT and 7,600 characters of findings, which is the
#: very false-positive class this whole function exists to prevent. Caught by the
#: Cursor lane reviewing its own implementation, 2026-08-21. Do not re-add MULTILINE.
_TOOL_CHECK_FAIL = re.compile(r"\A\s*tool check:\s*fail", re.IGNORECASE)

#: A refusal written per the directive is far shorter than any real review.
REFUSAL_MAX_CHARS = 2000
#: Every round prompt demands a VERDICT line, so a document carrying a refusal marker
#: but NO verdict is a refusal however long it grew. This closes the gap a pure length
#: test leaves: a blocked agent that dumps a large verbatim error before its refusal
#: line would otherwise sail past REFUSAL_MAX_CHARS and be accepted as a review.
REVIEW_STRUCTURE_MARKERS = ("verdict:", "must-fix", "should-fix")

#: A chain/table row that is literally the word "summary" in several columns.
_PLACEHOLDER_ROW = re.compile(r"\|\s*summary\s*\|\s*summary\s*\|", re.IGNORECASE)


def unreadable_review_diagnostic(review: str) -> str:
    """Return a reason string if this review looks written without file access.

    Empty string means it looks genuine. Deliberately conservative: it fires
    only on filler no grounded reviewer would emit, because a false positive
    here silently discards a real review.
    """
    low = review.lower()
    for marker in UNREADABLE_REVIEW_FILLER_MARKERS:
        if marker in low:
            return f"contains the placeholder/failure marker {marker!r}"
    # The EXPLICIT SENTINEL. FILE_OUTPUT_DIRECTIVE / STDOUT_OUTPUT_DIRECTIVE tell a
    # tool-blind agent to lead with this exact line, so finding it at the start of a
    # line is decisive on its own.
    if _TOOL_CHECK_FAIL.search(review):
        return "contains the placeholder/failure marker 'tool check: fail'"
    # Otherwise the discriminator is SHAPE, not wording. A blocked agent is told to
    # write ONLY the refusal, so a real refusal carries no VERDICT / MUST-FIX
    # structure. A grounded review that merely QUOTES a refusal phrase while
    # reasoning about the refusal path does -- and it must survive, because that
    # exact false positive threw away a 10,110-byte review citing real line numbers
    # on 2026-08-21. Matching these generic English phrases anywhere is what broke it.
    has_structure = any(marker in low for marker in REVIEW_STRUCTURE_MARKERS)
    if has_structure and len(low) > REFUSAL_MAX_CHARS:
        return ""
    for marker in UNREADABLE_REVIEW_REFUSAL_MARKERS:
        if marker in low:
            return f"contains the placeholder/failure marker {marker!r}"
    if _PLACEHOLDER_ROW.search(review):
        return "chain rows are filled with the literal word 'summary'"
    return ""


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
    if ok:
        # A NON-EMPTY review can still be evidence-free. Fail the leg rather
        # than hand the driver something that reads like grounding and is not:
        # the entire value of this panel is that claims can be checked against
        # the real files, and a review written blind cannot be.
        unreadable = unreadable_review_diagnostic(review)
        if unreadable:
            msg = (f"{name}: review looks written WITHOUT file access -- "
                   f"{unreadable}. Failing this leg; re-run once the agent's "
                   f"tools are confirmed working.")
            print(f"  [FAILED] {msg}")
            append_process_log(log_file, msg)
            ok = False
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
    model_receipt = (
        f"MODEL: {AGY_MODEL or '(agy default)'}\n"
        f"ARGV (prompt omitted): {cmd[:-1]!r}"
    )
    write_process_log(log_file, "", "", extra=model_receipt)
    started_at = time.time()
    try:
        proc = subprocess.run(cmd, stdin=subprocess.DEVNULL, text=True, cwd=str(repo),
                              capture_output=True, encoding="utf-8", errors="replace",
                              timeout=PER_AGENT_TIMEOUT)
        write_process_log(log_file, proc.stdout or "", proc.stderr or "", extra=model_receipt)
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


def run_cursor(prompt: str, repo: Path, out_file: Path, log_file: Path) -> bool:
    """Cursor CLI: READ-ONLY (--mode ask), prompt on STDIN, review captured from STDOUT.

    The only lane of the four that needs no write access at all -- ask mode cannot edit,
    so there is no --force, no --dangerously-skip-permissions, and no file-handoff.
    --trust is required for every headless run: without it Cursor exits rc=1 with
    "Workspace Trust Required" no matter which repo it is pointed at.
    """
    # Clear the stale review FIRST, before any early return. collect_review reads the
    # FILE before stdout, so a previous run's cursor.md left behind by a not-found or
    # preflight-blocked leg would be read as THIS run's answer -- and
    # record_failure_diagnostic would append its note to that stale review, producing
    # something that reads like a fresh graded result and is not.
    if out_file.exists():
        out_file.unlink()
    run_dir = out_file.parent

    exe = _which_cursor()
    if exe is None:
        log_file.write_text(
            r"cursor CLI not found: looked in KIBITZ_CURSOR_BIN, then "
            r"%LOCALAPPDATA%\cursor-agent, then PATH for 'cursor-agent'/'agent'",
            encoding="utf-8")
        print("  x cursor: command not found")
        return False
    if CURSOR_MODE_OVERRIDDEN:
        print(f"  [MODE] {CURSOR_MODE_OVERRIDDEN}")
        append_quota_warning(run_dir, CURSOR_MODE_OVERRIDDEN)
    family_warning = cursor_family_warning()
    if family_warning:
        print(f"  [FAMILY] {family_warning}")
        append_quota_warning(run_dir, family_warning)
    preflight_blocker = quota_preflight("cursor", exe, repo, run_dir)
    if preflight_blocker:
        record_failure_diagnostic("cursor", out_file, log_file, preflight_blocker)
        print("  [FAILED] cursor (quota preflight)")
        return False

    full = prompt + STDOUT_OUTPUT_DIRECTIVE
    cmd = [exe, "-p", "--trust", "--mode", CURSOR_MODE, "--output-format", "text"]
    if CURSOR_MODEL:
        cmd += ["--model", CURSOR_MODEL]
    (run_dir / "cursor_model_selected.txt").write_text(
        "\n".join([
            f"requested={CURSOR_MODEL or '(cursor default)'}",
            f"family={cursor_model_family(CURSOR_MODEL) or '(unknown)'}",
            f"mode={CURSOR_MODE}",
            f"exe={exe}",
        ]) + "\n",
        encoding="utf-8")

    # THE PROMPT GOES ON STDIN, NEVER IN ARGV. agent.cmd re-invokes PowerShell through
    # cmd.exe (8191-char ceiling) and a real round prompt runs past 10,000, so as an
    # argument it dies instantly with "The command line is too long." There is
    # deliberately NO automatic fallback transport: retrying on failure cannot tell a
    # transport problem from a refusal or a bad review, so it would discard a genuine
    # "TOOL CHECK: FAIL" answer and pay for a second call to re-ask the same question.
    # If stdin ever stops working, this must fail loudly and be fixed here.
    print(f"  -> cursor: model={CURSOR_MODEL or 'default'} mode={CURSOR_MODE} "
          f"transport=stdin read-only -> stdout")
    receipt = (f"MODEL: {CURSOR_MODEL or '(cursor default)'}\n"
               f"MODE: {CURSOR_MODE}\n"
               f"TRANSPORT: stdin\n"
               f"ARGV (prompt omitted): {cmd!r}")
    write_process_log(log_file, "", "", extra=receipt)
    started_at = time.time()
    try:
        proc = subprocess.run(
            cmd, cwd=str(repo), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=PER_AGENT_TIMEOUT,
            input=full,
        )
        write_process_log(log_file, proc.stdout or "", proc.stderr or "", extra=receipt)
    except subprocess.TimeoutExpired as exc:
        diagnostic = quota_diagnostic("cursor", started_at,
                                      safe_text(exc.stdout), safe_text(exc.stderr))
        record_failure_diagnostic("cursor", out_file, log_file, diagnostic)
        print(f"  [FAILED] cursor (timeout after {PER_AGENT_TIMEOUT}s)")
        return False
    ok = collect_review("cursor", out_file, log_file, proc.returncode, proc.stdout or "")
    if not ok:
        diagnostic = quota_diagnostic("cursor", started_at,
                                      proc.stdout or "", proc.stderr or "")
        if diagnostic:
            record_failure_diagnostic("cursor", out_file, log_file, diagnostic)
    print(f"  [{'OK' if ok else 'FAILED'}] cursor "
          f"(rc={proc.returncode}, model={CURSOR_MODEL or 'default'})")
    return ok


RUNNERS = {
    "codex": run_codex,
    "antigravity": run_agy,
    "claude": run_claude,
    "cursor": run_cursor,
}
AGENT_ALIASES = {
    "codex": "codex",
    "antigravity": "antigravity",
    "agy": "antigravity",
    "claude": "claude",
    "cursor": "cursor",
    "cursor-agent": "cursor",
    "agent": "cursor",
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
    "grok": "cursor",
}
# THE HOST BOUNDARY, and it is the whole reason this list is filtered by driver:
# a reviewer must be an INDEPENDENT reading of the code. If Codex is driving, the codex
# CLI is not a second opinion -- it is the same system grading its own homework, and the
# same is true of agy driving agy, Claude driving Claude, and Cursor driving Cursor.
# main() removes the detected driver from this list, so with Claude driving from Cowork a
# round runs codex + antigravity + cursor: three families, none of them the host.
DEFAULT_RUNNERS = ["codex", "antigravity", "claude", "cursor"]


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
                     f"use auto, none, codex, claude, antigravity/agy, or cursor")
        if driver != "auto":
            return driver, "KIBITZ_DRIVER"

    env = os.environ
    if env.get("CODEX_SHELL") or env.get("CODEX_THREAD_ID") or env.get("CODEX_INTERNAL_ORIGINATOR_OVERRIDE"):
        return "codex", "Codex environment"
    if env.get("AGY") or env.get("ANTIGRAVITY") or env.get("ANTIGRAVITY_CLI"):
        return "antigravity", "Antigravity environment"
    if env.get("CLAUDECODE") or env.get("CLAUDE_CODE") or env.get("CLAUDE_DESKTOP"):
        return "claude", "Claude environment"
    # Verified by asking the Cursor CLI to dump its own environment, 2026-08-21.
    # Without this the host boundary silently breaks the moment cursor joins the
    # default panel: a kibitz run driven from Cursor would launch the Cursor CLI as
    # one of its own reviewers and call a self-review an independent opinion.
    if env.get("CURSOR_AGENT") or env.get("CURSOR_CONVERSATION_ID") or env.get("CURSOR_INVOKED_AS"):
        return "cursor", "Cursor environment"
    return None, "standalone"


def main() -> None:
    global PER_AGENT_TIMEOUT
    ap = argparse.ArgumentParser(
        description="kibitz local-agent fan-out (driver-aware Codex/Antigravity/Claude/Cursor)")
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
    ap.add_argument("--only", action="append",
                    metavar="{codex,antigravity,agy,claude,cursor}",
                    help="run only this agent (repeatable). Overrides driver-aware defaults.")
    ap.add_argument("--driver", default="auto",
                    metavar="{auto,none,codex,claude,antigravity,agy,cursor}",
                    help="active driver to exclude from default reviewers. A host never "
                         "reviews itself. Default: auto.")
    ap.add_argument("--all-agents", action="store_true",
                    help="run codex + antigravity + claude + cursor, ignoring the detected "
                         "driver. This CAN make a host review itself -- use deliberately.")
    ap.add_argument("--with-claude", action="store_true",
                    help="compatibility flag: include Claude even if the driver-aware default excludes it.")
    ap.add_argument("--dry-run", action="store_true",
                    help="print selected driver/agents and exit without calling agents.")
    ap.add_argument("--timeout", type=float, default=None,
                    help="per-agent timeout in seconds (default: none -- agents batch).")
    ap.add_argument("--check-pins", action="store_true",
                    help="check the configured model pins against the live "
                         "catalogs, print any that are stale, and exit. Run "
                         "this at install and at the start of a campaign.")
    args = ap.parse_args()

    if args.check_pins:
        # Install-time / start-of-campaign check. A pin only ever verified by
        # hand goes stale silently -- the arc keeps running a generation behind
        # and only a receipt file records it.
        agy_exe = _which("agy", _WIN_AGY_BIN)
        if not agy_exe:
            print("  [PIN] agy not found on PATH; skipping the antigravity pin check.")
        else:
            print(f"  [PIN] configured antigravity lane: {AGY_MODEL!r}")
            if not report_pin_freshness(agy_exe):
                print("  [PIN] antigravity pin is current.")
        cursor_exe = _which_cursor()
        if not cursor_exe:
            print("  [PIN] cursor CLI not found; skipping the cursor pin check.")
        else:
            print(f"  [PIN] configured cursor lane: {CURSOR_MODEL!r}")
            try:
                cursor_warnings = cursor_pin_warnings(cursor_exe)
            except Exception as exc:  # pragma: no cover - a check must never break a run
                cursor_warnings = [f"cursor pin check skipped ({type(exc).__name__}: {exc})"]
            for warning in cursor_warnings:
                print(f"  [PIN] {warning}")
            if not cursor_warnings:
                print("  [PIN] cursor pin is current.")
        print(f"  [PIN] codex preference order: {', '.join(CODEX_MODEL_PREFERENCE)}")
        print("  [PIN] claude lane uses ALIASES (haiku/sonnet/opus), which do "
              "not rot -- nothing to refresh.")
        return 0

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
                 f"(choose auto, none, codex, claude, antigravity/agy, cursor)")
    driver = detected_driver if explicit_driver == "auto" else explicit_driver

    if args.only:
        selected = []
        for raw_name in args.only:
            name = AGENT_ALIASES.get(raw_name.lower())
            if name is None:
                ap.error(f"unknown agent for --only: {raw_name} "
                         f"(choose codex, antigravity/agy, claude, or cursor)")
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
#  - Cursor: `agent -p --trust --mode ask --model <id> --output-format text`, with the
#    PROMPT ON STDIN and the review read from STDOUT.
#      * --trust is MANDATORY headless. Without it every run exits rc=1 with
#        "Workspace Trust Required", on any drive, however many times you have run it
#        before. It is also all that is needed -- no trust records are written to the
#        user's Cursor config.
#      * THE PROMPT MUST NOT BE AN ARGV ELEMENT. agent.cmd re-invokes PowerShell through
#        cmd.exe (8191-char ceiling) and a real round prompt exceeds 10,000. As argv it
#        dies in 0.1s with "The command line is too long." -- while every short smoke
#        test still passes, which is exactly how this ships broken. Proven 2026-08-21.
#      * Do NOT give this lane FILE_OUTPUT_DIRECTIVE. Ask mode has no write tool, so a
#        directive ordering a file write manufactures a guaranteed false failure.
#      * The Cursor EDITOR is NOT required. The CLI is standalone.
#  - Never scrape terminal output for DONE/FINISHED. Never set a short subprocess timeout
#    unless you explicitly want to bail on a hung agent (use --timeout for that).
# ---------------------------------------------------------------------------
