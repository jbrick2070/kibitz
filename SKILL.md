---
name: kibitz
description: >-
  Kibitz gets you a second opinion on a plan, sprint plan, spec, or architecture
  doc from two file-reading CLI agents - Codex (`codex exec`) and Antigravity
  (`agy -p`) - running locally on your own machine, no API key and no cloud
  spend. Each agent crawls your REAL repo on its own and returns an independent
  review; Claude then writes its own code-grounded anchor review, grounds the
  agents' claims against the actual code, discards hallucinations, and folds only
  the survivors into one improved plan across a fixed 4-round arc (r1 arc -> r2
  coding -> r3 wiring -> r4 convergence). Fully hands-off, designed to run in
  Claude Cowork on Windows; ships with an opt-in ComfyUI custom-node profile.
  Use when the user wants a second opinion / to pressure-test / harden /
  "round-robin" / "make bulletproof" a doc with their LOCAL agents, or says
  "kibitz", "/kibitz", "kibitz this", "get a second opinion", "run the local
  panel", or "use Codex and Antigravity to review this".
---

# Kibitz

Harden a document by (1) having Claude write its own code-grounded anchor
review, then (2) fanning the document out to two LOCAL file-reading CLI agents
for independent critique, then (3) verifying every claim against the real code
and folding only what survives into an improved plan. Fixed 4-round arc; run
all four.

The panel here is **Codex (`codex exec`)** and **Antigravity (`agy -p`)**
running on your machine, each reading the real repo itself - so there is no
copy-paste, no API key, and no cloud spend.

> **Exact CLI flags, model-selection policy, and the versions this was proven
> on live in [`COMPAT.md`](COMPAT.md).** They move fast; keep them out of your
> head and check that file when a flag stops working. This SKILL.md is the
> durable contract.

## The division of labor (this is the whole idea)

- **Claude is ALWAYS both a panelist AND the sole judge.** Before the fan-out,
  Claude reads the real source files and writes its own VERDICT + MUST-FIX
  review in the same format as the panel. This *anchor review* is grounded from
  the start and stops the panel from hijacking synthesis with plausible-
  sounding hallucinations.
- **The panel (Codex + Antigravity)** generates *independent* critiques. Each
  agent opens your repo in its own working directory and grounds its own
  review; neither sees the other's output. Two different agent harnesses catch
  different things - that diversity is the value.
- **Claude is the sole judge and synthesizer.** Local agents can still be
  confidently wrong about your code. Claude verifies each agent claim against
  the actual files, throws out misreads and hallucinations, and integrates only
  the verified-good. Correctness comes from Claude's grounding - not headcount.

Never outsource the synthesis to an agent. The panel proposes; Claude disposes.

## Safety posture (durable - not version-specific)

- **Codex runs read-only.** The reviewer literally cannot edit your repo. This
  is the primary lane; keep it that way.
- **Antigravity runs UNSANDBOXED.** `agy` has no read-only-that-still-writes
  mode, so the file-handoff (the agent writes its own review to a file)
  requires `--dangerously-skip-permissions`. It is gated by a strict
  review-only prompt directive, and because your repo is git-committed, any
  stray edit shows up in `git status` and is revertible.
- **For untrusted prompts, run `agy` in a throwaway git worktree.** Do not feed
  a prompt you do not trust into an unsandboxed agent against your live tree.

## The 4-round arc

Each round has a different focus. Run all four; do not exit early.

| Round | Focus | Round prompt |
|-------|-------|--------------|
| r1 | High-level arc / creative coherence | `references/review-prompt-r1.md` |
| r2 | Coding plan / implementability | `references/review-prompt-r2.md` |
| r3 | Wiring / integration / sequencing | `references/review-prompt-r3.md` |
| r4 | Convergence / residual defects | `references/review-prompt-r4.md` |

After r4, deliver the final hardened plan and report the agent calls made
(8 total across the arc: two agents x four rounds).

