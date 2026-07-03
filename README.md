# kibitz

**Hey -- do you use local coding agents to harden ComfyUI workflows on Windows?** Then you can have
**multiple independent model families fact-check your work and give it a second look**, right inside
your local agent flow, with this little skill.

Here's the trick: they don't just read a snippet you paste in. Your active driver
(Claude, Codex, Antigravity, or another supported host) writes its own grounded
anchor review, then Kibitz fans out to the other local reviewer lanes. The current
lanes are Codex, Antigravity, and Claude Code, but the design goal is model-family
diversity rather than loyalty to any one brand. Each lane reads your *whole* repo
on your machine, critiques your plan, and then the active driver checks everything
they say against your real code and throws out anything that isn't true. A real
multi-system second opinion that can't bluff, because they actually read the code.

No API keys -- just the local agent logins you probably already have.

> Built and tested on **Windows**. Mac/Linux will probably work (the commands are included) but aren't
> tested yet -- if you try it, let me know how it goes.

## The easy way (recommended): paste one prompt, your AI does the rest

This is how most people install it -- and it's the most reliable path. Open your
preferred host assistant and paste the prompt below. It tells your AI to do the
whole setup -- **1) install the skill, 2) install the OpenAI-family CLI lane, 3)
install the Google-family CLI lane, 4) install/check the Anthropic-family CLI
lane** -- and stop only when you need to sign in. Then... poof, you're set.
(Same prompt also lives in [`install/setup-with-claude.md`](install/setup-with-claude.md).)

```
I want to use the "kibitz" skill so multiple local model families can fact-check my code. Set it up for me from
https://github.com/jbrick2070/kibitz -- do as much yourself as you can, and only stop when I need to
sign in somewhere.

1. INSTALL THE SKILL: clone https://github.com/jbrick2070/kibitz to a folder I'll keep, and install the
   skill from that clone into wherever my host looks for skills. KEEP the clone -- the kibitz script lives
   in its `scripts/` folder and that's what actually runs the agents (so typing `/kibitz` works).
2. INSTALL THE CODEX CLI (OpenAI-family coding agent lane, the `codex` command): if it's missing, on Windows run
   `powershell -ExecutionPolicy ByPass -c "irm https://chatgpt.com/codex/install.ps1 | iex"` (Mac/Linux:
   `npm install -g @openai/codex`), then tell me to run `codex` once and sign in with my OpenAI/ChatGPT account.
3. INSTALL THE ANTIGRAVITY CLI (Google-family coding agent lane, the `agy` command): if it's missing, on Windows run
   `irm https://antigravity.google/cli/install.ps1 | iex` (Mac/Linux:
   `curl -fsSL https://antigravity.google/cli/install.sh | bash`), then tell me to run `agy` once and sign
   in with my Google account.
4. INSTALL OR CHECK CLAUDE CODE CLI (Anthropic-family coding agent lane, the `claude` command): if it's missing, install
   Claude Code, then tell me to run `claude` once and sign in with my Claude account.
5. Run kibitz's `scripts/doctor.py` and show me the results -- every check must be green (it confirms
   `codex`, `agy`, and `claude` resolve, even when they live in their Windows install dirs).
6. Prove it works: run kibitz's `scripts/kibitz.py` for a tiny one-round pass on a one-line sample plan,
   using the correct `--driver` for this host. Show me the driver-aware reviewer set it picked. Explain
   that Kibitz selects reviewer lanes by model family: Anthropic-family driver -> OpenAI + Google-family
   lanes; OpenAI-family driver -> Google + Anthropic-family lanes; Google-family driver -> OpenAI +
   Anthropic-family lanes; `--driver none` or `--all-agents` -> all configured lanes. Use `--dry-run`
   first if you only need to verify selection without spending prompts. Always run kibitz through
   `scripts/kibitz.py` -- never improvise your own agent calls.
7. If I am using Kibitz on a ComfyUI custom-node repo, offer to generate a local profile with
   `scripts/comfyui_profile.py --repo <repo> --workflow <workflow.json> --write`. Explain that this writes
   `.kibitz/comfyui.local.md`, auto-detecting local/cloud runtime hints, ComfyUI root, user prefs,
   model paths/inventory, custom nodes, and active local ComfyUI servers when possible.

