# COMPAT.md - version-specific CLI flags and model policy

`SKILL.md` is the durable contract. This file is the volatile part: the exact
CLI flags, the model-selection policy, and the tool versions this was proven on.

> **These flags move fast. If a flag breaks, run `codex --help` / `agy --help`
> / `claude --help` and update this file - do not patch around it in the
> script.** The skill's design (file-handoff, read-only Codex, active-driver
> judge, driver-aware reviewer selection) is stable; only the surface flags
> below are expected to drift.

## Proven on

| Tool | Version proven | Notes |
|------|----------------|-------|
| Codex CLI (`codex`) | `0.142.5`, running model `gpt-5.5` | `codex exec` non-interactive mode |
| Antigravity (`agy`) | `1.0.16`, `1.1.5` | no `--headless`, no `--approve`; `agy models` is available for preflight |
| Claude Code (`claude`) | `2.1.72` | `claude -p` non-interactive mode |
| Cursor CLI (`agent`) | `2026.08.11-e8db854` | `agent -p` non-interactive; **prompt on STDIN**, review from STDOUT; standalone - the Cursor editor is NOT required |
| GitHub CLI (`gh`) | `2.89` | optional; only if you script repo setup |

These are the versions the invocations below were verified against. Newer
versions may rename or remove flags - check `--help` first.

## Quota, credit, and retry behavior

Kibitz performs a cheap, non-prompt quota/auth preflight for each selected lane
before it spends an agent call:

- Codex: `codex login status`
- Antigravity: `agy models`, plus recent Antigravity CLI logs
- Claude Code: `claude auth status`
- Cursor: `agent status --format text`

The preflight writes `<agent>_quota_status.txt` in the run folder. If Kibitz has
a real usage percentage, it warns at the configured thresholds (default
`KIBITZ_QUOTA_WARN_THRESHOLDS=50,70,90`) and appends to `quota_warnings.md`.
Current Codex, Antigravity, and Claude Code status surfaces do not reliably
expose usage percentages, so threshold warnings also accept explicit environment
overrides: `KIBITZ_CODEX_USAGE_PERCENT`, `KIBITZ_AGY_USAGE_PERCENT`,
`KIBITZ_CLAUDE_USAGE_PERCENT`, and `KIBITZ_CURSOR_USAGE_PERCENT`.

Hard provider markers such as `RESOURCE_EXHAUSTED`, `code 429`, `check quota`,
`Individual quota reached`, `rate limit`, or `out of credits` are handled
differently. Kibitz annotates the failed `<agent>.md`, writes
`<agent>_quota_hold.md`, prints a user-facing acknowledgment, and suggests a
retry window. Default retry window is `KIBITZ_QUOTA_RETRY_AFTER=1h`; examples:
`30m`, `4h`, `1d`.

A quota marker in a recent Antigravity CLI log WARNS but does **not** block the
lane. Antigravity hits 429s internally, retries and succeeds: one log from a run
that produced a complete 7.6 KB review carried five `RESOURCE_EXHAUSTED` markers
and four `code 429`. So a log marker is evidence about the provider's rate
limiter, not evidence that this call will fail, and blocking on it costs a whole
reviewer seat for a lane that would have answered. Set
`KIBITZ_QUOTA_BLOCK_ON_RECENT=1` to restore blocking. Direct evidence still
blocks: the agent's own output is read to see whether THIS call actually died.

## Codex

Invocation (one review, read-only, file-handoff):

```
codex exec -C <repo> --sandbox read-only --json --color never \
  -c model_reasoning_effort="high" \
  [-m <model>] \
  -o <outfile> "<prompt>"
```

- The prompt is passed as the final argument. The subprocess stdin is closed
  with `stdin=subprocess.DEVNULL` so an inherited stdin cannot hang the launch.
- `--sandbox read-only` is a hard guarantee: the reviewer cannot edit the repo.
  Keep it. This is the safe primary lane.
- `-o <outfile>` (a.k.a. `--output-last-message`) writes the final answer to a
  file. Success = exit code 0 AND that file exists and is non-empty. Never scrape
  stdout first; Kibitz reads the file first and only uses stdout as a fallback
  for harnesses that print a review without writing the output file.
