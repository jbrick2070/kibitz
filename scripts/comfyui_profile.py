#!/usr/bin/env python3
"""Generate a repo-local ComfyUI profile overlay for kibitz.

The generated file is intentionally local and machine-specific:
  .kibitz/comfyui.local.md

Kibitz auto-appends that file, together with the shipped generic ComfyUI
profile, when it exists in the target repo. Python standard library only.
"""
from __future__ import annotations

import argparse
import ast
import datetime
import json
import os
import platform
import subprocess
import sys
from collections import Counter
from pathlib import Path


DEFAULT_OUTPUT = Path(".kibitz") / "comfyui.local.md"
EXCLUDE_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".kibitz",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "venv",
    "__pycache__",
    "kibitz-runs",
    "node_modules",
}
HEAVY_IMPORT_ROOTS = {
    "comfy",
    "cv2",
    "diffusers",
    "numpy",
    "onnxruntime",
    "PIL",
    "safetensors",
    "torch",
    "torchaudio",
    "torchvision",
    "transformers",
}
TENSOR_SIGNALS = {
    "IMAGE": "IMAGE",
    "LATENT": "LATENT",
    "MASK": "MASK",
    "samples": "latent samples",
    "permute(": "permute",
    "movedim(": "movedim",
    "channels_last": "channels_last",
    "channels_first": "channels_first",
    "BHWC": "BHWC",
    "BCHW": "BCHW",
    "NHWC": "NHWC",
    "NCHW": "NCHW",
}
VRAM_SIGNALS = {
    "model_management": "model_management",
    "cuda": "cuda",
    "VRAM": "VRAM",
    "empty_cache": "empty_cache",
    "offload": "offload",
    "cpu()": "cpu()",
    ".to(": ".to(...)",
}


def repo_relative(path: Path, repo: Path) -> str:
    try:
        return str(path.resolve().relative_to(repo.resolve()))
    except ValueError:
        return str(path)


def resolve_repo_path(raw: str | Path, repo: Path) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        path = repo / path
    return path.resolve()


def query_gpus() -> list[dict[str, str]]:
    cmd = [
        "nvidia-smi",
        "--query-gpu=name,memory.total,memory.used",
        "--format=csv,noheader,nounits",
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if proc.returncode != 0:
        return []
    gpus = []
    for line in proc.stdout.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) >= 3:
            gpus.append({"name": parts[0], "total_mb": parts[1], "used_mb": parts[2]})
    return gpus


def find_workflows(repo: Path, supplied: list[str]) -> list[Path]:
    if supplied:
        return [resolve_repo_path(item, repo) for item in supplied]

    workflows_dir = repo / "workflows"
    candidates: list[Path] = []
    if workflows_dir.is_dir():
        candidates.extend(sorted(workflows_dir.glob("*.json")))

    if not candidates:
        candidates.extend(
            sorted(
                path
                for path in repo.glob("*.json")
                if "workflow" in path.name.lower() or "comfy" in path.name.lower()
            )
        )

    return candidates[:20]


def summarize_workflow(path: Path, repo: Path) -> dict[str, object]:
    summary: dict[str, object] = {
        "path": repo_relative(path, repo),
        "exists": path.is_file(),
    }
    if not path.is_file():
        summary["error"] = "file not found"
        return summary

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        summary["error"] = f"could not parse JSON: {exc}"
        return summary

    nodes = data.get("nodes") if isinstance(data, dict) else None
    links = data.get("links") if isinstance(data, dict) else None
    if not isinstance(nodes, list):
        summary["error"] = "not a LiteGraph/API workflow with a top-level nodes[] list"
        return summary

    type_counts: Counter[str] = Counter()
    widget_total = 0
    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_type = node.get("type") or node.get("class_type") or "<unknown>"
        type_counts[str(node_type)] += 1
        widgets = node.get("widgets_values")
        if isinstance(widgets, list):
            widget_total += len(widgets)

    summary.update(
        {
            "nodes": len(nodes),
            "links": len(links) if isinstance(links, list) else "unknown",
            "widgets": widget_total,
            "top_types": type_counts.most_common(12),
        }
    )
    return summary


