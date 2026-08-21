---
name: kibitz
description: >-
  Harden plans, sprint plans, specs, and architecture docs with independent
  local file-reading reviews from Codex, Antigravity, Claude Code, and Cursor.
  The active UI driver writes a code-grounded anchor, excludes its own duplicate
  CLI lane, verifies every reviewer claim against the real repo, and acts as sole
  judge. Use the default four-round arc for new campaigns or auditable
  continuation/scoped-tail receipts when explicitly requested. Includes
  optional ComfyUI and repo-local profiles. Use when the user says kibitz,
  /kibitz, second opinion, pressure-test, harden, round-robin, make bulletproof,
  run the local panel, or asks to include local Codex, Antigravity, Claude, or
  Cursor reviewers.
---

# Kibitz

Harden a document by (1) having the active driver write its own code-grounded
anchor review, then (2) fanning the document out to LOCAL file-reading CLI
agents for independent critique, then (3) verifying every claim against the
real code and folding only what survives into an improved plan. A new campaign
runs the full 4-round arc by default; explicit resumptions and user-scoped
contiguous round ranges are supported with receipts.

There are **four lanes, one model family each** -- that split is the whole point,
because four independent readings are worth more than four readings from the same
family:

| lane | CLI | family |
|------|-----|--------|
| `codex` | `codex exec` | GPT |
| `antigravity` | `agy` | Gemini |
| `claude` | `claude -p` | Claude |
| `cursor` | `agent -p` | Grok |

**A DRIVER NEVER REVIEWS ITSELF.** If Codex is driving, the `codex` CLI is not a
second opinion -- it is the same system grading its own homework, and the same is
true of agy driving agy, Claude driving Claude, and Cursor driving Cursor. So the
default panel is **all four lanes MINUS the detected driver**:

- Claude driving -> Codex + Antigravity + Cursor review.
- Codex driving -> Antigravity + Claude Code + Cursor review.
- Antigravity driving -> Codex + Claude Code + Cursor review.
- Cursor driving -> Codex + Antigravity + Claude Code review.
- No driver / standalone -> all four review.

Use `--driver claude|codex|agy|cursor|none` when the host is not auto-detected.
Use repeated `--only` flags for fallbacks, such as `--only codex --only cursor`
when Antigravity is out of quota.

**Host UI boundary:** when Kibitz is invoked from a product UI, that live UI is
the driver/panelist for its model family. Do not launch the same system's CLI as
a second reviewer from the base OS. In Antigravity UI, use `--driver agy` (or
`--only codex --only claude`) so Antigravity participates through the UI anchor,
not through an `agy` subprocess. In Cursor, use `--driver cursor`. Avoid
`--all-agents` in that context unless you are intentionally testing a CLI outside
its own UI -- `--all-agents` deliberately ignores the boundary and CAN make a host
review itself.

> **Exact CLI flags, model-selection policy, and the versions this was proven
> on live in [`COMPAT.md`](COMPAT.md).** They move fast; keep them out of your
> head and check that file when a flag stops working. This SKILL.md is the
> durable contract.

## The division of labor (this is the whole idea)

- **The active driver is ALWAYS both a panelist AND the sole judge.** Before
  the fan-out, the driver reads the real source files and writes its own
  VERDICT + MUST-FIX review in the same format as the panel. In Claude Cowork
  the driver is Claude; in Codex the driver is Codex. This *anchor review* is
  grounded from the start and stops the panel from hijacking synthesis with
  plausible-sounding hallucinations.
- **The panel generates independent critiques.** By default it is the local
  agents that are not already the active driver -- three of the four lanes;
  standalone runs use all four.
  Each agent opens your repo in its own working directory and grounds its own
  review; neither sees the other's output. Different agent harnesses catch
  different things - that diversity is the value.
- **The active driver is the sole judge and synthesizer.** Local agents can
  still be confidently wrong about your code. The driver verifies each agent
  claim against the actual files, throws out misreads and hallucinations, and
  integrates only the verified-good. Correctness comes from grounding - not
  headcount.

Never outsource the synthesis to an agent. The panel proposes; the driver
disposes.

## Safety posture (durable - not version-specific)

- **Codex runs read-only.** The reviewer literally cannot edit your repo. This
  is the primary lane; keep it that way.
- **Antigravity runs UNSANDBOXED.** `agy` has no read-only-that-still-writes
  mode, so the file-handoff (the agent writes its own review to a file)
  requires `--dangerously-skip-permissions`. It is gated by a strict
  review-only prompt directive, and because your repo is git-committed, any
  stray edit shows up in `git status` and is revertible.
