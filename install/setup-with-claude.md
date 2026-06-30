# Set up kibitz from a host assistant

Paste this whole thing into a host assistant that can edit files and run local commands.

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

When it's all green, give me a simple "you're ready" and remind me I just type `/kibitz` on any plan.
```

Your host assistant will handle the rest and stop only when it needs you to sign in.
