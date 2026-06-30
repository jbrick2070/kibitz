#!/usr/bin/env python3
"""Generate a repo-local ComfyUI profile overlay for kibitz.

The generated file is intentionally local and machine-specific:
  .kibitz/comfyui.local.md

Kibitz auto-appends that file, together with the shipped generic ComfyUI
profile, when it exists in the target repo.

CLAUDE.md is never edited by default. Use --emit-claude-snippet to print a
pasteable pointer, or --append-claude-md for explicit opt-in pointer-only writes.
Python standard library only.
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
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Optional, Union


DEFAULT_OUTPUT = Path(".kibitz") / "comfyui.local.md"
DEFAULT_CLAUDE_MD = Path("CLAUDE.md")
DEFAULT_COMFY_PORTS = (8000, 8188)
CLAUDE_SNIPPET_BEGIN = "<!-- KIBITZ LOCAL COMFYUI PROFILE BEGIN -->"
CLAUDE_SNIPPET_END = "<!-- KIBITZ LOCAL COMFYUI PROFILE END -->"
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
MODEL_FILE_EXTS = {
    ".bin",
    ".ckpt",
    ".engine",
    ".gguf",
    ".onnx",
    ".pt",
    ".pth",
    ".safetensors",
}
MODEL_PATH_KEYS = {
    "checkpoints",
    "clip",
    "clip_vision",
    "configs",
    "controlnet",
    "diffusers",
    "diffusion_models",
    "embeddings",
    "gligen",
    "hypernetworks",
    "loras",
    "style_models",
    "text_encoders",
    "unet",
    "upscale_models",
    "vae",
    "vae_approx",
}
CLOUD_ENV_HINTS = {
    "RUNPOD_POD_ID": "RunPod",
    "RUNPOD_PUBLIC_IP": "RunPod",
    "RUNPOD_DC_ID": "RunPod",
    "COLAB_GPU": "Google Colab",
    "KAGGLE_KERNEL_RUN_TYPE": "Kaggle",
    "MODAL_TASK_ID": "Modal",
    "VAST_CONTAINERLABEL": "Vast.ai",
    "PAPERSPACE_NOTEBOOK_ID": "Paperspace",
    "AWS_EXECUTION_ENV": "AWS",
    "AWS_REGION": "AWS",
    "GOOGLE_CLOUD_PROJECT": "Google Cloud",
    "GCP_PROJECT": "Google Cloud",
    "AZUREML_RUN_ID": "Azure ML",
    "CODESPACES": "GitHub Codespaces",
    "KUBERNETES_SERVICE_HOST": "Kubernetes",
}
COMFY_ROOT_ENV_KEYS = ("COMFYUI_ROOT", "COMFYUI_PATH", "COMFYUI_HOME", "COMFY_HOME")


def repo_relative(path: Path, repo: Path) -> str:
    try:
        return str(path.resolve().relative_to(repo.resolve()))
    except ValueError:
        return str(path)


def resolve_repo_path(raw: Union[str, Path], repo: Path) -> Path:
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


def path_from_env(key: str) -> Optional[Path]:
    raw = os.environ.get(key)
    if not raw:
        return None
    path = Path(os.path.expandvars(raw)).expanduser()
    return path if path.exists() else None


def looks_like_comfyui_root(path: Path) -> bool:
    return (
        path.is_dir()
        and (path / "models").is_dir()
        and ((path / "custom_nodes").is_dir() or (path / "user").is_dir())
    )


def find_comfyui_roots(repo: Path, supplied_root: Optional[str]) -> list[Path]:
    candidates: list[Path] = []
    if supplied_root:
        candidates.append(resolve_repo_path(supplied_root, repo))
    for key in COMFY_ROOT_ENV_KEYS:
        env_path = path_from_env(key)
        if env_path:
            candidates.append(env_path)
    for parent in [repo] + list(repo.parents):
        candidates.append(parent)
    home = Path.home()
    candidates.extend(
        [
            home / "Documents" / "ComfyUI",
            home / "ComfyUI",
            Path("/workspace/ComfyUI"),
            Path("/content/ComfyUI"),
            Path("/ComfyUI"),
        ]
    )

    roots: list[Path] = []
    seen = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        if looks_like_comfyui_root(resolved):
            roots.append(resolved)
    return roots


def detect_runtime_hints() -> list[str]:
    hints = []
    for key, label in CLOUD_ENV_HINTS.items():
        if os.environ.get(key):
            hints.append(f"{label} (`{key}` is set)")
    path_hints = {
        "RunPod workspace": Path("/workspace"),
        "Google Colab content": Path("/content"),
        "Modal volume": Path("/modal"),
    }
    for label, path in path_hints.items():
        if path.exists():
            hints.append(f"{label} path exists: `{path}`")
    return sorted(set(hints))


def detect_comfy_desktop() -> list[Path]:
    candidates = []
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        candidates.append(
            Path(local_appdata) / "Programs" / "ComfyUI" / "Comfy Desktop" / "Comfy Desktop.exe"
        )
    return [path for path in candidates if path.is_file()]


def query_comfy_server(port: int) -> Optional[dict[str, object]]:
    url = f"http://127.0.0.1:{port}/system_stats"
    try:
        with urllib.request.urlopen(url, timeout=0.5) as response:
            raw = response.read(256_000).decode("utf-8", errors="replace")
    except (OSError, urllib.error.URLError, TimeoutError):
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = {}
    result: dict[str, object] = {"port": port, "url": url}
    devices = data.get("devices") if isinstance(data, dict) else None
    if isinstance(devices, list):
        result["devices"] = [
            {
                "name": str(item.get("name", "unknown")),
                "type": str(item.get("type", "unknown")),
                "vram_total": item.get("vram_total"),
                "vram_free": item.get("vram_free"),
            }
            for item in devices
            if isinstance(item, dict)
        ][:4]
    return result


def detect_active_servers(ports: list[int]) -> list[dict[str, object]]:
    return [server for port in ports if (server := query_comfy_server(port))]


def summarize_user_profiles(comfy_root: Path) -> dict[str, object]:
    user_dir = comfy_root / "user"
    profiles = []
    if not user_dir.is_dir():
        return {"user_dir": user_dir, "profiles": profiles}
    for child in sorted(path for path in user_dir.iterdir() if path.is_dir()):
        settings = child / "comfy.settings.json"
        workflows_dir = child / "workflows"
        workflows = sorted(workflows_dir.glob("*.json")) if workflows_dir.is_dir() else []
        selected_settings: dict[str, object] = {}
        if settings.is_file():
            try:
                data = json.loads(settings.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                data = {}
            if isinstance(data, dict):
                for key in (
                    "Comfy.InstalledVersion",
                    "Comfy.Release.Version",
                    "Comfy.DevMode",
                    "Comfy.Workflow.ShowMissingModelsWarning",
                    "Comfy.Workflow.ShowMissingNodesWarning",
                    "Comfy.Validation.Workflows",
                ):
                    if key in data:
                        selected_settings[key] = data[key]
                launch_args = data.get("Comfy.Server.LaunchArgs")
                if isinstance(launch_args, dict):
                    selected_settings["Comfy.Server.LaunchArgs"] = launch_args
                server_values = data.get("Comfy.Server.ServerConfigValues")
                if isinstance(server_values, dict):
                    selected_settings["Comfy.Server.ServerConfigValues"] = server_values
        profiles.append(
            {
                "name": child.name,
                "settings": settings if settings.is_file() else None,
                "workflow_count": len(workflows),
                "workflow_samples": [path.name for path in workflows[:12]],
                "selected_settings": selected_settings,
            }
        )
    return {"user_dir": user_dir, "profiles": profiles}


def summarize_custom_nodes(comfy_root: Path) -> dict[str, object]:
    custom_nodes = comfy_root / "custom_nodes"
    if not custom_nodes.is_dir():
        return {"path": custom_nodes, "nodes": []}
    nodes = [
        child.name
        for child in sorted(custom_nodes.iterdir(), key=lambda p: p.name.lower())
        if child.is_dir() and child.name not in {"__pycache__"}
    ]
    return {"path": custom_nodes, "nodes": nodes}


def find_extra_model_path_files(comfy_roots: list[Path], repo: Path) -> list[Path]:
    candidates: list[Path] = []
    for root in comfy_roots:
        candidates.extend(sorted(root.glob("extra_model_paths*.yaml")))
        candidates.extend(sorted(root.glob("extra_model_paths*.yml")))
    candidates.extend(sorted(repo.rglob("*model_paths*.yaml")))
    candidates.extend(sorted(repo.rglob("*model_paths*.yml")))

    result = []
    seen = set()
    for path in candidates:
        if any(part in {"models", ".git", "__pycache__"} for part in path.parts):
            continue
        resolved = path.resolve()
        if resolved not in seen and path.is_file():
            seen.add(resolved)
            result.append(resolved)
    return result[:20]


def split_path_value(raw: str) -> list[str]:
    value = raw.strip().strip("\"'")
    if not value or value in {"|", ">"}:
        return []
    pieces = []
    for part in value.replace(";", "\n").splitlines():
        for subpart in part.split(","):
            cleaned = subpart.strip().strip("\"'")
            if cleaned:
                pieces.append(cleaned)
    return pieces


def resolve_model_path(value: str, base_path: Optional[Path], config_path: Path) -> Path:
    expanded = Path(os.path.expandvars(value)).expanduser()
    if expanded.is_absolute():
        return expanded
    if base_path is not None:
        return (base_path / expanded).resolve()
    return (config_path.parent / expanded).resolve()


def parse_extra_model_paths(path: Path) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    section: Optional[str] = None
    base_by_section: dict[str, Path] = {}
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line_without_comment = raw_line.split("#", 1)[0].rstrip()
        if not line_without_comment.strip():
            continue
        indent = len(line_without_comment) - len(line_without_comment.lstrip())
        stripped = line_without_comment.strip()
        if indent == 0 and stripped.endswith(":"):
            section = stripped[:-1].strip()
            continue
        if section is None or ":" not in stripped:
            continue
        key, raw_value = stripped.split(":", 1)
        key = key.strip()
        values = split_path_value(raw_value)
        if key == "base_path" and values:
            base_by_section[section] = resolve_model_path(values[0], None, path)
            continue
        if key not in MODEL_PATH_KEYS and key != "custom_nodes":
            continue
        base_path = base_by_section.get(section)
        for value in values:
            entries.append(
                {
                    "source": path,
                    "section": section,
                    "key": key,
                    "path": resolve_model_path(value, base_path, path),
                }
            )
    return entries


def default_model_dirs(comfy_roots: list[Path]) -> list[Path]:
    dirs = []
    for root in comfy_roots:
        models = root / "models"
        if models.is_dir():
            dirs.append(models)
    return dirs


def summarize_directory(path: Path) -> dict[str, object]:
    exists = path.exists()
    summary: dict[str, object] = {"path": path, "exists": exists}
    if not exists or not path.is_dir():
        return summary
    try:
        children = list(path.iterdir())
    except OSError:
        children = []
    summary["dir_count"] = sum(1 for child in children if child.is_dir())
    summary["file_count"] = sum(1 for child in children if child.is_file())
    return summary


def scan_model_inventory(model_roots: list[Path], max_files: int) -> dict[str, object]:
    categories: dict[str, dict[str, object]] = {}
    largest: list[tuple[int, Path]] = []
    hf_models: list[str] = []
    scanned = 0
    truncated = False
    seen_files = set()

    for root in model_roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            try:
                resolved = path.resolve()
            except OSError:
                continue
            if resolved in seen_files:
                continue
            seen_files.add(resolved)
            if path.parent.name == "refs" or path.suffix.lower() not in MODEL_FILE_EXTS:
                continue
            scanned += 1
            if scanned > max_files:
                truncated = True
                break
            try:
                size = path.stat().st_size
            except OSError:
                size = 0
            try:
                rel = path.relative_to(root)
                category = rel.parts[0] if len(rel.parts) > 1 else "(root)"
            except ValueError:
                category = "(external)"
            info = categories.setdefault(
                category,
                {"count": 0, "bytes": 0, "samples": [], "exts": Counter()},
            )
            info["count"] = int(info["count"]) + 1
            info["bytes"] = int(info["bytes"]) + size
            info["exts"][path.suffix.lower()] += 1
            samples = info["samples"]
            if isinstance(samples, list) and len(samples) < 8:
                samples.append(path.name)
            largest.append((size, path))

            for part in path.parts:
                if part.startswith("models--"):
                    model_id = part.removeprefix("models--").replace("--", "/")
                    if model_id not in hf_models:
                        hf_models.append(model_id)
                    break
        if truncated:
            break

    largest = sorted(largest, reverse=True, key=lambda item: item[0])[:15]
    return {
        "categories": categories,
        "largest": largest,
        "hf_models": hf_models[:40],
        "scanned": min(scanned, max_files),
        "truncated": truncated,
    }


def detect_comfy_setup(args: argparse.Namespace, repo: Path) -> dict[str, object]:
    roots = find_comfyui_roots(repo, args.comfyui_root)
    root = roots[0] if roots else None
    ports = []
    for item in str(args.ports).split(","):
        item = item.strip()
        if not item:
            continue
        try:
            ports.append(int(item))
        except ValueError:
            continue
    extra_model_path_files = find_extra_model_path_files(roots, repo)
    extra_model_entries = []
    for path in extra_model_path_files:
        extra_model_entries.extend(parse_extra_model_paths(path))

    model_dirs = default_model_dirs(roots)
    for raw in args.models_dir:
        model_dirs.append(resolve_repo_path(raw, repo))
    for entry in extra_model_entries:
        path = entry["path"]
        if isinstance(path, Path) and entry.get("key") != "custom_nodes":
            model_dirs.append(path)

    unique_model_dirs = []
    seen_dirs = set()
    for path in model_dirs:
        resolved = path.resolve()
        if resolved not in seen_dirs:
            seen_dirs.add(resolved)
            unique_model_dirs.append(resolved)

    return {
        "roots": roots,
        "primary_root": root,
        "runtime_hints": detect_runtime_hints(),
        "desktop_exes": detect_comfy_desktop(),
        "active_servers": detect_active_servers(ports),
        "user_profiles": summarize_user_profiles(root) if root else None,
        "custom_nodes": summarize_custom_nodes(root) if root else None,
        "input_dir": resolve_repo_path(args.input_base, repo) if args.input_base else (root / "input" if root else None),
        "output_dir": resolve_repo_path(args.output_base, repo) if args.output_base else (root / "output" if root else None),
        "temp_dir": resolve_repo_path(args.temp_base, repo) if args.temp_base else (root / "temp" if root else None),
        "extra_model_path_files": extra_model_path_files,
        "extra_model_entries": extra_model_entries[:80],
        "model_dirs": unique_model_dirs,
        "model_inventory": (
            scan_model_inventory(unique_model_dirs, args.max_model_files)
            if not args.no_model_scan
            else None
        ),
    }


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


def gib(size_bytes: int) -> str:
    return f"{size_bytes / (1024 ** 3):.2f} GiB"


def format_existing_path(label: str, path: Optional[Path]) -> str:
    if path is None:
        return f"- {label}: `unknown`"
    status = "exists" if path.exists() else "missing"
    return f"- {label}: `{path}` ({status})"


def format_comfy_setup(setup: dict[str, object]) -> list[str]:
    lines: list[str] = ["", "## Runtime / ComfyUI Setup", ""]
    runtime_hints = setup["runtime_hints"]
    if runtime_hints:
        lines.append("- Runtime/cloud hints:")
        lines.extend(f"  - {hint}" for hint in runtime_hints)
    else:
        lines.append("- Runtime/cloud hints: none detected; this looks like a local desktop run")

    roots = setup["roots"]
    if roots:
        lines.append("- Detected ComfyUI roots:")
        lines.extend(f"  - `{path}`" for path in roots)
    else:
        lines.append("- Detected ComfyUI roots: none")

    desktop_exes = setup["desktop_exes"]
    if desktop_exes:
        lines.append("- Comfy Desktop executables:")
        lines.extend(f"  - `{path}`" for path in desktop_exes)

    active_servers = setup["active_servers"]
    if active_servers:
        lines.append("- Active local ComfyUI servers:")
        for server in active_servers:
            lines.append(f"  - port `{server['port']}`: `{server['url']}`")
            for device in server.get("devices", []):
                if not isinstance(device, dict):
                    continue
                lines.append(
                    "    - "
                    f"{device.get('type', 'device')} `{device.get('name', 'unknown')}`; "
                    f"vram_free={device.get('vram_free')}; vram_total={device.get('vram_total')}"
                )
    else:
        lines.append("- Active local ComfyUI servers: none detected on the probed ports")

    lines.extend(
        [
            format_existing_path("Input directory", setup["input_dir"]),
            format_existing_path("Output directory", setup["output_dir"]),
            format_existing_path("Temp directory", setup["temp_dir"]),
        ]
    )
    return lines


def format_user_profiles(setup: dict[str, object]) -> list[str]:
    lines = ["", "## ComfyUI User Preferences", ""]
    user_profiles = setup["user_profiles"]
    if not isinstance(user_profiles, dict):
        lines.append("- User profile directory: `unknown`")
        return lines
    lines.append(format_existing_path("User profile directory", user_profiles["user_dir"]))
    profiles = user_profiles.get("profiles", [])
    if not profiles:
        lines.append("- Profiles: none found")
        return lines
    for profile in profiles:
        if not isinstance(profile, dict):
            continue
        lines.append(f"- Profile `{profile['name']}`:")
        settings = profile.get("settings")
        if settings:
            lines.append(f"  - settings: `{settings}`")
        lines.append(f"  - saved workflow count: `{profile.get('workflow_count', 0)}`")
        samples = profile.get("workflow_samples", [])
        if samples:
            lines.append(f"  - workflow samples: {', '.join(f'`{name}`' for name in samples)}")
        selected_settings = profile.get("selected_settings", {})
        if isinstance(selected_settings, dict) and selected_settings:
            lines.append("  - selected settings:")
            for key, value in selected_settings.items():
                lines.append(f"    - `{key}`: `{value}`")
    return lines


def format_custom_nodes(setup: dict[str, object]) -> list[str]:
    lines = ["", "## Installed Custom Nodes", ""]
    custom_nodes = setup["custom_nodes"]
    if not isinstance(custom_nodes, dict):
        lines.append("- Custom nodes directory: `unknown`")
        return lines
    lines.append(format_existing_path("Custom nodes directory", custom_nodes["path"]))
    nodes = custom_nodes.get("nodes", [])
    if not nodes:
        lines.append("- Custom node directories: none found")
        return lines
    lines.append(f"- Custom node directory count: `{len(nodes)}`")
    shown = nodes[:80]
    lines.extend(f"  - `{name}`" for name in shown)
    if len(nodes) > len(shown):
        lines.append(f"  - ... {len(nodes) - len(shown)} more")
    return lines


def format_model_setup(setup: dict[str, object]) -> list[str]:
    lines = ["", "## Model Paths / Inventory", ""]
    model_dirs = setup["model_dirs"]
    if model_dirs:
        lines.append("- Model search roots:")
        for path in model_dirs:
            summary = summarize_directory(path)
            if summary.get("exists"):
                lines.append(
                    f"  - `{path}` (dirs={summary.get('dir_count', 0)}, files={summary.get('file_count', 0)})"
                )
            else:
                lines.append(f"  - `{path}` (missing)")
    else:
        lines.append("- Model search roots: none detected")

    extra_files = setup["extra_model_path_files"]
    if extra_files:
        lines.append("- Extra model path config files:")
        lines.extend(f"  - `{path}`" for path in extra_files)
    extra_entries = setup["extra_model_entries"]
    if extra_entries:
        lines.append("- Extra model path entries:")
        for entry in extra_entries:
            lines.append(
                "  - "
                f"`{entry['section']}.{entry['key']}` -> `{entry['path']}` "
                f"(from `{entry['source']}`)"
            )

    inventory = setup["model_inventory"]
    if inventory is None:
        lines.append("- Model inventory scan: disabled")
        return lines

    lines.append(
        f"- Model files scanned: `{inventory['scanned']}`"
        + (" (truncated at scan limit)" if inventory["truncated"] else "")
    )
    categories = inventory["categories"]
    if categories:
        lines.append("- Model files by category:")
        for category, info in sorted(categories.items()):
            exts = info.get("exts", Counter())
            if isinstance(exts, Counter):
                ext_text = ", ".join(f"{ext} x{count}" for ext, count in sorted(exts.items()))
            else:
                ext_text = "unknown"
            lines.append(
                f"  - `{category}`: {info['count']} files, {gib(int(info['bytes']))}; {ext_text}"
            )
            samples = info.get("samples", [])
            if samples:
                lines.append(f"    - samples: {', '.join(f'`{name}`' for name in samples)}")
    largest = inventory["largest"]
    if largest:
        lines.append("- Largest model-like files:")
        for size, path in largest:
            lines.append(f"  - `{path}` ({gib(size)})")
    hf_models = inventory["hf_models"]
    if hf_models:
        lines.append("- Hugging Face cache model ids detected:")
        lines.extend(f"  - `{model_id}`" for model_id in hf_models)
    return lines


def build_profile(args: argparse.Namespace, repo: Path) -> str:
    workflows = [summarize_workflow(path, repo) for path in find_workflows(repo, args.workflow)]
    py_scan = scan_python(repo)
    gpus = query_gpus()
    setup = detect_comfy_setup(args, repo)
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

    lines.extend(format_comfy_setup(setup))
    lines.extend(format_user_profiles(setup))
    lines.extend(format_model_setup(setup))
    lines.extend(format_custom_nodes(setup))

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


def build_claude_snippet(profile_path: Path, repo: Path) -> str:
    profile_ref = repo_relative(profile_path, repo)
    return "\n".join(
        [
            CLAUDE_SNIPPET_BEGIN,
            "## Kibitz Local ComfyUI Profile",
            "",
            "For machine-local ComfyUI review context, read:",
            "",
            f"`{profile_ref}`",
            "",
            "This is a pointer only. The profile is local, should stay uncommitted,",
            "and does not replace shared repo policy or operator instructions.",
            CLAUDE_SNIPPET_END,
            "",
        ]
    )


def append_claude_md_pointer(claude_md: Path, snippet: str) -> Optional[Path]:
    claude_md.parent.mkdir(parents=True, exist_ok=True)
    backup_path = None
    if claude_md.exists():
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = claude_md.with_name(f"{claude_md.name}.bak-kibitz-{stamp}")
        backup_path.write_text(claude_md.read_text(encoding="utf-8", errors="replace"),
                               encoding="utf-8")
        text = claude_md.read_text(encoding="utf-8", errors="replace")
    else:
        text = ""

    start = text.find(CLAUDE_SNIPPET_BEGIN)
    end = text.find(CLAUDE_SNIPPET_END)
    if start != -1 and end != -1 and end > start:
        end += len(CLAUDE_SNIPPET_END)
        new_text = text[:start].rstrip() + "\n\n" + snippet.rstrip() + "\n" + text[end:].lstrip()
    else:
        prefix = text.rstrip()
        new_text = (prefix + "\n\n" if prefix else "") + snippet
    claude_md.write_text(new_text, encoding="utf-8")
    return backup_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate .kibitz/comfyui.local.md for Kibitz's ComfyUI reviewer profile."
    )
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="target repo (default: current directory)")
    parser.add_argument("--workflow", action="append", default=[], help="canonical ComfyUI workflow JSON; repeatable")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="output profile path, repo-relative by default")
    parser.add_argument("--comfyui-root", help="ComfyUI install/root path; auto-detected when omitted")
    parser.add_argument("--models-dir", action="append", default=[], help="extra model root to inventory; repeatable")
    parser.add_argument("--input-base", help="ComfyUI input path override")
    parser.add_argument("--output-base", help="ComfyUI output path override")
    parser.add_argument("--temp-base", help="ComfyUI temp path override")
    parser.add_argument(
        "--ports",
        default=",".join(str(port) for port in DEFAULT_COMFY_PORTS),
        help="comma-separated local ComfyUI ports to probe",
    )
    parser.add_argument("--vram-budget-gb", help="review budget in GiB, if different from total GPU VRAM")
    parser.add_argument("--max-model-files", type=int, default=20_000, help="model inventory scan cap")
    parser.add_argument("--no-model-scan", action="store_true", help="record model paths but skip model file inventory")
    parser.add_argument("--note", action="append", default=[], help="extra local invariant note; repeatable")
    parser.add_argument("--write", action="store_true", help="write the profile file instead of printing to stdout")
    parser.add_argument("--force", action="store_true", help="overwrite an existing output file")
    parser.add_argument("--no-git-exclude", action="store_true",
                        help="do not add .kibitz/*.local.md to the target repo's local git exclude")
    parser.add_argument("--emit-claude-snippet", action="store_true",
                        help="print a safe CLAUDE.md pointer snippet; does not modify CLAUDE.md")
    parser.add_argument("--append-claude-md", action="store_true",
                        help="explicit opt-in: append/update a pointer block in CLAUDE.md")
    parser.add_argument("--claude-md", type=Path, default=DEFAULT_CLAUDE_MD,
                        help="CLAUDE.md path for --append-claude-md, repo-relative by default")
    args = parser.parse_args()

    repo = args.repo.resolve()
    if not repo.is_dir():
        parser.error(f"--repo is not a directory: {repo}")

    output = resolve_repo_path(args.output, repo)
    snippet = build_claude_snippet(output, repo)
    if args.emit_claude_snippet and not args.write and not args.append_claude_md:
        print(snippet)
        return 0

    if not args.write:
        if args.append_claude_md and not output.exists():
            print(
                f"ERROR: {output} does not exist. Run with --write first, or include --write.",
                file=sys.stderr,
            )
            return 2
        if not args.append_claude_md:
            print(build_profile(args, repo))
        if args.emit_claude_snippet:
            print("\n" + snippet)
        if args.append_claude_md:
            claude_md = resolve_repo_path(args.claude_md, repo)
            backup_path = append_claude_md_pointer(claude_md, snippet)
            print(f"Updated {claude_md} with Kibitz pointer block.")
            if backup_path:
                print(f"Backup: {backup_path}")
        return 0

    profile = build_profile(args, repo)
    if output.exists() and not args.force:
        print(f"ERROR: {output} already exists. Re-run with --force to overwrite it.", file=sys.stderr)
        return 2
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(profile, encoding="utf-8")
    print(f"Wrote {output}")
    if not args.no_git_exclude and ensure_git_exclude(repo):
        print("Ensured .kibitz/*.local.md is ignored via .git/info/exclude")
    print("Kibitz will auto-append this profile for runs in this repo.")
    if args.emit_claude_snippet:
        print("\n" + snippet)
    if args.append_claude_md:
        claude_md = resolve_repo_path(args.claude_md, repo)
        backup_path = append_claude_md_pointer(claude_md, snippet)
        print(f"Updated {claude_md} with Kibitz pointer block.")
        if backup_path:
            print(f"Backup: {backup_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