- **Claude Code is writable only for file-handoff.** It uses
  `claude -p` with Read/Glob/Grep/Write and `--dangerously-skip-permissions`,
  so it can write its single review file.
- **For untrusted prompts, run writable lanes in a throwaway git worktree.** Do
  not feed a prompt you do not trust into an unsandboxed agent against your live
  tree.

## The 4-round arc

Each round has a different focus. Run all four for a new campaign; do not
silently skip a round.

| Round | Focus | Round prompt |
|-------|-------|--------------|
| r1 | High-level arc / creative coherence | `references/review-prompt-r1.md` |
| r2 | Coding plan / implementability | `references/review-prompt-r2.md` |
| r3 | Wiring / integration / sequencing | `references/review-prompt-r3.md` |
| r4 | Convergence / residual defects | `references/review-prompt-r4.md` |

### Continuation and explicitly scoped tails

The full arc is the default, not a reason to ignore an explicit user request.
When the user asks to resume or names a contiguous range such as `r3 -> r4`:

- **Resume with prior artifacts:** verify the immediate predecessor's
  `input.md`, `driver_anchor.md`, reviewer files, `judgment.md`, and `final.md`.
  Record their paths and SHA-256 values in `resume_receipt.md`, and use that
  predecessor `final.md` as the resumed round's exact input. If the chain is
  missing or ambiguous, restart at the earliest missing round unless the user
  explicitly requests a partial campaign.
- **Explicit partial campaign:** when earlier Kibitz artifacts do not exist but
  the user deliberately requests only a contiguous tail, write
  `scope_receipt.md` before fan-out. Record the requested range, input path and
  SHA-256, driver, reviewer lanes, and every round not run. Never describe that
  campaign as a completed four-round arc.
- Run every selected round sequentially through the requested endpoint. Write a
  fresh `driver_anchor.md` before each fan-out, ground every new claim, and feed
  each round's `final.md` into the next. Never report an omitted round as
  executed.

The standard per-round driver artifacts are `driver_anchor.md`, `judgment.md`,
and `final.md`, alongside `input.md` and the reviewer files.

After r4, deliver the final hardened plan and report the **actual** agent calls
made. With four lanes, a normal driver-aware full arc makes **12** external calls
(three reviewer agents x four rounds, since the driver is excluded);
`--driver none` or `--all-agents` makes **16**. A scoped campaign reports its
smaller real count and names the rounds not run.

**Domain profiles (optional).** The four round prompts are deliberately
general. When the target is a specialized codebase, use the matching profile so
the agents also check that domain's invariants. Ships with `profiles/comfyui.md`
(ComfyUI custom-node packs: tensor layouts, the node-class contract,
VRAM/model-management, `IS_CHANGED` caching, import isolation). For ComfyUI repos,
prefer generating a local overlay with:

```
python scripts/comfyui_profile.py --repo /path/to/repo --workflow workflows/main.json --write
```

That writes `.kibitz/comfyui.local.md` in the target repo. The helper tries to
infer the user's actual ComfyUI setup: local/cloud runtime hints, ComfyUI root,
Comfy Desktop executable, active localhost server ports, input/output/temp dirs,
`user/default` settings and workflows, `extra_model_paths*.yaml`, model
inventory, Hugging Face cache ids, and installed custom nodes. `scripts/kibitz.py`
auto-appends both the shipped ComfyUI profile and that local overlay when the
overlay exists. Use `--profile comfyui` to force the generic profile without a
local overlay, or `--no-profiles` to disable profiles for a run. Add your own
profiles the same way via `--profile path/to/profile.md`.

## The loop (steps 1-6 repeat for each selected round)

Do not skip the driver anchor or the grounding step.

1. **Set up.** Identify the document, topic, and repo. Decide the round. If a
   domain profile applies, note which one. For ComfyUI repos, check whether
   `.kibitz/comfyui.local.md` exists; if it does not and workflow/VRAM facts
   matter, generate it before fanning out.

2. **The driver writes its anchor review.** Read the real source files and any
   applicable domain/local profile. Write a VERDICT + MUST-FIX + SHOULD-FIX
   review of the *current* plan in the same format as the round prompt
   (`references/review-prompt-r<N>.md`). Label every claim CONFIRMED / MISREAD /
   UNVERIFIABLE against the files you can actually see. This is the first input
   to synthesis.

3. **Fan out - run the local agents.** Call the script (below). It writes the
   plan to `input.md`, then runs each selected agent non-interactively with the
   round prompt (plus any domain profile), capturing one review per agent under
   the run folder.

