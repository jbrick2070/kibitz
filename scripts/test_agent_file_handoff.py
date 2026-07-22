#!/usr/bin/env python3
"""Offline regression for agent file-handoff and stdin handling.

This test shadows codex/agy/claude on PATH with local stub launchers. It never
calls the real CLIs and needs no network or sign-in.
"""
from __future__ import annotations

import datetime
import os
import stat
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KIBITZ = ROOT / "scripts" / "kibitz.py"


STUB_AGENT = r'''
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def prompt_from_args(args: list[str]) -> str:
    return args[-1] if args else ""


def out_path_from_prompt(prompt: str) -> Path:
    lines = prompt.splitlines()
    markers = (
        "to exactly this file:",
        "to this exact path, then stop:",
    )
    for idx, line in enumerate(lines):
        if any(marker in line for marker in markers):
            for candidate in lines[idx + 1:]:
                candidate = candidate.strip()
                if candidate:
                    return Path(candidate)
    raise SystemExit("output path not found in prompt")


def main() -> int:
    agent = sys.argv[1]
    args = sys.argv[2:]

    if agent == "codex" and args[:2] == ["debug", "models"]:
        print(json.dumps({"models": [{"slug": "gpt-5"}]}))
        return 0

    if agent == "codex" and args[:2] == ["login", "status"]:
        print("Logged in using ChatGPT")
        return 0

    if agent == "codex":
        print("CODEX STDOUT REVIEW")
        return 0

    if agent == "claude" and args[:2] == ["auth", "status"]:
        print(json.dumps({"loggedIn": True, "subscriptionType": "max"}))
        return 0

    if agent == "claude":
        print("CLAUDE STDOUT REVIEW")
        return 0

    if agent == "agy" and args[:1] == ["models"]:
        print("Gemini Stub (High)")
        return 0

    if agent == "agy":
        if os.environ.get("KIBITZ_STUB_AGY_MODE") == "empty":
            return 0
        env_out = os.environ.get("KIBITZ_STUB_AGY_OUT")
        out_path = Path(env_out) if env_out else out_path_from_prompt(prompt_from_args(args))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("AGY FILE REVIEW\n", encoding="utf-8")
        return 0

    raise SystemExit(f"unknown stub agent: {agent}")


if __name__ == "__main__":
    raise SystemExit(main())
'''


def write_stub_launchers(fake_bin: Path) -> None:
    stub_py = fake_bin / "stub_agent.py"
    stub_py.write_text(STUB_AGENT, encoding="utf-8")
    for agent in ("codex", "agy", "claude"):
        if os.name == "nt":
            launcher = fake_bin / f"{agent}.cmd"
            body = (
                "@echo off\n"
                f'"{sys.executable}" "%~dp0stub_agent.py" {agent} %*\n'
            )
            launcher.write_text(body, encoding="utf-8")
        else:
            launcher = fake_bin / agent
            launcher.write_text(
                f'#!/bin/sh\nexec "{sys.executable}" "$(dirname "$0")/stub_agent.py" {agent} "$@"\n',
                encoding="utf-8",
            )
            launcher.chmod(launcher.stat().st_mode | stat.S_IEXEC)


def run_kibitz(
    repo: Path,
    plan: Path,
    env: dict[str, str],
    topic: str,
    *agents: str,
    round_id: str = "r1",
) -> subprocess.CompletedProcess[str]:
    run_env = env.copy()
    run_env["KIBITZ_STUB_AGY_OUT"] = str(
        run_dir(repo, topic, round_id) / "antigravity.md"
    )
    cmd = [
        sys.executable,
        str(KIBITZ),
        "--doc",
        str(plan),
        "--round",
        round_id,
        "--topic",
        topic,
        "--repo",
        str(repo),
        "--driver",
        "none",
        "--no-profiles",
        "--timeout",
        "20",
    ]
    for agent in agents:
        cmd += ["--only", agent]
    return subprocess.run(
        cmd,
        cwd=str(ROOT),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        env=run_env,
    )


def run_dir(repo: Path, topic: str, round_id: str = "r1") -> Path:
    return (
        repo
        / "kibitz-runs"
        / f"{datetime.date.today().isoformat()}-{topic}"
        / round_id
    )


