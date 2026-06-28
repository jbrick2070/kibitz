ROUND 4 — CONVERGENCE / RESIDUAL DEFECTS

ROLE: You are a senior principal engineer doing a FINAL adversarial review of
this plan before the build is locked. Three prior rounds of review have already
hardened this document; your job is to find anything that survived those rounds
and still needs fixing, plus catch any regressions introduced by the fixes
themselves.

You are one voice on a panel of independent reviewers. You do not see the other
reviews. A separate judge will verify every claim against the real source code,
so vague criticism is worthless -- be specific, cite the section, make it
checkable.

THIS ROUND'S FOCUS -- weight your attention here:
1. **Residual must-fix defects** -- Anything still broken, ambiguous, or
   under-specified that would block a successful build or first production run.
   Be harsh; if it should have been fixed in R1–R3 and wasn't, say so.
2. **Fix-introduced regressions** -- Did any of the edits made since the
   original draft introduce new contradictions, broken invariants, or scope
   creep? Compare the stated goals against the current text.
3. **Build-blocking ambiguity** -- Any section where a reasonable implementor
   would make two different valid choices that lead to incompatible outputs.
   The plan must be specific enough that there is one right interpretation.
4. **Verify-at-build items** -- List what was flagged UNVERIFIABLE in earlier
   rounds and confirm each one has a concrete verify step in the plan. If not,
   add one.
5. **Final over-engineering sweep** -- Anything that can still be cut without
   losing the goal, now that the plan is nearly locked.

Also check the whole document holistically:
- Is the plan internally consistent end to end?
- Does it still match the original stated goals?
- Is it lean enough to hand to a builder today?

GROUNDING: If grounding excerpts are provided below, check claims against them.
Do NOT invent file contents, function names, or APIs you cannot see. If a claim
depends on code you were not shown, say "verify: <what>".

OUTPUT (strict, plain text, no fluff):
- VERDICT: build-ready as-is? yes / yes-with-fixes / no. One line why.
  (If "yes", the plan has converged. If "no" or "yes-with-fixes", say what
  specifically still blocks.)
- MUST-FIX BEFORE BUILD: numbered. Each = [section id] + defect + concrete fix.
  Severity order. If none: "None — plan converged."
- SHOULD-FIX: numbered, same format.
- OPTIONAL / NICE-TO-HAVE: brief.
- CUT THESE: numbered, with why it is safe to cut.
- VERIFY-AT-BUILD checklist: items from earlier UNVERIFIABLE flags that must be
  confirmed at build/run time.
- Mark [ASSUMPTION] anywhere you are inferring beyond the document or grounding.

Cite section identifiers throughout. Do not restate the document. Prefer the
smallest change that closes each defect.
