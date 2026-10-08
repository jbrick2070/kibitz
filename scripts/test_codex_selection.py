"""Offline regressions for model selection and multiple installed Codex CLIs."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import codex_cli
import doctor
import kibitz


class CodexSelectionTests(unittest.TestCase):
    def select(self, models, requested=None):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = subprocess.CompletedProcess([], 0, json.dumps({"models": models}), "")
            with patch.object(kibitz, "CODEX_MODEL_REQUEST", requested), \
                    patch.object(kibitz.subprocess, "run", return_value=result):
                selected = kibitz.pick_codex_model("codex", root, root)
            receipt = (root / "codex_model_resolution.txt").read_text(encoding="utf-8")
            self.assertIn(f"selected={selected or '(codex default)'}", receipt)
            return selected

    def test_current_catalog_prefers_sol_61(self):
        self.assertEqual(self.select([
            {"slug": "gpt-5.5", "visibility": "hide"},
            {"slug": "gpt-6-astra"}, {"slug": "gpt-6-sol"},
            {"slug": "gpt-6.1-sol"},
        ]), "gpt-6.1-sol")

    def test_older_cli_catalog_uses_available_full_size_model(self):
        self.assertEqual(self.select([
            {"slug": "gpt-5.6-luna"}, {"slug": "gpt-5.6-terra"},
            {"slug": "gpt-5.6-sol"},
        ]), "gpt-5.6-sol")

    def test_hidden_preference_does_not_beat_visible_model(self):
        self.assertEqual(self.select([
            {"slug": "gpt-6.1-sol", "visibility": "hide"},
            {"slug": "gpt-6-sol"},
        ]), "gpt-6-sol")

    def test_explicit_small_or_hidden_pin_is_preserved(self):
        for slug in ("gpt-6-luna", "gpt-5.3-codex-spark"):
            with self.subTest(slug=slug):
                self.assertEqual(self.select([
                    {"slug": slug, "visibility": "hide"}, {"slug": "gpt-6.1-sol"},
                ], slug), slug)

    def test_missing_pin_falls_back_to_available_model(self):
        self.assertEqual(self.select([{"slug": "gpt-6.1-sol"}], "gpt-99-missing"),
                         "gpt-6.1-sol")

    def test_future_fallback_sorts_numerically_and_excludes_small_models(self):
        self.assertEqual(self.select([
            {"slug": "gpt-9-sol"}, {"slug": "gpt-10-sol"},
            {"slug": "gpt-11-luna"}, {"slug": "gpt-12-nano"},
        ]), "gpt-10-sol")

    def test_new_desktop_cli_beats_old_path_cli(self):
        self.check_versions("0.147.0", "0.162.0-alpha.2", expected="desktop")

    def test_stable_beats_same_version_prerelease(self):
        self.check_versions("0.162.0", "0.162.0-alpha.2", expected="path")

    def test_newer_path_cli_still_wins(self):
        self.check_versions("0.170.0", "0.162.0", expected="path")

    def test_prerelease_numbers_are_compared_numerically(self):
        self.check_versions("0.162.0-alpha.2", "0.162.0-alpha.10", expected="desktop")

    def test_native_binary_beats_equal_version_cmd_shim(self):
        self.check_versions("0.162.0-alpha.2", "0.162.0-alpha.2",
                            expected="desktop", path_name="codex.cmd")

    def check_versions(self, path_version, desktop_version, expected, path_name="codex.exe"):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path_exe = root / "old" / path_name
            desktop_exe = root / "desktop" / "hash" / "codex.exe"
            for file in (path_exe, desktop_exe):
                file.parent.mkdir(parents=True)
                file.touch()
            versions = {str(path_exe): path_version, str(desktop_exe): desktop_version}

            def version_result(args, **kwargs):
                self.assertEqual(args[1:], ["--version"])
                return subprocess.CompletedProcess(args, 0, f"codex-cli {versions[args[0]]}\n", "")

            with patch.dict(os.environ, {"KIBITZ_CODEX_BIN": "", "LOCALAPPDATA": ""}), \
                    patch.object(codex_cli.shutil, "which", return_value=str(path_exe)), \
                    patch.object(codex_cli.subprocess, "run", side_effect=version_result):
                selected = codex_cli.find_codex(str(root / "desktop"))
                self.assertEqual(selected, str(desktop_exe if expected == "desktop" else path_exe))
                self.assertEqual(doctor.find_agent("codex", str(root / "desktop")), selected)
                self.assertEqual(kibitz._which("codex", str(root / "desktop")), selected)

    def test_explicit_binary_does_not_probe_real_clis(self):
        with tempfile.TemporaryDirectory() as temporary:
            executable = Path(temporary) / "codex.cmd"
            executable.touch()
            with patch.dict(os.environ, {"KIBITZ_CODEX_BIN": str(executable)}), \
                    patch.object(codex_cli.subprocess, "run") as run:
                self.assertEqual(codex_cli.find_codex(), str(executable))
                run.assert_not_called()

    def test_invalid_override_does_not_silently_use_another_cli(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch.dict(os.environ, {"KIBITZ_CODEX_BIN": str(Path(temporary) / "missing")}):
                with self.assertRaisesRegex(ValueError, "KIBITZ_CODEX_BIN"):
                    codex_cli.find_codex()


if __name__ == "__main__":
    unittest.main()