def assert_contains(path: Path, expected: str, context: subprocess.CompletedProcess[str] | None = None) -> None:
    if not path.exists():
        detail = ""
        if context is not None:
            detail = f"\nstdout:\n{context.stdout}\nstderr:\n{context.stderr}"
        raise AssertionError(f"{path} does not exist{detail}")
    actual = path.read_text(encoding="utf-8")
    if expected not in actual:
        detail = ""
        if context is not None:
            detail = f"\nstdout:\n{context.stdout}\nstderr:\n{context.stderr}"
        raise AssertionError(f"{path} did not contain {expected!r}; got {actual!r}{detail}")


def write_agy_quota_log(home: Path) -> None:
    log_dir = home / ".gemini" / "antigravity-cli" / "log"
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / "cli-test.log").write_text(
        textwrap.dedent("""\
            I0702 20:52:17 server.go:2578] GetG1Credits: starting fetch
            E0702 20:52:17 http_helpers.go:269] Failed to make code assist backend request (loadCodeAssist): {
              "error": {
                "code": 429,
                "message": "Resource has been exhausted (e.g. check quota).",
                "status": "RESOURCE_EXHAUSTED"
              }
            }
        """),
        encoding="utf-8",
    )


def main() -> int:
    source = KIBITZ.read_text(encoding="utf-8")
    if "stdin=subprocess.DEVNULL" not in source:
        raise AssertionError("scripts/kibitz.py does not close subprocess stdin")

    with tempfile.TemporaryDirectory(prefix="kibitz-agent-stub-") as tmp_raw:
        tmp = Path(tmp_raw)
        repo = tmp / "repo"
        fake_bin = tmp / "bin"
        fake_home = tmp / "home"
        repo.mkdir()
        fake_bin.mkdir()
        fake_home.mkdir()
        plan = tmp / "plan.md"
        plan.write_text("Review this stub plan.\n", encoding="utf-8")
        write_stub_launchers(fake_bin)

        env = os.environ.copy()
        env["PATH"] = str(fake_bin) + os.pathsep + env.get("PATH", "")
        # Keep the regression independent of whichever product UI launches it.
        # The test explicitly names every stub lane below, so standalone mode is
        # the deterministic contract.
        env["KIBITZ_DRIVER"] = "none"
        env["KIBITZ_AGY_MODEL"] = ""
        env["KIBITZ_CLAUDE_MODEL"] = ""
        env["KIBITZ_CLAUDE_EFFORT"] = ""
        env["HOME"] = str(fake_home)
        env["USERPROFILE"] = str(fake_home)
        for key in (
            "KIBITZ_CODEX_QUOTA_PERCENT",
            "KIBITZ_ANTIGRAVITY_USAGE_PERCENT",
            "KIBITZ_AGY_USAGE_PERCENT",
            "KIBITZ_ANTIGRAVITY_QUOTA_PERCENT",
            "KIBITZ_AGY_QUOTA_PERCENT",
            "KIBITZ_CLAUDE_USAGE_PERCENT",
            "KIBITZ_CLAUDE_QUOTA_PERCENT",
        ):
            env.pop(key, None)
        env["KIBITZ_CODEX_USAGE_PERCENT"] = "72"
        env["KIBITZ_QUOTA_RETRY_AFTER"] = "30m"

        ok = run_kibitz(repo, plan, env, "stub-pass", "codex", "claude", "agy")
        if ok.returncode != 0:
            raise AssertionError(textwrap.dedent(f"""\
                expected successful stub pass
                stdout:
                {ok.stdout}
                stderr:
                {ok.stderr}
            """))
        first = run_dir(repo, "stub-pass")
        assert_contains(first / "codex.md", "CODEX STDOUT REVIEW", ok)
        assert_contains(first / "claude.md", "CLAUDE STDOUT REVIEW", ok)
        assert_contains(first / "antigravity.md", "AGY FILE REVIEW", ok)
        assert_contains(first / "codex_quota_status.txt", "usage_percent=72", ok)
        assert_contains(first / "quota_warnings.md", "Codex usage 72%", ok)

        default_agy_env = env.copy()
        default_agy_env.pop("KIBITZ_AGY_MODEL", None)
        default_agy = run_kibitz(
            repo, plan, default_agy_env, "stub-agy-default", "agy"
        )
        if default_agy.returncode != 0:
            raise AssertionError(textwrap.dedent(f"""\
                expected successful default-model Antigravity pass
                stdout:
                {default_agy.stdout}
                stderr:
                {default_agy.stderr}
            """))
        default_agy_dir = run_dir(repo, "stub-agy-default")
        assert_contains(
            default_agy_dir / "agy_model_selected.txt",
            "gemini-3.6-flash-high",
            default_agy,
        )

        budget_env = env.copy()
        budget_env.pop("KIBITZ_CLAUDE_MODEL", None)
        budget_env.pop("KIBITZ_CLAUDE_EFFORT", None)
        budget_env["KIBITZ_CLAUDE_BUDGET"] = "high"
        budget = run_kibitz(repo, plan, budget_env, "stub-claude-budget", "claude")
        if budget.returncode != 0:
            raise AssertionError(textwrap.dedent(f"""\
                expected successful claude budget pass
                stdout:
                {budget.stdout}
                stderr:
                {budget.stderr}
            """))
        budget_dir = run_dir(repo, "stub-claude-budget")
        assert_contains(budget_dir / "claude.md", "CLAUDE STDOUT REVIEW", budget)
        assert_contains(budget_dir / "claude_budget_selected.txt", "budget=high", budget)
        assert_contains(budget_dir / "claude_budget_selected.txt", "model=opus", budget)
        assert_contains(budget_dir / "claude_budget_selected.txt", "effort=max", budget)

        resume_topic = "stub-resume"
        prior_dir = run_dir(repo, resume_topic, "r2")
        prior_dir.mkdir(parents=True)
        prior_input = prior_dir / "input.md"
        prior_input.write_text("R2 input.\n", encoding="utf-8")
        (prior_dir / "driver_anchor.md").write_text(
            "R2 driver anchor.\n", encoding="utf-8"
        )
        (prior_dir / "antigravity.md").write_text(
            "R2 Antigravity review.\n", encoding="utf-8"
        )
        (prior_dir / "claude.md").write_text(
            "R2 Claude review.\n", encoding="utf-8"
        )
        (prior_dir / "judgment.md").write_text(
            "R2 judgment.\n", encoding="utf-8"
        )
        prior_final = prior_dir / "final.md"
        # Deliberately use LF bytes. The historical text-mode implementation
        # rewrote these to CRLF on Windows and violated resume hash identity.
        prior_final.write_bytes(b"R2 hardened final.\n")

        resumed = run_kibitz(
            repo,
            prior_final,
            env,
            resume_topic,
            "claude",
            round_id="r3",
        )
        if resumed.returncode != 0:
            raise AssertionError(textwrap.dedent(f"""\
                expected successful r2 -> r3 continuation pass
                stdout:
                {resumed.stdout}
                stderr:
                {resumed.stderr}
            """))
        resumed_dir = run_dir(repo, resume_topic, "r3")
        if (resumed_dir / "input.md").read_bytes() != prior_final.read_bytes():
            raise AssertionError("resumed r3 input is not byte-identical to r2 final")
        assert_contains(resumed_dir / "claude.md", "CLAUDE STDOUT REVIEW", resumed)
        if "Round:      r3" not in resumed.stdout:
            raise AssertionError("resumed run did not report r3")
        if "Write your own code-grounded anchor review" in resumed.stdout:
            raise AssertionError("post-run instructions still place the anchor after fan-out")
        if "driver anchor was written before this fan-out" not in resumed.stdout:
            raise AssertionError("post-run instructions do not preserve anchor-before-fan-out")

        empty_env = env.copy()
        empty_env["KIBITZ_STUB_AGY_MODE"] = "empty"
        write_agy_quota_log(fake_home)
        degraded = run_kibitz(repo, plan, empty_env, "stub-empty", "codex", "agy")
        if degraded.returncode != 0:
            raise AssertionError(textwrap.dedent(f"""\
                expected degraded pass with codex still OK
                stdout:
                {degraded.stdout}
                stderr:
                {degraded.stderr}
            """))
        if "quota preflight" not in degraded.stdout:
            raise AssertionError("missing quota preflight failure note")
        second = run_dir(repo, "stub-empty")
        assert_contains(second / "codex.md", "CODEX STDOUT REVIEW", degraded)
        assert_contains(second / "antigravity.md", "RESOURCE_EXHAUSTED", degraded)
        assert_contains(second / "antigravity.log", "quota/backend exhaustion", degraded)
        assert_contains(second / "antigravity_quota_hold.md", "Suggested retry", degraded)
        assert_contains(second / "antigravity_quota_hold.md", "ask when to retry", degraded)
        assert_contains(second / "quota_warnings.md", "Antigravity", degraded)
        empty_review = second / "antigravity.md"
        if "AGY FILE REVIEW" in empty_review.read_text(encoding="utf-8"):
            raise AssertionError("empty agy leg produced a fake review")

    print("agent file-handoff regression: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