4. **Ground every agent claim.** Read the agents' reviews. For each distinct
   claim, verify against the *real* files - read the actual source/JSON, or
   spawn subagents to parallelize. Label each claim CONFIRMED, MISREAD (cite the
   covering section), or UNVERIFIABLE (downgrade to a "verify-at-build" note).
   Discard MISREAD and hallucinated claims.

5. **Synthesize (driver only).** Merge anchor review + verified agent claims:
   dedupe across sources, resolve conflicts with a one-line rationale, guard the
   project's invariants (reject any "fix" that breaks one), keep it lean - no
   changelog, just the improved plan forward. Save as `final.md` (or
   `r<N>_plan.md` if advancing). Keep a short judgment note (accepted /
   rejected-with-reason / verify-at-build items).

6. **Advance.** Feed the updated plan into the next selected round (normally
   r1 -> r2 -> r3 -> r4) using that round's prompt. For a continuation or
   explicit partial campaign, obey the receipt and remain sequential within the
   selected range. After r4, deliver the final hardened plan and judgment log.

## Calling the fan-out script

**Always run this script -- never hand-roll the agent calls.** If `scripts/kibitz.py`
is not sitting next to this `SKILL.md` (some hosts install only the doc), clone the repo
and run it from there instead of improvising your own `codex`/`agy` invocation:

```
git clone https://github.com/jbrick2070/kibitz
python kibitz/scripts/kibitz.py --doc path/to/plan.md --round r1 --topic mytopic --repo /path/to/your/repo
```

The script resolves the CLIs itself with **no PATH required**: it checks `PATH`,
then falls back to the standard install dirs and `rglob`s them -- so it finds
`codex` even when it lives in a hashed bin dir (e.g.
`%LOCALAPPDATA%\OpenAI\Codex\bin\<hash>\codex.exe`), `agy` in
`%LOCALAPPDATA%\agy\bin`, and `claude` in `%USERPROFILE%\.local\bin`.
Hand-rolling the resolution is exactly how a host misses a local agent and
drops to a smaller panel for no reason -- so don't. (Run
`python scripts/doctor.py` first if you want to confirm the agents resolve.)

`scripts/kibitz.py` does exactly one pass and nothing else. It is
**Python standard library only** - no pip install, no dependencies.

```
python scripts/kibitz.py \
  --doc path/to/plan.md \
  --round r1 \
  --topic ending-mode \
  --repo /path/to/your/repo \
  --driver auto
```

- `--repo` defaults to the current directory, so if you run from the repo root
  you can omit it.
- `--doc <path>` validates UTF-8 for the reviewer prompt and copies the source
  bytes exactly to `input.md`; never normalize line endings in a resume chain.
- `--round {r1,r2,r3,r4}` picks one round prompt. Run all four for a new
  campaign; explicit resumptions and scoped tails follow the receipt rules
  above.
- `--profile comfyui` appends the shipped generic ComfyUI profile. `--profile
  path/to/profile.md` appends a custom profile. Repeat as needed.
- `.kibitz/comfyui.local.md` in the target repo is auto-detected; when present,
  kibitz appends both the shipped ComfyUI profile and the local overlay.
- `--no-profiles` disables both requested profiles and local auto-detection.
- `--driver {auto,none,codex,claude,antigravity,agy,cursor}` selects the active
  driver, which is then EXCLUDED from the panel -- a driver never reviews itself.
  `auto` honors `KIBITZ_DRIVER` and known host environment hints. `none` means
  standalone/full external panel (all four lanes).
- `--all-agents` runs Codex + Antigravity + Claude Code + Cursor regardless of
  driver. This ignores the host boundary and can make a driver review itself.
- `--only codex`, `--only antigravity`/`--only agy`, `--only claude`, or
  `--only cursor` (aliases: `agent`, `cursor-agent`) runs selected agents
  (repeatable) and overrides the driver-aware default.
- `--dry-run` prints the detected/selected driver and reviewer agents without
  calling any agents; use it to confirm host detection without spending prompts.
- If `agy` is out of quota, use `--only claude` or repeat
  `--only codex --only claude`.
- For the Claude Code reviewer lane, control spend with
  `KIBITZ_CLAUDE_BUDGET=low|medium|high|plan`. This is an explicit Kibitz tier,
  not a native Claude auto-router. Default `medium` preserves the normal
  `sonnet` / `high` behavior; `KIBITZ_CLAUDE_MODEL` and
  `KIBITZ_CLAUDE_EFFORT` override the tier.
