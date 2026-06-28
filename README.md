# kibitz

**Hey -- do you use Claude Cowork to vibe-code your ComfyUI workflows on Windows?** Then you can have
**ChatGPT and Gemini fact-check your work and give it a second look**, right inside Cowork, with this
little skill.

Here's the trick: they don't just read a snippet you paste in -- Codex (ChatGPT) and Antigravity (Gemini)
each read your *whole* repo on your own machine, critique your plan, and then Claude checks everything they
say against your real code and throws out anything that isn't true. A real second and third opinion that
can't bluff, because they actually read the code.

No API keys, no extra bills -- just the ChatGPT and Gemini logins you probably already have.

> Built and tested on **Windows**. Mac/Linux will probably work (the commands are included) but aren't
> tested yet -- if you try it, let me know how it goes.

## One-click install (Claude Cowork)

Grab [`kibitz.skill`](kibitz.skill) from this repo, open it in Claude Cowork, and click
**Save skill**. That's it -- the whole skill (the `kibitz.py` script, the round prompts, and the
ComfyUI profile) installs together in one click, so nothing is left out. Then you only need the two
CLIs signed in (see below), and you can type `/kibitz` on any plan.

## The easy way: let your AI install it for you

Open Claude Cowork (or Claude Code) and paste this one prompt. It tells your AI to do the whole setup --
**1) install the skill, 2) install the Codex CLI, 3) install the agy CLI** -- and stop only when you need
to sign in. Then... poof, you're set.

The same prompt also lives in [`install/setup-with-claude.md`](install/setup-with-claude.md).
Copy it from there or straight from this block:

```
I want to use the "kibitz" skill so ChatGPT and Gemini can fact-check my code. Set it up for me from
https://github.com/jbrick2070/kibitz -- do as much yourself as you can, and only stop when I need to
sign in somewhere.

1. INSTALL THE SKILL: clone https://github.com/jbrick2070/kibitz and put the kibitz skill folder where my
   Claude looks for skills (you know where that is on this machine -- if you're not sure, check my Claude
   settings / skills directory and place it there so typing `/kibitz` works).
2. INSTALL THE CODEX CLI (ChatGPT's coding agent, the `codex` command): if it's missing, on Windows run
   `powershell -ExecutionPolicy ByPass -c "irm https://chatgpt.com/codex/install.ps1 | iex"` (Mac/Linux:
   `npm install -g @openai/codex`), then tell me to run `codex` once and sign in with my ChatGPT account.
3. INSTALL THE ANTIGRAVITY CLI (Gemini's coding agent, the `agy` command): if it's missing, on Windows run
   `irm https://antigravity.google/cli/install.ps1 | iex` (Mac/Linux:
   `curl -fsSL https://antigravity.google/cli/install.sh | bash`), then tell me to run `agy` once and sign
   in with my Google account.
4. Run kibitz's `scripts/doctor.py` and show me the results -- every check should be green.
5. Prove it works: run a tiny kibitz pass on a one-line sample plan and show me both ChatGPT's and Gemini's
   reviews.

