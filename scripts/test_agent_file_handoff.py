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

    if agent == "codex":
        print("CODEX STDOUT REVIEW")
        return 0

    if agent == "claude":
        print("CLAUDE STDOUT REVIEW")
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
            if agent == "codex":
                body = (
                    "@echo off\n"
                    f'"{sys.executable}" "%~dp0stub_agent.py" codex %1 %2\n'
                )
            else:
                body = (
                    "@echo off\n"
                    f'"{sys.executable}" "%~dp0stub_agent.py" {agent}\n'
                )
            launcher.write_text(body, encoding="utf-8")
        else:
            launcher = fake_bin / agent
            launcher.write_text(
                f'#!/bin/sh\nexec "{sys.executable}" "$(dirname "$0")/stub_agent.py" {agent} "$@"\n',
                encoding="utf-8",
            )
            launcher.chmod(launcher.stat().st_mode | stat.S_IEXEC)


def run_kibitz(repo: Path, plan: Path, env: dict[str, str], topic: str, *agents: str) -> subprocess.CompletedProcess[str]:
    run_env = env.copy()
    run_env["KIBITZ_STUB_AGY_OUT"] = str(run_dir(repo, topic) / "antigravity.md")
    cmd = [
        sys.executable,
        str(KIBITZ),
        "--doc",
        str(plan),
        "--round",
        "r1",
        "--topic",
        topic,
        "--repo",
        str(repo),
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


def run_dir(repo: Path, topic: str) -> Path:
    return repo / "kibitz-runs" / f"{datetime.date.today().isoformat()}-{topic}" / "r1"


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


def main() -> int:
    source = KIBITZ.read_text(encoding="utf-8")
    if "stdin=subprocess.DEVNULL" not in source:
        raise AssertionError("scripts/kibitz.py does not close subprocess stdin")

    with tempfile.TemporaryDirectory(prefix="kibitz-agent-stub-") as tmp_raw:
        tmp = Path(tmp_raw)
        repo = tmp / "repo"
        fake_bin = tmp / "bin"
        repo.mkdir()
        fake_bin.mkdir()
        plan = tmp / "plan.md"
        plan.write_text("Review this stub plan.\n", encoding="utf-8")
        write_stub_launchers(fake_bin)

        env = os.environ.copy()
        env["PATH"] = str(fake_bin) + os.pathsep + env.get("PATH", "")
        env["KIBITZ_AGY_MODEL"] = ""
        env["KIBITZ_CLAUDE_MODEL"] = ""
        env["KIBITZ_CLAUDE_EFFORT"] = ""

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

        empty_env = env.copy()
        empty_env["KIBITZ_STUB_AGY_MODE"] = "empty"
        degraded = run_kibitz(repo, plan, empty_env, "stub-empty", "codex", "agy")
        if degraded.returncode != 0:
            raise AssertionError(textwrap.dedent(f"""\
                expected degraded pass with codex still OK
                stdout:
                {degraded.stdout}
                stderr:
                {degraded.stderr}
            """))
        if "agy #76" not in degraded.stdout:
            raise AssertionError("missing agy #76 failure note")
        second = run_dir(repo, "stub-empty")
        assert_contains(second / "codex.md", "CODEX STDOUT REVIEW", degraded)
        empty_review = second / "antigravity.md"
        if empty_review.exists() and empty_review.read_text(encoding="utf-8").strip():
            raise AssertionError("empty agy leg produced a fake review")

    print("agent file-handoff regression: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