- `--timeout <seconds>` is optional; default is no ceiling (agents batch and can
  take minutes). Only set it if you need to bail on a hung agent.
- Inline text works instead of `--doc`:
  `python scripts/kibitz.py "harden the ending-mode plan" --round r1`.

Output lands in `<repo>/kibitz-runs/<YYYY-MM-DD>-<topic>/<round>/` as
`input.md`, `profiles_used.txt`, `<agent>.md`, `<agent>.log`, and lightweight
quota/status files such as `<agent>_quota_status.txt`. If a provider reports
quota, credit, or rate-limit exhaustion, Kibitz also writes
`<agent>_quota_hold.md` with the diagnostic and a suggested retry window. The
driver then writes `final.md` there after grounding and synthesis.

## ComfyUI local profile helper

Generate or refresh a repo-local ComfyUI overlay with:

```
python scripts/comfyui_profile.py \
  --repo /path/to/comfyui/custom_nodes/MyNodePack \
  --workflow workflows/my_workflow.json \
  --vram-budget-gb 16 \
  --write
```

The helper records machine/repo facts such as GPU VRAM from `nvidia-smi`,
local/cloud runtime hints, ComfyUI root, active local server ports, user prefs,
model paths/inventory, Hugging Face cache ids, installed custom nodes, canonical
workflow summaries, files that mention `NODE_CLASS_MAPPINGS`, `INPUT_TYPES`,
tensor/layout signals, VRAM/model-management signals, top-level heavy imports,
and local reviewer instructions. It prints to stdout by default; `--write`
writes `.kibitz/comfyui.local.md`.
On write, it also adds `.kibitz/*.local.md` to the target repo's local
`.git/info/exclude` unless `--no-git-exclude` is passed. Existing profiles are
not overwritten unless `--force` is passed, so user notes in the local overlay
are protected.

Do **not** auto-update `CLAUDE.md` when generating a local profile. That file is
high-authority repo/project instruction space. If the user wants Claude/Cowork
to notice the profile, prefer:

```
python scripts/comfyui_profile.py --repo /path/to/repo --emit-claude-snippet
```

Only use this explicit opt-in when the user asks to write the pointer:

```
python scripts/comfyui_profile.py --repo /path/to/repo --append-claude-md
```

`--append-claude-md` writes only a marker-wrapped pointer to
`.kibitz/comfyui.local.md`, never the full local profile, and creates a
timestamped backup before changing an existing `CLAUDE.md`.

Useful overrides for cloud pods or unusual installs:

```
python scripts/comfyui_profile.py --repo . --comfyui-root /workspace/ComfyUI --models-dir /runpod-volume/models --ports 8188 --write
```

## First-run check and quota discipline

- **CHECK THE PINS AT INSTALL, AND AGAIN WHEN A CAMPAIGN STARTS.**

  ```
  python scripts/kibitz.py --check-pins
  ```

  It polls the live catalog, reports whether the configured lane is current,
  invalid, or a generation behind, and exits. **Run it as part of install and at
  the top of any multi-round arc.**

  Why it exists: a pin only ever verified by hand goes stale silently. Twice in
  one week the panel ran a generation behind and nothing said so - Codex's
  preference tuple still listed `gpt-5.5` after `gpt-5.6-sol` shipped, and the
  antigravity default still said `Gemini 3.6 Flash (High)` after 3.7 landed. In
  both cases the arc completed happily; only a receipt file recorded which model
  actually answered.

  It **warns, never blocks** - a stale pin still returns a real review, so
  failing the run would cost more than the drift. And note which lanes can even
  go stale: **aliases do not rot, pinned slugs do.** The Claude lane uses bare
  aliases (`haiku`/`sonnet`/`opus`) and has never drifted; the two that did were
  both pinned.
- **A BROKEN AGENT DOES NOT FAIL LOUDLY - IT RETURNS A CONFIDENT REPORT.** This
  is the failure mode to know about, because every other guard passes it: exit
  code 0, non-empty file, well-formatted headings. Observed 2026-08-17 - a lane
  returned a code trace whose middle steps read
  `summary | summary | summary | Standard processing applied`, asserted it was
  "proven from the real filesystem", and named a source file and a class that do
  not exist. The operator had separately hit a telemetry-plugin crash that killed
  that agent's tool execution outright.
  - **The tells are STRUCTURAL, not factual** - you need no knowledge of the repo
    under review to spot them: placeholder filler mid-chain, branch labels that
    contradict the logic the report itself quoted, and an impact list far thinner
    than the code supports.
  - **Two guards ship for this.** Every file-handoff agent is told, in
    `FILE_OUTPUT_DIRECTIVE`, to confirm its own file tools FIRST and to write
    `TOOL CHECK: FAIL` plus the verbatim error instead of a review if they do not
    - a refusal is a useful answer, a blind review is worse than none. And
    `collect_review` runs `unreadable_review_diagnostic`, which FAILS the leg on
    that filler instead of counting it as collected.
  - **The instruction alone was never going to be enough** - an instructed model
    is still a model - so the structural check is the real guard and the prompt
    line is belt-and-braces.
