# COMPAT.md - version-specific CLI flags and model policy

`SKILL.md` is the durable contract. This file is the volatile part: the exact
CLI flags, the model-selection policy, and the tool versions this was proven on.

> **These flags move fast. If a flag breaks, run `codex --help` / `agy --help`
> / `claude --help` and update this file - do not patch around it in the
> script.** The skill's design (file-handoff, read-only Codex, active-driver
> judge) is stable; only the surface flags below are expected to drift.

## Proven on

| Tool | Version proven | Notes |
|------|----------------|-------|
| Codex CLI (`codex`) | running model `gpt-5.5` | `codex exec` non-interactive mode |
| Antigravity (`agy`) | `1.0.13` | no `--headless`, no `--approve`, no `models` subcommand |
| Claude Code (`claude`) | `2.1.72` | `claude -p` non-interactive mode |
| GitHub CLI (`gh`) | `2.89` | optional; only if you script repo setup |

These are the versions the invocations below were verified against. Newer
versions may rename or remove flags - check `--help` first.

## Codex

Invocation (one review, read-only, file-handoff):

```
codex exec -C <repo> --sandbox read-only --json --color never \
  -c model_reasoning_effort="high" \
  [-m <model>] \
  -o <outfile> -
```

- The prompt is piped on **STDIN** (the trailing `-`).
- `--sandbox read-only` is a hard guarantee: the reviewer cannot edit the repo.
  Keep it. This is the safe primary lane.
- `-o <outfile>` (a.k.a. `--output-last-message`) writes the final answer to a
  file. Success = exit code 0 AND that file exists and is non-empty. Never scrape
  stdout - it is swallowed when redirected.
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
agy --model <model> --dangerously-skip-permissions -p "<prompt + write directive>"
```

- `agy` has **no** read-only-that-still-writes sandbox, **no** `--headless`,
  **no** `--approve`, and **no** `models` subcommand (verified on agy 1.0.13).
  Do not invoke any of those - they do not exist on this version.
- Because `agy -p` swallows stdout when redirected, the review is delivered by
  **file-handoff**: the prompt instructs `agy` to WRITE its complete review to a
  specific output file with its own write tool, then stop.
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
  [--effort <low|medium|high|max>]
```

- The prompt is sent on **STDIN**.
- Claude Code has no native `-o` / `--output-last-message` equivalent, so the
  review is delivered by **file-handoff**: the prompt instructs Claude to WRITE
  its complete review to a specific output file, then stop.
- That write requires `--dangerously-skip-permissions`. The tool list is narrowed
  to `Read,Glob,Grep,Write`; the prompt permits only the single review-file write.
- Claude is in the default runner set. Use repeated `--only` flags to run a
  smaller fallback panel, for example `--only codex --only claude` when `agy`
  is out of quota. `--only agy` is accepted as an alias for
  `--only antigravity`.

### Claude model + effort policy

- Default model alias: **`sonnet`** (override via `KIBITZ_CLAUDE_MODEL`; set to
  `""` to use Claude Code's own default).
- Default effort: **`high`** (override via `KIBITZ_CLAUDE_EFFORT`; supported
  values on Claude Code 2.1.72 are `low`, `medium`, `high`, and `max`).
- When `agy` is out of quota, the practical fallback is `--only claude` or
  `--only codex --only claude`.

## If a flag breaks

1. Run `codex --help` / `codex exec --help`, `agy --help`, or `claude --help`.
2. Find the current equivalent of the flag that broke.
3. Update the invocation in `scripts/kibitz.py` AND the entry in this file in the
   same change. Note the version you verified it on in the table above.
