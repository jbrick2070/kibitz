# Set up kibitz with Claude

Paste this whole thing into Claude Cowork or Claude Code.

```
I want to use the "kibitz" skill so ChatGPT, Gemini, and Claude Code can fact-check my code. Set it up for me from
https://github.com/jbrick2070/kibitz -- do as much yourself as you can, and only stop when I need to
sign in somewhere.

1. INSTALL THE SKILL: clone https://github.com/jbrick2070/kibitz to a folder I'll keep, and install the
   skill from that clone into wherever my Claude looks for skills. KEEP the clone -- the kibitz script lives
   in its `scripts/` folder and that's what actually runs the agents (so typing `/kibitz` works).
2. INSTALL THE CODEX CLI (ChatGPT's coding agent, the `codex` command): if it's missing, on Windows run
   `powershell -ExecutionPolicy ByPass -c "irm https://chatgpt.com/codex/install.ps1 | iex"` (Mac/Linux:
   `npm install -g @openai/codex`), then tell me to run `codex` once and sign in with my ChatGPT account.
3. INSTALL THE ANTIGRAVITY CLI (Gemini's coding agent, the `agy` command): if it's missing, on Windows run
   `irm https://antigravity.google/cli/install.ps1 | iex` (Mac/Linux:
   `curl -fsSL https://antigravity.google/cli/install.sh | bash`), then tell me to run `agy` once and sign
   in with my Google account.
4. INSTALL OR CHECK CLAUDE CODE CLI (Claude's coding agent, the `claude` command): if it's missing, install
   Claude Code, then tell me to run `claude` once and sign in with my Claude account.
5. Run kibitz's `scripts/doctor.py` and show me the results -- every check must be green (it confirms
   `codex`, `agy`, and `claude` resolve, even when they live in their Windows install dirs).
6. Prove it works: run kibitz's `scripts/kibitz.py` for a tiny one-round pass on a one-line sample plan and
   show me ChatGPT's, Gemini's, and Claude's reviews. Always run kibitz through `scripts/kibitz.py` -- never
   improvise your own agent calls.

When it's all green, give me a simple "you're ready" and remind me I just type `/kibitz` on any plan.
```

Claude will handle the rest and stop only when it needs you to sign in.