- `-C <repo>` sets the working directory the agent reads.

### Codex model + reasoning policy

- **Reasoning:** default `model_reasoning_effort="high"`. `xhigh` is reserved
  for deep review and is model-dependent; if an `xhigh` run fails, the script
  retries once with `high`. Override via `KIBITZ_CODEX_REASONING`.
- **Model pin:** set `KIBITZ_CODEX_MODEL` (e.g. `gpt-5.6-sol`) to bypass auto-pick
  entirely; empty/unset = auto-pick below.
- **Model:** poll the live catalog with `codex debug models` (JSON), then pick
  the strongest non-mini model, preferring in order: `gpt-5.5`, then
  `gpt-5-codex`, then `gpt-5`; otherwise the highest `gpt-5*` slug. Models tagged
  `mini` / `fast` / `spark` / `nano` are never auto-selected. If polling fails,
  Codex falls back to its own default model.
- The default coding/review pick is **`gpt-5.5` at `high`** for family diversity
  against the Gemini lane.

## Antigravity (`agy`)

When the active host is the Antigravity UI, do not launch `agy` as a reviewer
from the base OS. Use `--driver agy` so the UI is the Antigravity lane and only
Codex + Claude Code are fanned out. The `agy` CLI lane below is for non-UI hosts
or explicit CLI testing.

Invocation (one review, file-handoff):

```
agy --model <model> --dangerously-skip-permissions --print-timeout 5m \
  -p "<prompt + write directive>"
```

- `agy` has **no** read-only-that-still-writes sandbox, **no** `--headless`,
  and **no** `--approve` (verified on agy 1.0.16). Do not invoke those - they
  do not exist on this version.
- Because `agy -p` swallows stdout when redirected, the review is delivered by
  **file-handoff**: the prompt instructs `agy` to WRITE its complete review to a
  specific output file with its own write tool, then stop.