def iter_python_files(repo: Path):
    for root, dirs, files in os.walk(repo):
        root_path = Path(root)
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for name in files:
            if name.endswith(".py"):
                yield root_path / name


def top_level_import_roots(tree: ast.Module) -> list[str]:
    roots: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            roots.extend(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.append(node.module.split(".")[0])
    return roots


def scan_python(repo: Path) -> dict[str, object]:
    mapping_files: list[str] = []
    display_mapping_files: list[str] = []
    input_type_files: list[str] = []
    heavy_imports: dict[str, list[str]] = {}
    tensor_signals: dict[str, list[str]] = {}
    vram_signals: dict[str, list[str]] = {}
    parse_errors: list[str] = []

    for path in iter_python_files(repo):
        rel = repo_relative(path, repo)
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                text = path.read_text(encoding="utf-8-sig")
            except UnicodeDecodeError:
                parse_errors.append(f"{rel}: could not read as UTF-8")
                continue

        if "NODE_CLASS_MAPPINGS" in text:
            mapping_files.append(rel)
        if "NODE_DISPLAY_NAME_MAPPINGS" in text:
            display_mapping_files.append(rel)
        if "INPUT_TYPES" in text:
            input_type_files.append(rel)
        found_tensor_signals = sorted(label for token, label in TENSOR_SIGNALS.items() if token in text)
        if found_tensor_signals:
            tensor_signals[rel] = found_tensor_signals
        found_vram_signals = sorted(label for token, label in VRAM_SIGNALS.items() if token in text)
        if found_vram_signals:
            vram_signals[rel] = found_vram_signals

        try:
            tree = ast.parse(text, filename=str(path))
        except SyntaxError as exc:
            parse_errors.append(f"{rel}: {exc.msg} at line {exc.lineno}")
            continue

        imports = sorted(set(top_level_import_roots(tree)) & HEAVY_IMPORT_ROOTS)
        if imports:
            heavy_imports[rel] = imports

    return {
        "mapping_files": mapping_files[:40],
        "display_mapping_files": display_mapping_files[:40],
        "input_type_files": input_type_files[:40],
        "heavy_imports": heavy_imports,
        "tensor_signals": dict(list(tensor_signals.items())[:40]),
        "vram_signals": dict(list(vram_signals.items())[:40]),
        "parse_errors": parse_errors[:40],
    }


def format_workflow(summary: dict[str, object]) -> list[str]:
    lines = [f"- `{summary['path']}`"]
    if not summary.get("exists"):
        lines.append(f"  - status: {summary.get('error', 'missing')}")
        return lines
    if summary.get("error"):
        lines.append(f"  - status: {summary['error']}")
        return lines
    lines.append(
        f"  - nodes: {summary['nodes']}; links: {summary['links']}; widget slots: {summary['widgets']}"
    )
    top_types = summary.get("top_types") or []
    if top_types:
        rendered = ", ".join(f"{name} x{count}" for name, count in top_types)
        lines.append(f"  - common node types: {rendered}")
    return lines


def build_profile(args: argparse.Namespace, repo: Path) -> str:
    workflows = [summarize_workflow(path, repo) for path in find_workflows(repo, args.workflow)]
    py_scan = scan_python(repo)
    gpus = query_gpus()
    generated = datetime.datetime.now(datetime.timezone.utc).astimezone().isoformat(timespec="seconds")
    profile_path = resolve_repo_path(args.output, repo)

    lines: list[str] = [
        "# Local ComfyUI Profile for Kibitz",
        "",
        f"Generated: `{generated}`",
        f"Repo: `{repo}`",
        f"Profile path: `{repo_relative(profile_path, repo)}`",
        "",
        "Kibitz auto-appends this local overlay when it exists, together with the shipped generic ComfyUI profile.",
        "Reviewer agents must treat the facts below as repo/user-specific constraints and write `verify:` instead of guessing when a value is unknown.",
        "",
        "## Hardware / VRAM",
        "",
        f"- OS: `{platform.platform()}`",
        f"- Python: `{platform.python_version()}`",
    ]
    if gpus:
        for index, gpu in enumerate(gpus):
            lines.append(
                f"- GPU {index}: `{gpu['name']}`; total VRAM: `{gpu['total_mb']} MiB`; currently used: `{gpu['used_mb']} MiB`"
            )
    else:
        lines.append("- GPU: `unknown` (`nvidia-smi` was not available or returned no GPU data)")
    if args.vram_budget_gb:
        lines.append(f"- Review VRAM budget: `{args.vram_budget_gb} GiB`")
    else:
        lines.append("- Review VRAM budget: `unknown`; reviewers should verify before recommending always-resident models or large caches")

    lines.extend(["", "## Local Paths", ""])
    if args.comfyui_root:
        lines.append(f"- ComfyUI root: `{resolve_repo_path(args.comfyui_root, repo)}`")
    else:
        lines.append("- ComfyUI root: `unknown`")
    if args.output_base:
        lines.append(f"- ComfyUI output base: `{resolve_repo_path(args.output_base, repo)}`")
    else:
        lines.append("- ComfyUI output base: `unknown`")

    lines.extend(["", "## Canonical Workflows", ""])
    if workflows:
        for summary in workflows:
            lines.extend(format_workflow(summary))
    else:
        lines.append("- No workflow JSON was supplied or auto-discovered. Pass `--workflow <path>` to make workflow wiring checks concrete.")
    lines.extend(
        [
            "",
            "Workflow-specific review rules:",
            "- If a plan changes node inputs, widgets, outputs, or wiring, reviewers must check the canonical workflow files above.",
            "- LiteGraph `widgets_values` are positional; appending optional widgets is safer than inserting in the middle.",
            "- Code that is not registered and wired into the relevant workflow should be treated as dormant until proven otherwise.",
        ]
    )

    lines.extend(["", "## Custom Node Package Scan", ""])
    mapping_files = py_scan["mapping_files"]
    display_mapping_files = py_scan["display_mapping_files"]
    input_type_files = py_scan["input_type_files"]
    if mapping_files:
        lines.append("- Files mentioning `NODE_CLASS_MAPPINGS`:")
        lines.extend(f"  - `{item}`" for item in mapping_files)
    else:
        lines.append("- Files mentioning `NODE_CLASS_MAPPINGS`: none found")
    if display_mapping_files:
        lines.append("- Files mentioning `NODE_DISPLAY_NAME_MAPPINGS`:")
        lines.extend(f"  - `{item}`" for item in display_mapping_files)
    else:
        lines.append("- Files mentioning `NODE_DISPLAY_NAME_MAPPINGS`: none found")
    if input_type_files:
        lines.append("- Files mentioning `INPUT_TYPES`:")
        lines.extend(f"  - `{item}`" for item in input_type_files)
    else:
        lines.append("- Files mentioning `INPUT_TYPES`: none found")

    heavy_imports = py_scan["heavy_imports"]
    lines.extend(["", "## Top-Level Heavy Imports Observed", ""])
    if heavy_imports:
        for rel, imports in sorted(heavy_imports.items()):
            lines.append(f"- `{rel}`: {', '.join(f'`{name}`' for name in imports)}")
        lines.append("")
        lines.append("Reviewers should check whether these imports are required at ComfyUI startup or can be lazy-loaded inside node execution.")
    else:
        lines.append("- None found in top-level Python imports.")

    tensor_signals = py_scan["tensor_signals"]
    lines.extend(["", "## Tensor / Layout Signals Observed", ""])
    if tensor_signals:
        for rel, signals in sorted(tensor_signals.items()):
            lines.append(f"- `{rel}`: {', '.join(f'`{name}`' for name in signals)}")
        lines.append("")
        lines.append("Reviewers should inspect these files before making tensor-layout claims.")
    else:
        lines.append("- None found.")

    vram_signals = py_scan["vram_signals"]
    lines.extend(["", "## VRAM / Model-Management Signals Observed", ""])
    if vram_signals:
        for rel, signals in sorted(vram_signals.items()):
            lines.append(f"- `{rel}`: {', '.join(f'`{name}`' for name in signals)}")
        lines.append("")
        lines.append("Reviewers should inspect these files before making residency, offload, or cache-lifetime claims.")
    else:
        lines.append("- None found.")

    parse_errors = py_scan["parse_errors"]
    if parse_errors:
        lines.extend(["", "## Python Parse Warnings", ""])
        lines.extend(f"- {item}" for item in parse_errors)

    if args.note:
        lines.extend(["", "## User Notes", ""])
        lines.extend(f"- {item}" for item in args.note)

    lines.extend(
        [
            "",
            "## Local Reviewer Instructions",
            "",
            "- Prefer concrete file-path citations over general ComfyUI advice.",
            "- For VRAM/model-management claims, compare the recommendation to the GPU and budget above; if the budget is unknown, mark the claim `verify:`.",
            "- For tensor-layout claims, verify the actual tensors used by this repo before asserting channel/order mistakes.",
            "- For workflow claims, inspect the canonical workflow JSON listed above, not an ad-hoc or generated graph.",
            "- For node-contract claims, verify `NODE_CLASS_MAPPINGS`, `INPUT_TYPES`, `RETURN_TYPES`, `FUNCTION`, `CATEGORY`, and any workflow wiring together.",
            "",
            "## Edit Me",
            "",
            "Add any project-specific invariants here before important reviews, for example canonical model names, maximum resolution/batch size, output directories, or workflow files that must be edited with code changes.",
            "",
        ]
    )
    return "\n".join(lines)


def ensure_git_exclude(repo: Path) -> bool:
    exclude = repo / ".git" / "info" / "exclude"
    if not exclude.is_file():
        return False
    existing = exclude.read_text(encoding="utf-8", errors="replace")
    rule = ".kibitz/*.local.md"
    if any(line.strip() == rule for line in existing.splitlines()):
        return True
    suffix = "" if existing.endswith("\n") or not existing else "\n"
    exclude.write_text(existing + suffix + rule + "\n", encoding="utf-8")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate .kibitz/comfyui.local.md for Kibitz's ComfyUI reviewer profile."
    )
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="target repo (default: current directory)")
    parser.add_argument("--workflow", action="append", default=[], help="canonical ComfyUI workflow JSON; repeatable")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="output profile path, repo-relative by default")
    parser.add_argument("--comfyui-root", help="ComfyUI install/root path to record")
    parser.add_argument("--output-base", help="ComfyUI output base path to record")
    parser.add_argument("--vram-budget-gb", help="review budget in GiB, if different from total GPU VRAM")
    parser.add_argument("--note", action="append", default=[], help="extra local invariant note; repeatable")
    parser.add_argument("--write", action="store_true", help="write the profile file instead of printing to stdout")
    parser.add_argument("--force", action="store_true", help="overwrite an existing output file")
    parser.add_argument("--no-git-exclude", action="store_true",
                        help="do not add .kibitz/*.local.md to the target repo's local git exclude")
    args = parser.parse_args()

    repo = args.repo.resolve()
    if not repo.is_dir():
        parser.error(f"--repo is not a directory: {repo}")

    profile = build_profile(args, repo)
    output = resolve_repo_path(args.output, repo)
    if not args.write:
        print(profile)
        return 0

    if output.exists() and not args.force:
        print(f"ERROR: {output} already exists. Re-run with --force to overwrite it.", file=sys.stderr)
        return 2
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(profile, encoding="utf-8")
    print(f"Wrote {output}")
    if not args.no_git_exclude and ensure_git_exclude(repo):
        print("Ensured .kibitz/*.local.md is ignored via .git/info/exclude")
    print("Kibitz will auto-append this profile for runs in this repo.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