When it's all green, give me a simple "you're ready" and remind me I just type `/kibitz` on any plan.
```

## Or install in one click (supported hosts)

Prefer not to paste the prompt? Grab [`kibitz.skill`](kibitz.skill), open it in a
host that supports `.skill` bundles (Claude Cowork does), and click **Save
skill** -- the whole skill (script, round prompts, ComfyUI profile) installs
together in one click. You'll still need the three CLIs signed in (steps 2-4 of
the prompt above).

## Prefer to do it by hand? Manual install

If you would rather drive it yourself, here are the same steps as plain commands.
Same order as the prompt: **skill first, then the three CLIs.**

**1. Get kibitz and install the skill.** Clone the repo:

```
git clone https://github.com/jbrick2070/kibitz
```

Then copy the `kibitz` folder into the folder where your host keeps its skills, so
typing `/kibitz` works. If you are not sure where that is, ask your host assistant:
"where do my skills live?" - then copy the folder there.

**2. Check Python.** You need Python 3.9 or later (kibitz uses only Python's
built-in tools - there is nothing to `pip install`). Check with:

```
python --version
```

If that prints `Python 3.9` or higher, you are set. If not, install Python from
[python.org](https://www.python.org/downloads/).

**3. Install OpenAI Codex (OpenAI-family coding agent lane) and sign in.**

- Windows:

  ```
  powershell -ExecutionPolicy ByPass -c "irm https://chatgpt.com/codex/install.ps1 | iex"
  ```

- Mac / Linux (needs Node.js 22 or later):

  ```
  npm install -g @openai/codex
  ```

  **Important:** it must be the scoped name `@openai/codex`. The plain `codex`
  package on npm is an unrelated project from 2012 - do not install that one.

- Sign in: run `codex` once and log in with an OpenAI/ChatGPT account (Plus, Pro, or
  Team) or an API key. If the browser sign-in does not work, run
  `codex login --device-auth` instead.

- Check it worked:

  ```
  codex --version
  ```

  (On Windows it installs under `%LOCALAPPDATA%\OpenAI\Codex`.) Docs:
  [developers.openai.com/codex/cli](https://developers.openai.com/codex/cli).

**4. Install Google Antigravity (Google-family coding agent lane) and sign in.**

- Windows:

  ```
  irm https://antigravity.google/cli/install.ps1 | iex
  ```

- Mac / Linux:

  ```
  curl -fsSL https://antigravity.google/cli/install.sh | bash
  ```

- Sign in: run `agy` once and log in with a Google account.

- Check it worked:

  ```
  agy --version
  ```

  (On Windows it installs under `%LOCALAPPDATA%\agy\bin`.) Docs:
  [antigravity.google/docs/cli-getting-started](https://antigravity.google/docs/cli-getting-started).

**5. Install Claude Code (Anthropic-family coding agent lane) and sign in.**

- Install Claude Code from Anthropic, then run:

  ```
  claude
  ```

- Sign in with your Claude account.

- Check it worked:

  ```
  claude --version
  ```

  (On this Windows setup it commonly lives under `%USERPROFILE%\.local\bin`.)

**6. Run the doctor.** From inside the kibitz folder:

```
python scripts/doctor.py
```

Make every line green (see the next section for what each check means).

**7. Optional: generate a local ComfyUI profile for a repo.** The shipped
ComfyUI profile checks general invariants. Your machine still has local facts:
GPU/VRAM, cloud-vs-local runtime, ComfyUI root, user prefs, model paths,
canonical workflow JSON, custom nodes, output paths, active server ports, and
project rules. Generate a local overlay from the kibitz folder:

```
python scripts/comfyui_profile.py --repo C:\path\to\ComfyUI\custom_nodes\MyNodePack --workflow workflows\my_workflow.json --vram-budget-gb 16 --write
```

That writes `.kibitz\comfyui.local.md` inside the target repo. It auto-detects
ComfyUI roots by walking up from the repo and checking common env vars, probes
local ComfyUI ports (`8000`, `8188` by default), summarizes `user\default`
settings/workflows, reads `extra_model_paths*.yaml`, inventories model-like
files, records Hugging Face cache model ids, and lists installed custom nodes.
Kibitz auto-appends it, together with the generic ComfyUI profile, on future
runs in that repo. The helper also adds `.kibitz/*.local.md` to the target repo's
local `.git/info/exclude` so machine-specific facts stay out of commits.
Existing local profiles are protected; add `--force` if you really want to
regenerate one.

Kibitz does **not** update `CLAUDE.md` automatically. If you want a safe pointer
for Claude/Cowork to notice the local profile, print a snippet and paste it
yourself:

```
python scripts/comfyui_profile.py --repo C:\path\to\repo --emit-claude-snippet
```

There is also an explicit opt-in writer. It only appends or updates a small
marker-wrapped pointer block, never the full local profile, and it makes a
timestamped backup when `CLAUDE.md` already exists:

```
python scripts/comfyui_profile.py --repo C:\path\to\repo --append-claude-md
```

Useful overrides for cloud pods or unusual installs:

```
python scripts/comfyui_profile.py --repo . --comfyui-root /workspace/ComfyUI --models-dir /runpod-volume/models --ports 8188 --write
```

## Check everything works

`scripts/doctor.py` is a quick preflight that tells you, in plain English,
whether your machine is ready. It does *not* call the agents - it just confirms
they are installed. It checks:

- **Python 3.9 or later** - the version kibitz needs.
- **The `codex` command** - found on your PATH or in `%LOCALAPPDATA%\OpenAI\Codex`.
  If it is missing, the doctor prints the exact install command.
- **The `agy` command** - found on your PATH or in `%LOCALAPPDATA%\agy\bin`.
  Same - it prints the install hint if missing.
- **The `claude` command** - found on your PATH or in `%USERPROFILE%\.local\bin`.
  Same - it prints the install hint if missing.
- **The kibitz files** - all the skill's pieces are present and the Python
  entry points are valid.

At the end it prints **READY** or **NOT READY YET**. If only one agent is
installed, it will still say you can run, just with a one-agent panel. The doctor
cannot check whether you are signed in (that only happens the first time you run
each agent yourself) - it will remind you of that.

Then the tiny real test: in your active host, point at a short plan and say
`/kibitz` (or just "run kibitz"). You will see the local agents go off, read the
repo, and return reviews.

Kibitz is **multi-system aware**. It tries to detect the active driver, and you
can make that explicit:

```
python scripts/kibitz.py --doc plan.md --round r1 --driver claude
python scripts/kibitz.py --doc plan.md --round r1 --driver codex
python scripts/kibitz.py --doc plan.md --round r1 --driver agy
python scripts/kibitz.py --doc plan.md --round r1 --driver none
```

- Anthropic-family driver (`--driver claude`) -> OpenAI + Google-family reviewer lanes.
- OpenAI-family driver (`--driver codex`) -> Google + Anthropic-family reviewer lanes.
- Google-family driver (`--driver agy`) -> OpenAI + Anthropic-family reviewer lanes.
- `--driver none` or `--all-agents` -> all configured reviewer lanes.
- Repeated `--only` flags override driver-aware selection.
- Add `--dry-run` to verify the selected driver/reviewer set without calling any
  agents.
- Add `--profile comfyui` to force the generic ComfyUI profile. If
  `.kibitz\comfyui.local.md` exists in the target repo, Kibitz auto-adds it and
  the generic profile. Use `--no-profiles` for a profile-free run.

When Kibitz is invoked from a product UI, that live UI is already the
driver/panelist for its model family. Do not launch the same system's CLI as a
second reviewer from the base OS. In Antigravity UI, use `--driver agy` (or
`--only codex --only claude`) so Antigravity participates through the UI anchor,
not through an `agy` subprocess. Avoid `--all-agents` / `--only agy` there unless
you are intentionally testing the CLI outside the UI.

## How to use it day to day

Point your active host at a plan, spec, or design doc and say "run kibitz on this." Kibitz
then walks a fixed **4-round arc**, each round with a different lens:

| Round | What it looks at |
|-------|------------------|
| r1 | The big picture - does the overall approach hang together? |
| r2 | The coding plan - is it actually buildable? |
| r3 | The wiring - do the pieces connect and sequence correctly? |
| r4 | Final pass - anything still broken? |

In every round, the driver writes the anchor review, the external reviewer agents
read your real code and write their own reviews, and then **the active driver is
the judge**: it grounds every claim each agent makes against your actual code,
throws out the ones that are wrong, and folds the rest into a better version of
the plan. The output lands in a `kibitz-runs\` folder inside your repo, so you
have a full record of what was suggested, kept, and rejected. Each run also gets
lightweight quota/status files like `<agent>_quota_status.txt`; if a provider
reports quota, credit, or rate-limit exhaustion, Kibitz writes
`<agent>_quota_hold.md` with the diagnostic and a suggested retry window.

## Troubleshooting

| You see... | Do this |
|------------|---------|
| `codex`, `agy`, or `claude` "not found" | Close and reopen your terminal so it picks up the new PATH. If it is still missing, it may be installed at `%LOCALAPPDATA%\OpenAI\Codex` (OpenAI-family lane), `%LOCALAPPDATA%\agy\bin` (Google-family lane), or `%USERPROFILE%\.local\bin` (Anthropic-family lane). |
| "not signed in" / it asks you to log in | Run the bare command once on its own - `codex`, `agy`, or `claude` - and complete the sign-in. After that, kibitz can use it. |
| The wrong `codex` got installed | If you installed the plain `codex` npm package by mistake, uninstall it (`npm uninstall -g codex`) and install the scoped one: `npm install -g @openai/codex`. |
| Only one agent is installed | Kibitz still runs with the one you have (a "degraded" one-agent panel). It only fails if all agents are missing. |
| Antigravity is out of quota | Use `--only codex --only claude` for that round. |
| Antigravity says only `timeout waiting for response` | Check `<run>\antigravity.log`. If recent `agy` CLI logs contain `RESOURCE_EXHAUSTED`, `code 429`, `check quota`, or `Individual quota reached`, Kibitz annotates the failed review file with a quota/backend exhaustion diagnostic. Without those markers, treat it as an `agy` timeout/print-mode failure, not proven credits. |
| Kibitz writes `<agent>_quota_hold.md` | Tell the user this lane failed on quota/credit/rate-limit usage. Ask when they want to retry, or use the built-in retry window in the hold file. Default is `1h`; override with `KIBITZ_QUOTA_RETRY_AFTER=30m`, `4h`, etc. |
| You want earlier usage warnings | Keep the default `KIBITZ_QUOTA_WARN_THRESHOLDS=50,70,90` or change it. Warnings fire only when Kibitz has a real percentage from a status surface or an explicit env override such as `KIBITZ_CODEX_USAGE_PERCENT`, `KIBITZ_AGY_USAGE_PERCENT`, or `KIBITZ_CLAUDE_USAGE_PERCENT`. |
| Antigravity exits rc=0 but produces no review | Kibitz treats that as a failed leg, not success. This is the known captured-stdout drop in `agy -p` (#76/#408); the remaining reviewer lanes and the driver anchor can continue. |
| Kibitz picked the wrong driver | Pass `--driver claude`, `--driver codex`, `--driver agy`, or set `KIBITZ_DRIVER` before launching it. |

## A note on safety

Please read this before running kibitz on a repo you care about. It is gentle,
but it matters.

- **The Codex lane reads only - it cannot change your files.** That is the safe lane.
- **The Antigravity lane runs without a sandbox.** To hand its review back, kibitz lets it
  write that one review file, which means it is technically allowed to touch the
  disk. It is told, firmly, to review only and write nothing else. Do not put
  this lane in a fully OS-enforced read-only mode, or it cannot write the one
  review file Kibitz needs while `agy -p` drops captured stdout.
- **The Claude Code lane also uses a write-approved file-handoff.** It is restricted to
  Read/Glob/Grep/Write and told to write only its review file.
- Because of that, if you are ever feeding in input you do not fully trust, run it
  in a **throwaway git worktree** (a disposable copy of your repo) rather than your
  live project.
- **Keep your repo committed to git.** Then your tree is clean before a run, and if
  any agent ever made a stray edit, it would show up immediately in `git status`
  and you could undo it with one command.

## License

MIT. See [`LICENSE`](LICENSE).
