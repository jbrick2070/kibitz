---
name: kibitz
description: >-
  Kibitz gets you a second opinion on a plan, sprint plan, spec, or architecture
  doc from local file-reading CLI agents: Codex (`codex exec`), Antigravity
  (`agy -p`), and Claude Code (`claude -p`). Kibitz is multi-system aware: the
  active driver (Claude, Codex, or Antigravity) writes the anchor review and is
  excluded from the default external reviewer set, while the remaining local
  agents crawl your REAL repo and return independent reviews. The driver grounds
  the agents' claims against the actual code, discards hallucinations, and folds
  only the survivors into one improved plan across a fixed 4-round arc (r1 arc
  -> r2 coding -> r3 wiring -> r4 convergence). Fully hands-off, designed for
  Claude Cowork, Codex, and Antigravity on Windows; ships with an opt-in ComfyUI
  custom-node profile plus a repo-local ComfyUI profile generator.
  Use when the user wants a second opinion / to pressure-test / harden /
  "round-robin" / "make bulletproof" a doc with their LOCAL agents, or says
  "kibitz", "/kibitz", "kibitz this", "get a second opinion", "run the local
  panel", "include Claude", or "use Codex, Claude, and Antigravity to review
  this".
---

# Kibitz

Harden a document by (1) having the active driver write its own code-grounded
anchor review, then (2) fanning the document out to LOCAL file-reading CLI
agents for independent critique, then (3) verifying every claim against the
real code and folding only what survives into an improved plan. Fixed 4-round
arc; run all four.

The default panel is **driver-aware**:

- Claude driving -> Codex + Antigravity review.
- Codex driving -> Antigravity + Claude Code review.
- Antigravity driving -> Codex + Claude Code review.
- No driver / standalone -> Codex + Antigravity + Claude Code review.

Use `--driver claude|codex|agy|none` when the host is not auto-detected. Use
repeated `--only` flags for fallbacks, such as `--only codex --only claude` when
Antigravity is out of quota.

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
- **The panel generates independent critiques.** By default it is the two local
  agents that are not already the active driver; standalone runs use all three.
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

Each round has a different focus. Run all four; do not exit early.

| Round | Focus | Round prompt |
|-------|-------|--------------|
| r1 | High-level arc / creative coherence | `references/review-prompt-r1.md` |
| r2 | Coding plan / implementability | `references/review-prompt-r2.md` |
| r3 | Wiring / integration / sequencing | `references/review-prompt-r3.md` |
| r4 | Convergence / residual defects | `references/review-prompt-r4.md` |

After r4, deliver the final hardened plan and report the agent calls made
(8 external calls across the normal driver-aware arc: two reviewer agents x four
rounds; 12 calls if `--driver none` or `--all-agents` runs all three external
agents).

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

## The loop (steps 1-6 repeat for each of the 4 rounds)

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

6. **Advance.** Feed the updated plan into the next round (r1 -> r2 -> r3 -> r4)
   using that round's prompt. Do not skip rounds. After r4, deliver the final
   hardened plan and the judgment log.

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
- `--round {r1,r2,r3,r4}` picks the round prompt. Run all four across the arc.
- `--profile comfyui` appends the shipped generic ComfyUI profile. `--profile
  path/to/profile.md` appends a custom profile. Repeat as needed.
- `.kibitz/comfyui.local.md` in the target repo is auto-detected; when present,
  kibitz appends both the shipped ComfyUI profile and the local overlay.
- `--no-profiles` disables both requested profiles and local auto-detection.
- `--driver {auto,none,codex,claude,antigravity,agy}` selects the active driver.
  `auto` honors `KIBITZ_DRIVER` and known host environment hints. `none` means
  standalone/full external panel.
- `--all-agents` runs Codex + Antigravity + Claude Code regardless of driver.
- `--only codex`, `--only antigravity`/`--only agy`, or `--only claude` runs
  selected agents (repeatable) and overrides the driver-aware default.
- `--dry-run` prints the detected/selected driver and reviewer agents without
  calling any agents; use it to confirm host detection without spending prompts.
- If `agy` is out of quota, use `--only claude` or repeat
  `--only codex --only claude`.
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

- **Eyeball `<agent>.md` on the first run.** The file-handoff means `<agent>.md`
  is the agent's own written review. Success is judged by exit code + the file
  existing and being non-empty - the script does NOT verify the file actually
  *contains a review* rather than an error message. If it is empty (or is an
  "I can't access the repo" note) with exit 0, the agent ignored the write
  directive: check `<agent>.log` and re-run once.
- **All lanes can hit quota, credit, or rate limits.** A normal driver-aware
  full arc is 8 external agent calls (two reviewer agents x four rounds), which
  is fine, but high-volume loops can still bite. Kibitz writes
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
- **4 rounds is the arc.** Do not add passes beyond r4 unless the user asks.

## Conventions

Write artifacts as UTF-8, no BOM, ASCII where practical. Save everything under
`<repo>/kibitz-runs/<date>-<topic>/` so the design history is auditable. Never
represent an agent's unverified claim as fact - if it was not grounded against
the code, it is a hypothesis, not a finding.