- **Eyeball `<agent>.md` on the first run.** For codex/agy/claude the
  file-handoff means `<agent>.md` is the agent's own written review; for the
  **cursor** lane it is the stdout kibitz captured, since ask mode has no write
  tool. Success is judged by exit code + a non-empty review that survives the
  structural check - the script does NOT deeply verify the text really *is* a
  review rather than a plausible error message. If it is empty with exit 0, the
  agent ignored its output directive: check `<agent>.log` and re-run once.
- **All lanes can hit quota, credit, or rate limits.** A normal driver-aware
  full arc is 12 external agent calls (three reviewer agents x four rounds),
  which is fine, but high-volume loops can still bite. Kibitz writes
  `<agent>_quota_status.txt` for each selected lane and `quota_warnings.md`
  when it has something worth surfacing.
- **Warn on usage only when there is a real number.** The default warning
  thresholds are 50/70/90 percent (`KIBITZ_QUOTA_WARN_THRESHOLDS`). Current CLI
  status surfaces do not always expose percentages, so Kibitz also accepts
  explicit overrides such as `KIBITZ_CODEX_USAGE_PERCENT`,
  `KIBITZ_AGY_USAGE_PERCENT`, and `KIBITZ_CLAUDE_USAGE_PERCENT`.
- **Acknowledge confirmed quota failures to the user.** When a lane reports
  provider quota, credit, or rate-limit markers, Kibitz annotates the failed
  review, writes `<agent>_quota_hold.md`, prints the suggested retry window, and
  the driver should tell the user plainly: this lane failed on quota/credit
  usage. Ask when they want to retry, or use the built-in retry window
  (`KIBITZ_QUOTA_RETRY_AFTER`, default `1h`).
- **Do not guess credits from a timeout.** For Antigravity specifically, Kibitz
  scans recent `agy` CLI logs for quota markers (`RESOURCE_EXHAUSTED`, `code
  429`, `check quota`, `Individual quota reached`) and annotates the failed
  review file only when those markers exist. A plain `timeout waiting for
  response` remains an `agy` timeout/print-mode failure.
- **A CLI-LOG MARKER WARNS; IT DOES NOT BLOCK (default changed 2026-08-18).**
  The log scan is evidence about the provider's rate limiter, not about whether
  your call will fail. **Antigravity hits 429s internally, retries, and
  succeeds:** measured on a run that returned a complete 7.6 KB review, its own
  CLI log carried **5x `RESOURCE_EXHAUSTED` and 4x `code 429`**. Blocking on that
  costs a whole reviewer seat for a lane that would have answered -- which is
  exactly what happened on an r3 round that then ran a reviewer short for no
  reason. Same reasoning the pin check already uses: it warns, never blocks,
  because failing the run costs more than the drift.
  - **Direct evidence still blocks.** `output_quota_diagnostic` reads the
    agent's OWN stdout/stderr and sees whether *this* invocation actually died;
    that remains a hard failure, and the quota hold receipt is still written.
  - **Only the NEWEST log is consulted**, because a lane's state is its latest
    state, not its worst state in the window. Previously the scan walked every
    log in the lookback window (default 1h) newest-first and blocked on the first
    marker found, so a clean recent run did not clear an older failure -- it was
    skipped on the way to the stale one.
  - Restore the old behaviour with `KIBITZ_QUOTA_BLOCK_ON_RECENT=1`, and the
    whole-window scan with `KIBITZ_QUOTA_SCAN_ALL_RECENT=1`.
- **4 rounds is the default arc.** Do not add passes beyond r4 unless the user
  asks. Do not inflate an explicit scoped campaign into work the user did not
  request, and do not claim omitted rounds ran.

## Conventions

Write artifacts as UTF-8, no BOM, ASCII where practical. Save everything under
`<repo>/kibitz-runs/<date>-<topic>/` so the design history is auditable. Never
represent an agent's unverified claim as fact - if it was not grounded against
the code, it is a hypothesis, not a finding.