- On agy 1.0.16, captured subprocess launches have two known failure modes:
  inherited stdin can hang startup (#508), and captured stdout can be empty even
  with rc=0 (#76/#408). Kibitz closes stdin with `stdin=subprocess.DEVNULL`,
  reads the output file first, and treats rc=0 with no file/stdout text as a
  failed leg rather than an empty review.
- On quota/credit exhaustion, `agy` may only hand Kibitz a generic timeout or
  empty file. When the Antigravity leg fails, Kibitz also scans recent
  `%USERPROFILE%\.gemini\antigravity-cli\log\*.log` / `cli.log` entries for
  quota markers such as `RESOURCE_EXHAUSTED`, `code 429`, `check quota`, or
  `Individual quota reached`. Only those markers are reported as
  quota/backend exhaustion; Kibitz must not guess "credits" from a plain
  timeout.
- That write requires `--dangerously-skip-permissions` (agy is otherwise
  interactive about file writes). This makes `agy` **UNSANDBOXED**: it is gated
  only by the strict review-only prompt directive. See **Safety posture** in
  `SKILL.md`; run untrusted prompts in a throwaway git worktree.

### Antigravity model policy

- Default model: **`Gemini 3.7 Flash (High)`** (override via `KIBITZ_AGY_MODEL`; set to
  `""` to use agy's own default).
- `agy` has no separate reasoning flag - reasoning rides the picker display
  name's parenthesized level. The override must be the exact display name;
  passing a lower-case discovery slug can silently drop the Antigravity lane.
- Latest observed Antigravity discovery catalog (`agy models`, version `1.1.5`,
  2026-07-22):

  ```text
  gemini-3.6-flash-high
  gemini-3.6-flash-medium
  gemini-3.6-flash-low
  gemini-3.5-flash-high
  gemini-3.5-flash-medium
  gemini-3.5-flash-low
  gemini-3.1-pro-high
  gemini-3.1-pro-low
  claude-sonnet-4-6
  claude-opus-4-6-thinking
  gpt-oss-120b-medium
  ```

- If you specifically want the older Pro Gemini lane, set
  `KIBITZ_AGY_MODEL="Gemini 3.1 Pro (High)"`.

- **Diversity rule (do not casually change):** `agy` is multi-model and can run
  Claude or gpt-oss too. Keep it on **Gemini**. Codex covers GPT-family review
  and Claude Code covers the Claude-family lane when included, so `agy` on
  Gemini gives three distinct model families. Putting `agy` on a Claude model
  duplicates Claude; putting it on gpt-oss duplicates Codex - either collapses
  the panel's whole value.

## Claude Code (`claude`)

Invocation (one review, default file-handoff lane):

```
claude -p \
  --output-format text \
  --no-session-persistence \
  --dangerously-skip-permissions \
  --tools Read,Glob,Grep,Write \
  --add-dir <repo> \
  [--model <model>] \
  [--effort <low|medium|high|max>] \
  "<prompt + write directive>"
```

- The prompt is passed as the final argument. The subprocess stdin is closed
  with `stdin=subprocess.DEVNULL` for the same inherited-stdin safety as the
  other lanes.
- Claude Code has no native `-o` / `--output-last-message` equivalent, so the
  review is delivered by **file-handoff**: the prompt instructs Claude to WRITE
  its complete review to a specific output file, then stop.
- That write requires `--dangerously-skip-permissions`. The tool list is narrowed
  to `Read,Glob,Grep,Write`; the prompt permits only the single review-file write.
- Claude is in the runner set, but driver-aware defaults skip whichever system
  is already acting as the active driver. Use `--driver codex|claude|agy|none`
  to make that explicit, or `KIBITZ_DRIVER` for hosts that launch the script
  indirectly. Use repeated `--only` flags to run a smaller fallback panel, for
  example `--only codex --only claude` when `agy` is out of quota. `--only agy`
  is accepted as an alias for `--only antigravity`.

### Claude model + effort policy

- Claude Code does **not** currently expose a native first-party `auto` model
  router in the local CLI help. Kibitz therefore uses an explicit spend tier
  instead of pretending auto-routing exists.
- Default spend tier: **`KIBITZ_CLAUDE_BUDGET=medium`**, which resolves to
  `--model sonnet --effort high` and preserves the previous default behavior.
- Supported spend tiers:

  | Tier | Model | Effort | Intended use |
  |------|-------|--------|--------------|
  | `low` / `cheap` | `haiku` | `medium` | quick/cheap sanity checks |
  | `medium` / `med` / `standard` | `sonnet` | `high` | default review lane |
  | `high` / `deep` | `opus` | `max` | expensive deep review |
  | `plan` / `opusplan` | `opusplan` | `high` | Claude Code's planning-biased alias when available |

- Explicit overrides win: set `KIBITZ_CLAUDE_MODEL` or
  `KIBITZ_CLAUDE_EFFORT` to override the tier's chosen value. Set either to
  `""` to use Claude Code's own default for that field. If Claude Code later
  ships a native `auto` alias, use `KIBITZ_CLAUDE_MODEL=auto`.
- When `agy` is out of quota, the practical fallback is `--only claude` or
  `--only codex --only claude`.

## Cursor (`agent`)

Invocation (one review, READ-ONLY, prompt on stdin, review from stdout):

```
agent -p --trust --mode ask --output-format text --model <id>
        # ...with the PROMPT written to the process's STDIN, never as an argument
```

**The best-postured lane of the four.** `--mode ask` is read-only and has no write
tool, so Cursor needs no `--force`, no `--yolo`, and no skip-permissions flag. It is
the only lane that cannot modify your repo even in principle.

### The 8191-character wall - do not undo this

**The prompt MUST be fed on stdin.** On Windows `agent.cmd` re-invokes PowerShell
through `cmd.exe`, whose command line is capped at 8191 characters. A real kibitz
round prompt (round text + profiles + grounding footer) runs past 10,000. Passed as
an argv element it fails in 0.1 s with:

```
The command line is too long.
```

rc=1, empty stdout. Every short smoke test still passes, so this breaks only in
production. `run_cursor` therefore sends the prompt on stdin, and falls back to
calling `versions\<newest>\node.exe index.js` directly (pure CreateProcess, 32767
limit) if stdin ever stops working.

### `--trust` is mandatory

Without it every headless run exits rc=1 with "Workspace Trust Required", on any
drive, no matter how many times you have run there before. Kibitz passes `--trust`
on every call, which is why it works on any repo on any drive **without writing
trust records into your Cursor config**.

### No FILE_OUTPUT_DIRECTIVE for this lane

Cursor gets `STDOUT_OUTPUT_DIRECTIVE` instead. The file-handoff directive orders a
Write and says "Do not rely on stdout" - on a lane whose write tool is blocked that
manufactures a guaranteed false failure, where the agent hits the tool-health check,
cannot write, dutifully reports that it cannot read the repository, and the leg is
failed for a tool it was never given.

### Cursor model policy

Default `KIBITZ_CURSOR_MODEL=cursor-grok-4.6-high`. **Keep this on Grok.** Cursor
serves roughly 200 model ids across GPT, Claude, Gemini, Grok, Kimi, GLM and
Composer - it is the most multi-model launcher of the four, which makes the
one-family-per-seat rule matter more here, not less:

| lane | family |
|------|--------|
| `codex` | GPT |
| `antigravity` | Gemini |
| `claude` | Claude |
| `cursor` | **Grok** |

Grok is the only family the other three cannot supply. Kimi K3 and GLM 5.2 are the
defensible alternates; GPT / Claude / Gemini are not, because each duplicates a seat
the panel already holds.

`--check-pins` validates this id against the live `agent --list-models` catalog.
Cursor's catalog is the largest and fastest-moving of the four, so this pin is the
most likely to rot. `auto` never rots but surrenders family control, so it is
deliberately not the default.

**Privacy:** every `claude-fable-5-*` id in Cursor's catalog is labelled
**(NO ZDR)** - no zero data retention. Do not select one as a silent default; that
is a privacy change, not just a model change.

## Driver-aware selection

The script separates the **active driver** from the external reviewer agents.
The driver writes the anchor review and does synthesis; the script fans out to
the other systems by default.

**THE HOST BOUNDARY:** a driver never reviews itself. If Codex is driving, the
`codex` CLI is not a second opinion - it is the same system grading its own
homework, and the same is true of agy driving agy, Claude driving Claude, and
Cursor driving Cursor. The default panel is therefore **all four lanes MINUS the
detected driver**.

```
python scripts/kibitz.py --doc plan.md --round r1 --driver auto
python scripts/kibitz.py --doc plan.md --round r1 --driver codex
python scripts/kibitz.py --doc plan.md --round r1 --driver claude
python scripts/kibitz.py --doc plan.md --round r1 --driver agy
python scripts/kibitz.py --doc plan.md --round r1 --driver cursor
python scripts/kibitz.py --doc plan.md --round r1 --driver none
```

- `--driver auto` is the default. It first honors `KIBITZ_DRIVER`; then it looks
  for known host environment hints. Codex Desktop is detected via
  `CODEX_SHELL` / `CODEX_THREAD_ID` / `CODEX_INTERNAL_ORIGINATOR_OVERRIDE`;
  Cursor via `CURSOR_AGENT` / `CURSOR_CONVERSATION_ID` / `CURSOR_INVOKED_AS`.
- `--driver codex` runs Antigravity + Claude Code + Cursor.
- `--driver claude` runs Codex + Antigravity + Cursor.
- `--driver agy` / `--driver antigravity` runs Codex + Claude Code + Cursor.
- `--driver cursor` runs Codex + Antigravity + Claude Code.
- `--driver none` means standalone/full panel and runs all four agents.
- `--all-agents` also runs all four, ignoring the detected driver. That CAN make
  a host review itself, so use it deliberately.
- Repeated `--only` flags override driver-aware selection entirely.
- `--dry-run` prints the selected driver/reviewer set and exits before any agent
  call.

## If a flag breaks

1. Run `codex --help` / `codex exec --help`, `agy --help`, `claude --help`, or
   `agent --help`.
2. Find the current equivalent of the flag that broke.
3. Update the invocation in `scripts/kibitz.py` AND the entry in this file in the
   same change. Note the version you verified it on in the table above.
