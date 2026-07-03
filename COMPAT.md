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
| Antigravity (`agy`) | `1.0.16` | no `--headless`, no `--approve`; `agy models` is available for preflight |
| Claude Code (`claude`) | `2.1.72` | `claude -p` non-interactive mode |
| GitHub CLI (`gh`) | `2.89` | optional; only if you script repo setup |

These are the versions the invocations below were verified against. Newer
versions may rename or remove flags - check `--help` first.

## Quota, credit, and retry behavior

Kibitz performs a cheap, non-prompt quota/auth preflight for each selected lane
before it spends an agent call:

- Codex: `codex login status`
- Antigravity: `agy models`, plus recent Antigravity CLI logs
- Claude Code: `claude auth status`

The preflight writes `<agent>_quota_status.txt` in the run folder. If Kibitz has
a real usage percentage, it warns at the configured thresholds (default
`KIBITZ_QUOTA_WARN_THRESHOLDS=50,70,90`) and appends to `quota_warnings.md`.
Current Codex, Antigravity, and Claude Code status surfaces do not reliably
expose usage percentages, so threshold warnings also accept explicit environment
overrides: `KIBITZ_CODEX_USAGE_PERCENT`, `KIBITZ_AGY_USAGE_PERCENT`, and
`KIBITZ_CLAUDE_USAGE_PERCENT`.

Hard provider markers such as `RESOURCE_EXHAUSTED`, `code 429`, `check quota`,
`Individual quota reached`, `rate limit`, or `out of credits` are handled
differently. Kibitz annotates the failed `<agent>.md`, writes
`<agent>_quota_hold.md`, prints a user-facing acknowledgment, and suggests a
retry window. Default retry window is `KIBITZ_QUOTA_RETRY_AFTER=1h`; examples:
`30m`, `4h`, `1d`.

For recent Antigravity CLI log markers, Kibitz blocks that lane by default
instead of immediately burning another hanging attempt. Override with
`KIBITZ_QUOTA_BLOCK_ON_RECENT=0` only when you intentionally want to force a
fresh call.

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
- **Model:** poll the live catalog with `codex debug models` (JSON), then pick
  the strongest non-mini model, preferring in order: `gpt-5.5`, then
  `gpt-5-codex`, then `gpt-5`; otherwise the highest `gpt-5*` slug. Models tagged
  `mini` / `fast` / `spark` / `nano` are never auto-selected. If polling fails,
  Codex falls back to its own default model.
- The default coding/review pick is **`gpt-5.5` at `high`** for family diversity
  against the Gemini lane.

## Antigravity (`agy`)

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
  only by the strict review-only prompt directive. See SAFETY in `README.md` -
  run untrusted prompts in a throwaway git worktree.

### Antigravity model policy

- Default model: **`gemini-3.5-pro`** (override via `KIBITZ_AGY_MODEL`; set to
  `""` to use agy's own default).
- `agy` has no separate reasoning flag - reasoning rides the model slug's
  suffix (e.g. `gemini-3.1-pro-high`). Set `KIBITZ_AGY_MODEL=gemini-3.1-pro-high`
  for maximum reasoning.
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

- Default model alias: **`sonnet`** (override via `KIBITZ_CLAUDE_MODEL`; set to
  `""` to use Claude Code's own default).
- Default effort: **`high`** (override via `KIBITZ_CLAUDE_EFFORT`; supported
  values on Claude Code 2.1.72 are `low`, `medium`, `high`, and `max`).
- When `agy` is out of quota, the practical fallback is `--only claude` or
  `--only codex --only claude`.

## Driver-aware selection

The script separates the **active driver** from the external reviewer agents.
The driver writes the anchor review and does synthesis; the script fans out to
the other systems by default.

```
python scripts/kibitz.py --doc plan.md --round r1 --driver auto
python scripts/kibitz.py --doc plan.md --round r1 --driver codex
python scripts/kibitz.py --doc plan.md --round r1 --driver claude
python scripts/kibitz.py --doc plan.md --round r1 --driver agy
python scripts/kibitz.py --doc plan.md --round r1 --driver none
```

- `--driver auto` is the default. It first honors `KIBITZ_DRIVER`; then it looks
  for known host environment hints. Codex Desktop is detected via
  `CODEX_SHELL` / `CODEX_THREAD_ID` / `CODEX_INTERNAL_ORIGINATOR_OVERRIDE`.
- `--driver codex` runs Antigravity + Claude Code.
- `--driver claude` runs Codex + Antigravity.
- `--driver agy` / `--driver antigravity` runs Codex + Claude Code.
- `--driver none` means standalone/full panel and runs all three agents.
- `--all-agents` also runs all three, ignoring the detected driver.
- Repeated `--only` flags override driver-aware selection entirely.
- `--dry-run` prints the selected driver/reviewer set and exits before any agent
  call.

## If a flag breaks

1. Run `codex --help` / `codex exec --help`, `agy --help`, or `claude --help`.
2. Find the current equivalent of the flag that broke.
3. Update the invocation in `scripts/kibitz.py` AND the entry in this file in the
   same change. Note the version you verified it on in the table above.
