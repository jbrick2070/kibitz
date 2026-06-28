# Set up kibitz with Claude

Paste this whole thing into Claude Cowork or Claude Code.

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

Claude will handle the rest and stop only when it needs you to sign in.
