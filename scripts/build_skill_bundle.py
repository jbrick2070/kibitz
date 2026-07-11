#!/usr/bin/env python3
"""Build and verify the one-click ``kibitz.skill`` bundle deterministically."""
from __future__ import annotations

import argparse
import os
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = ROOT / "kibitz.skill"
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)

BUNDLE_FILES = (
    "SKILL.md",
    "COMPAT.md",
    "agents/openai.yaml",
    "scripts/doctor.py",
    "scripts/kibitz.py",
    "scripts/comfyui_profile.py",
    "references/review-prompt-r1.md",
    "references/review-prompt-r2.md",
    "references/review-prompt-r3.md",
    "references/review-prompt-r4.md",
    "references/profiles/comfyui.md",
)


def _zip_info(relative_path: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(relative_path, date_time=FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    return info


def build_bundle(output: Path) -> None:
    missing = [relative for relative in BUNDLE_FILES if not (ROOT / relative).is_file()]
    if missing:
        raise RuntimeError(f"cannot build bundle; missing: {', '.join(missing)}")

    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    try:
        with zipfile.ZipFile(temporary, mode="w") as archive:
            for relative in BUNDLE_FILES:
                archive.writestr(_zip_info(relative), (ROOT / relative).read_bytes())
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)


def verify_bundle(bundle: Path) -> None:
    with zipfile.ZipFile(bundle, mode="r") as archive:
        names = archive.namelist()
        if names != list(BUNDLE_FILES):
            raise RuntimeError(
                "bundle file list/order mismatch:\n"
                f"expected={list(BUNDLE_FILES)!r}\nactual={names!r}"
            )
        if len(names) != len(set(names)):
            raise RuntimeError("bundle contains duplicate paths")
        for relative in BUNDLE_FILES:
            expected = (ROOT / relative).read_bytes()
            actual = archive.read(relative)
            if actual != expected:
                raise RuntimeError(f"bundle payload mismatch: {relative}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="bundle path (default: <repo>/kibitz.skill)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the existing bundle without rebuilding it",
    )
    args = parser.parse_args()

    output = args.output.resolve()
    if not args.check:
        build_bundle(output)
    verify_bundle(output)
    action = "verified" if args.check else "built and verified"
    print(f"kibitz bundle {action}: {output}")
    print(f"files: {len(BUNDLE_FILES)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
