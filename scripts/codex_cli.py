"""Resolve the newest installed Codex CLI without changing PATH or user config."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path


def find_codex(*extra_dirs: str) -> str | None:
    """Honor an explicit launcher; otherwise compare installed CLI versions.

    Desktop updates can leave an older standalone CLI first on PATH. Probe only
    local --version commands; authentication and model discovery belong to the
    caller. An explicit override also keeps offline tests off real CLIs.
    """
    configured = os.environ.get("KIBITZ_CODEX_BIN", "").strip()
    if configured:
        path = Path(configured).expanduser()
        if not path.is_file():
            raise ValueError(f"KIBITZ_CODEX_BIN is not a launcher file: {configured}")
        return str(path)

    candidates = []
    on_path = shutil.which("codex")
    if on_path and "\\windowsapps\\" not in on_path.lower().replace("/", "\\"):
        candidates.append(on_path)
    directories = list(extra_dirs)
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        directories.extend([
            str(Path(local_app_data) / "OpenAI" / "Codex" / "bin"),
            str(Path(local_app_data) / "Programs" / "OpenAI" / "Codex" / "bin"),
        ])
    for directory in dict.fromkeys(directories):
        root = Path(directory)
        if root.is_dir():
            candidates.extend(str(path) for path in sorted(root.rglob("codex.exe")))

    unique = list({os.path.normcase(os.path.abspath(p)): p for p in candidates}.values())
    best, best_version = None, None
    for candidate in unique:
        try:
            proc = subprocess.run(
                [candidate, "--version"], stdin=subprocess.DEVNULL,
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        match = re.search(r"\bcodex-cli (\d+)\.(\d+)\.(\d+)(?:-([^\s]+))?", proc.stdout or "")
        if proc.returncode != 0 or not match:
            continue
        # Semver prerelease identifiers sort numerically when numeric; a stable
        # release wins over a prerelease at the same major/minor/patch.
        prerelease = match.group(4) or ""
        suffix = tuple((0, int(part)) if part.isdecimal() else (1, part)
                       for part in prerelease.split("."))
        version = (*map(int, match.group(1, 2, 3)), not bool(prerelease), suffix)
        if best_version is None or version > best_version:
            best, best_version = candidate, version
    return best or (unique[0] if unique else None)
