# kibitz

Get a second opinion on a plan, sprint plan, spec, or architecture doc from two
file-reading CLI agents running **locally on your own machine** - Codex
(`codex exec`) and Antigravity (`agy -p`) - with Claude as the grounded judge.
No API key, no cloud spend.

Each agent crawls your **real repo** on its own and returns an independent
review. Claude then writes its own code-grounded review, verifies every agent
claim against the actual code, throws out the hallucinations, and folds only the
survivors into one improved plan. The panel proposes; Claude disposes.

This is a Claude skill: it is driven by Claude Code / Claude Cowork, which
orchestrates the rounds, runs the fan-out script, grounds the claims, and writes
the synthesis. The agents and the script do the fan-out; the judgment is Claude's.

## How it works

Kibitz runs a fixed **4-round arc**, each round with a different lens:

| Round | Focus |
|-------|-------|
| r1 | High-level arc / creative coherence |
| r2 | Coding plan / implementability |
| r3 | Wiring / integration / sequencing |
| r4 | Convergence / residual defects |

Within each round, the loop is **anchor -> fan-out -> ground -> synthesize**:

1. **Anchor.** Claude reads the real source files and writes its own
   code-grounded VERDICT + MUST-FIX review first. Being grounded from the start
   keeps the panel from steering synthesis with plausible-sounding misreads.
2. **Fan-out.** `scripts/kibitz.py` writes the plan to `input.md` and runs each
   agent non-interactively against your real repo, capturing one review per agent.
3. **Ground.** Claude verifies each agent claim against the actual files and
   labels it CONFIRMED, MISREAD, or UNVERIFIABLE. Misreads and hallucinations are
   discarded.
4. **Synthesize.** Claude merges the anchor review and the verified survivors
   into one improved plan, guarding the project's invariants, and advances to the
   next round.

After r4 you get the final hardened plan plus a judgment log of what was
accepted, rejected (with reason), and deferred to verify-at-build.

## Requirements

- **Codex CLI** (`codex`) - installed and authenticated. Runs the read-only
  reviewer lane. (Install/auth: see the Codex CLI project page - link TBD.)
- **Antigravity CLI** (`agy`) - installed and authenticated. Runs the second
  reviewer lane. (Install/auth: see the Antigravity project page - link TBD.)
- **Claude Code / Claude Cowork** - the driver that runs the loop and is the judge.
- **Python 3.9+** - standard library only. No `pip install`, no dependencies.

Exact flags, the model-selection policy, and the tool versions this was proven
on live in [`COMPAT.md`](COMPAT.md). Those move fast; check `codex --help` /
`agy --help` if a flag stops working.

## Quickstart

1. Install the skill so your Claude driver can find it (drop this folder into
   your skills directory, e.g. as `kibitz/`).
2. From your repo root, a single round looks like:

   ```
   python scripts/kibitz.py --doc plan.md --round r1 --topic mytopic --repo .
   ```

   - `--repo` defaults to the current directory.
   - `--round {r1,r2,r3,r4}` selects the round prompt; run all four across the arc.
   - `--only codex` / `--only antigravity` (repeatable) runs a single agent.
   - `--timeout <seconds>` is optional (default: none; agents batch and can take
     minutes).
   - Inline text works instead of `--doc`:
     `python scripts/kibitz.py "harden the plan" --round r1`.

3. Output lands in `<repo>/kibitz-runs/<YYYY-MM-DD>-<topic>/<round>/` as
   `input.md`, `<agent>.md`, and `<agent>.log`. In practice you ask your Claude
   driver to "kibitz this plan" and it runs the full arc for you.

You can smoke-test the package layout without calling the agents:

```
python scripts/smoke_test.py
```

## SAFETY

Read this before running on any repo.

- **Codex runs read-only** (`--sandbox read-only`). The reviewer literally cannot
  edit your repo. This is the safe primary lane.
- **Antigravity runs UNSANDBOXED.** `agy` has no read-only-that-still-writes mode,
  so the file-handoff (the agent writes its own review to a file) requires
  `--dangerously-skip-permissions`. It is gated only by a strict review-only
  prompt directive.
- **Run `agy` in a throwaway git worktree for any untrusted input.** Do not feed
  a prompt you do not trust into an unsandboxed agent against your live tree.
- **Keep the repo git-committed.** Because the tree is clean before a run, any
  stray edit an agent makes shows up immediately in `git status` and is
  revertible. Commit first; review `git status` after.

## Domain profiles

The four round prompts are deliberately general. For a specialized codebase,
append a profile from `references/profiles/` to each round prompt so the agents
also check that domain's invariants. Ships with `profiles/comfyui.md` for
ComfyUI custom-node packs (tensor layouts, the node-class contract,
VRAM/model-management, `IS_CHANGED` caching, import isolation). Add your own
profiles the same way.

## License

MIT. See [`LICENSE`](LICENSE).