**Domain profiles (optional).** The four round prompts are deliberately
general. When the target is a specialized codebase, append the matching profile
from `references/profiles/` to each round prompt so the agents also check that
domain's invariants. Ships with `profiles/comfyui.md` (ComfyUI custom-node
packs: tensor layouts, the node-class contract, VRAM/model-management,
`IS_CHANGED` caching, import isolation). Add your own profiles the same way.

## The loop (steps 1-6 repeat for each of the 4 rounds)

Do not skip the Claude anchor or the grounding step.

1. **Set up.** Identify the document, topic, and repo. Decide the round. If a
   domain profile applies, note which one.

2. **Claude writes its anchor review.** Read the real source files. Write a
   VERDICT + MUST-FIX + SHOULD-FIX review of the *current* plan in the same
   format as the round prompt (`references/review-prompt-r<N>.md`). Label every
   claim CONFIRMED / MISREAD / UNVERIFIABLE against the files you can actually
   see. This is the first input to synthesis.

3. **Fan out - run the local agents.** Call the script (below). It writes the
   plan to `input.md`, then runs each selected agent non-interactively with the
   round prompt (plus any domain profile), capturing one review per agent under
   the run folder.

4. **Ground every agent claim.** Read the agents' reviews. For each distinct
   claim, verify against the *real* files - read the actual source/JSON, or
   spawn subagents to parallelize. Label each claim CONFIRMED, MISREAD (cite the
   covering section), or UNVERIFIABLE (downgrade to a "verify-at-build" note).
   Discard MISREAD and hallucinated claims.

5. **Synthesize (Claude only).** Merge anchor review + verified agent claims:
   dedupe across sources, resolve conflicts with a one-line rationale, guard the
   project's invariants (reject any "fix" that breaks one), keep it lean - no
   changelog, just the improved plan forward. Save as `final.md` (or
   `r<N>_plan.md` if advancing). Keep a short judgment note (accepted /
   rejected-with-reason / verify-at-build items).

6. **Advance.** Feed the updated plan into the next round (r1 -> r2 -> r3 -> r4)
   using that round's prompt. Do not skip rounds. After r4, deliver the final
   hardened plan and the judgment log.

## Calling the fan-out script

`scripts/kibitz.py` does exactly one pass and nothing else. It is
**Python standard library only** - no pip install, no dependencies.

```
python scripts/kibitz.py \
  --doc path/to/plan.md \
  --round r1 \
  --topic ending-mode \
  --repo /path/to/your/repo
```

- `--repo` defaults to the current directory, so if you run from the repo root
  you can omit it.
- `--round {r1,r2,r3,r4}` picks the round prompt. Run all four across the arc.
- `--only codex` or `--only antigravity` runs a single agent (repeatable);
  default is both.
- `--timeout <seconds>` is optional; default is no ceiling (agents batch and can
  take minutes). Only set it if you need to bail on a hung agent.
- Inline text works instead of `--doc`:
  `python scripts/kibitz.py "harden the ending-mode plan" --round r1`.

Output lands in `<repo>/kibitz-runs/<YYYY-MM-DD>-<topic>/<round>/` as
`input.md`, `<agent>.md`, and `<agent>.log`. Claude then writes `final.md`
there after grounding and synthesis.

## First-run check and quota discipline

- **Eyeball `<agent>.md` on the first run.** The file-handoff means `<agent>.md`
  is the agent's own written review. Success is judged by exit code + the file
  existing and being non-empty - the script does NOT verify the file actually
  *contains a review* rather than an error message. If it is empty (or is an
  "I can't access the repo" note) with exit 0, the agent ignored the write
  directive: check `<agent>.log` and re-run once.
- **`agy` has a per-prompt quota.** A full arc is 8 agent calls (two agents x
  four rounds), which is fine, but the per-prompt ceiling can bite on
  high-volume loops.
- **4 rounds is the arc.** Do not add passes beyond r4 unless the user asks.

## Conventions

Write artifacts as UTF-8, no BOM, ASCII where practical. Save everything under
`<repo>/kibitz-runs/<date>-<topic>/` so the design history is auditable. Never
represent an agent's unverified claim as fact - if it was not grounded against
the code, it is a hypothesis, not a finding.