When it's all green, give me a simple "you're ready" and remind me I just type `/kibitz` on any plan to use it.
```

## Prefer to do it by hand? Manual install

If you would rather drive it yourself, here are the same steps as plain commands.
Same order as the prompt: **skill first, then the two CLIs.**

**1. Get kibitz and install the skill.** Clone the repo:

```
git clone https://github.com/jbrick2070/kibitz
```

Then copy the `kibitz` folder into the folder where your Claude Code or Claude
Cowork keeps its skills, so typing `/kibitz` works. If you are not sure where that
is, just ask your Claude: "where do my skills live?" - then copy the folder there.

**2. Check Python.** You need Python 3.9 or later (kibitz uses only Python's
built-in tools - there is nothing to `pip install`). Check with:

```
python --version
```

If that prints `Python 3.9` or higher, you are set. If not, install Python from
[python.org](https://www.python.org/downloads/).

**3. Install OpenAI Codex (ChatGPT's coding agent) and sign in.**

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

- Sign in: run `codex` once and log in with a ChatGPT account (Plus, Pro, or
  Team) or an API key. If the browser sign-in does not work, run
  `codex login --device-auth` instead.

- Check it worked:

  ```
  codex --version
  ```

  (On Windows it installs under `%LOCALAPPDATA%\OpenAI\Codex`.) Docs:
  [developers.openai.com/codex/cli](https://developers.openai.com/codex/cli).

**4. Install Google Antigravity (Gemini's coding agent) and sign in.**

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

**5. Run the doctor.** From inside the kibitz folder:

```
python scripts/doctor.py
```

Make every line green (see the next section for what each check means).

## Check everything works

`scripts/doctor.py` is a quick preflight that tells you, in plain English,
whether your machine is ready. It does *not* call the agents - it just confirms
they are installed. It checks:

- **Python 3.9 or later** - the version kibitz needs.
- **The `codex` command** - found on your PATH or in `%LOCALAPPDATA%\OpenAI\Codex`.
  If it is missing, the doctor prints the exact install command.
- **The `agy` command** - found on your PATH or in `%LOCALAPPDATA%\agy\bin`.
  Same - it prints the install hint if missing.
- **The kibitz files** - all the skill's pieces are present and the main script
  is valid.

At the end it prints **READY** or **NOT READY YET**. If only one agent is
installed, it will still say you can run, just with a one-agent panel. The doctor
cannot check whether you are signed in (that only happens the first time you run
each agent yourself) - it will remind you of that.

Then the tiny real test: in Claude, point at a short plan and say `/kibitz` (or
just "run kibitz"). You will see both agents go off, read the repo, and return a
review.

## How to use it day to day

Point Claude at a plan, spec, or design doc and say "run kibitz on this." Kibitz
then walks a fixed **4-round arc**, each round with a different lens:

| Round | What it looks at |
|-------|------------------|
| r1 | The big picture - does the overall approach hang together? |
| r2 | The coding plan - is it actually buildable? |
| r3 | The wiring - do the pieces connect and sequence correctly? |
| r4 | Final pass - anything still broken? |

In every round, the two agents read your real code and write their own reviews,
and then **Claude is the judge**: it grounds every claim each agent makes against
your actual code, throws out the ones that are wrong, and folds the rest into a
better version of the plan. The output lands in a `kibitz-runs\` folder inside
your repo, so you have a full record of what was suggested, kept, and rejected.

## Troubleshooting

| You see... | Do this |
|------------|---------|
| `codex` or `agy` "not found" | Close and reopen your terminal so it picks up the new PATH. If it is still missing, it may be installed at `%LOCALAPPDATA%\OpenAI\Codex` (Codex) or `%LOCALAPPDATA%\agy\bin` (Antigravity). |
| "not signed in" / it asks you to log in | Run the bare command once on its own - `codex` or `agy` - and complete the sign-in. After that, kibitz can use it. |
| The wrong `codex` got installed | If you installed the plain `codex` npm package by mistake, uninstall it (`npm uninstall -g codex`) and install the scoped one: `npm install -g @openai/codex`. |
| Only one agent is installed | Kibitz still runs with the one you have (a "degraded" one-agent panel). It only fails if *both* are missing. |

## A note on safety

Please read this before running kibitz on a repo you care about. It is gentle,
but it matters.

- **Codex reads only - it cannot change your files.** That is the safe lane.
- **Antigravity runs without a sandbox.** To hand its review back, kibitz lets it
  write that one review file, which means it is technically allowed to touch the
  disk. It is told, firmly, to review only and write nothing else.
- Because of that, if you are ever feeding in input you do not fully trust, run it
  in a **throwaway git worktree** (a disposable copy of your repo) rather than your
  live project.
- **Keep your repo committed to git.** Then your tree is clean before a run, and if
  any agent ever made a stray edit, it would show up immediately in `git status`
  and you could undo it with one command.

## License

MIT. See [`LICENSE`](LICENSE).
