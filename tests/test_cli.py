from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from rbxbundle import _cli


class TestCliConfigDefaults(unittest.TestCase):
    def setUp(self) -> None:
        self.old_input = _cli.DEFAULT_INPUT_DIR
        self.old_output = _cli.DEFAULT_OUTPUT_DIR

    def tearDown(self) -> None:
        _cli.DEFAULT_INPUT_DIR = self.old_input
        _cli.DEFAULT_OUTPUT_DIR = self.old_output

    def test_apply_config_defaults_updates_argparse_defaults(self):
        cfg = {
            "input_dir": "custom-input",
            "output_dir": "custom-output",
        }

        _cli._apply_config_defaults(cfg)
        parser = _cli._build_argparser()
        subparsers = next(action for action in parser._actions if action.dest == "command").choices

        build_parser = subparsers["build"]
        list_parser = subparsers["list"]

        build_output = next(action for action in build_parser._actions if action.dest == "output")
        list_dir = next(action for action in list_parser._actions if action.dest == "dir")

        self.assertEqual(build_output.default, "custom-output")
        self.assertEqual(list_dir.default, "custom-input")

    def test_default_workspace_root_ends_with_rbxbundle(self):
        root = _cli._resolve_default_workspace_root()
        self.assertEqual(root.name.lower(), "rbxbundle")

    def test_resolve_cli_input_path_falls_back_to_default_input_dir(self):
        with tempfile.TemporaryDirectory() as td:
            input_dir = Path(td) / "input"
            input_dir.mkdir(parents=True, exist_ok=True)
            target = input_dir / "Sample.rbxmx"
            target.write_text("<roblox />", encoding="utf-8")

            old_input = _cli.DEFAULT_INPUT_DIR
            try:
                _cli.DEFAULT_INPUT_DIR = input_dir
                resolved = _cli._resolve_cli_input_path("Sample.rbxmx")
            finally:
                _cli.DEFAULT_INPUT_DIR = old_input

            self.assertEqual(resolved, target)

    def test_load_config_ignores_non_object_json(self):
        with tempfile.TemporaryDirectory() as td:
            config_path = Path(td) / "rbxbundle.json"
            config_path.write_text("[]", encoding="utf-8")

            old_path = _cli._CONFIG_PATH
            try:
                _cli._CONFIG_PATH = config_path
                cfg = _cli._load_config()
            finally:
                _cli._CONFIG_PATH = old_path

            self.assertEqual(cfg["input_dir"], str(_cli.DEFAULT_INPUT_DIR))
            self.assertEqual(cfg["output_dir"], str(_cli.DEFAULT_OUTPUT_DIR))
            self.assertEqual(cfg["schema_version"], _cli.CONFIG_SCHEMA_VERSION)

    def test_load_config_ignores_unsupported_schema_version(self):
        with tempfile.TemporaryDirectory() as td:
            config_path = Path(td) / "rbxbundle.json"
            config_path.write_text(json.dumps({"schema_version": 999, "input_dir": "bad"}), encoding="utf-8")

            old_path = _cli._CONFIG_PATH
            try:
                _cli._CONFIG_PATH = config_path
                cfg = _cli._load_config()
            finally:
                _cli._CONFIG_PATH = old_path

            self.assertEqual(cfg["input_dir"], str(_cli.DEFAULT_INPUT_DIR))
            self.assertEqual(cfg["output_dir"], str(_cli.DEFAULT_OUTPUT_DIR))
            self.assertEqual(cfg["schema_version"], _cli.CONFIG_SCHEMA_VERSION)

    def test_load_config_accepts_legacy_file_without_schema_version(self):
        with tempfile.TemporaryDirectory() as td:
            config_path = Path(td) / "rbxbundle.json"
            config_path.write_text(json.dumps({"input_dir": "legacy-input"}), encoding="utf-8")

            old_path = _cli._CONFIG_PATH
            try:
                _cli._CONFIG_PATH = config_path
                cfg = _cli._load_config()
            finally:
                _cli._CONFIG_PATH = old_path

            self.assertEqual(cfg["schema_version"], _cli.CONFIG_SCHEMA_VERSION)
            self.assertEqual(cfg["input_dir"], "legacy-input")

    def test_save_config_persists_schema_version(self):
        with tempfile.TemporaryDirectory() as td:
            config_path = Path(td) / "rbxbundle.json"

            old_path = _cli._CONFIG_PATH
            try:
                _cli._CONFIG_PATH = config_path
                _cli._save_config({"input_dir": "custom-input", "output_dir": "custom-output"})
            finally:
                _cli._CONFIG_PATH = old_path

            saved = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["schema_version"], _cli.CONFIG_SCHEMA_VERSION)
            self.assertEqual(saved["input_dir"], "custom-input")
            self.assertEqual(saved["output_dir"], "custom-output")

    def test_bundle_rules_for_path_merges_user_and_project_overrides(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            project_dir = base / "game"
            project_dir.mkdir(parents=True, exist_ok=True)
            in_path = project_dir / "Sample.rbxmx"
            in_path.write_text("<roblox />", encoding="utf-8")

            user_config = base / "user.json"
            user_config.write_text(
                json.dumps(
                    {
                        "schema_version": _cli.CONFIG_SCHEMA_VERSION,
                        "roblox_rules": {
                            "server_only_prefixes": ["ServerRuntime/"],
                        }
                    }
                ),
                encoding="utf-8",
            )

            project_config = project_dir / "rbxbundle.json"
            project_config.write_text(
                json.dumps(
                    {
                        "schema_version": _cli.CONFIG_SCHEMA_VERSION,
                        "roblox_rules": {
                            "client_only_prefixes": ["ClientRuntime/"],
                        }
                    }
                ),
                encoding="utf-8",
            )

            old_path = _cli._CONFIG_PATH
            try:
                _cli._CONFIG_PATH = user_config
                rules = _cli._bundle_rules_for_path(in_path)
            finally:
                _cli._CONFIG_PATH = old_path

            self.assertEqual(rules["server_only_prefixes"], ["ServerRuntime/"])
            self.assertEqual(rules["client_only_prefixes"], ["ClientRuntime/"])


class TestCliTextHelpers(unittest.TestCase):
    def test_helpers_use_ascii_markers(self):
        self.assertEqual(_cli.clr("", "[OK]"), "[OK]")
        self.assertEqual(_cli.clr("", "->"), "->")


class TestCliModeRouting(unittest.TestCase):
    def test_no_args_stays_interactive(self):
        self.assertFalse(_cli._should_use_argparse([]))

    def test_explicit_subcommand_uses_argparse(self):
        self.assertTrue(_cli._should_use_argparse(["build"]))

    def test_help_flag_uses_argparse(self):
        self.assertTrue(_cli._should_use_argparse(["--help"]))

    def test_unknown_argument_still_uses_argparse(self):
        self.assertTrue(_cli._should_use_argparse(["lisits"]))


class TestCliConfigValidate(unittest.TestCase):
    def test_validate_config_command_accepts_valid_file(self):
        with tempfile.TemporaryDirectory() as td:
            config_path = Path(td) / "rbxbundle.json"
            config_path.write_text(
                json.dumps(
                    {
                        "schema_version": _cli.CONFIG_SCHEMA_VERSION,
                        "roblox_rules": {
                            "client_only_prefixes": ["ClientRuntime/"],
                        },
                    }
                ),
                encoding="utf-8",
            )

            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = _cli.cmd_config_validate(type("Args", (), {"file": str(config_path)})())

            self.assertEqual(code, 0)
            self.assertEqual(stderr.getvalue(), "")
            self.assertIn("Config is valid.", stdout.getvalue())

    def test_validate_config_command_rejects_invalid_file(self):
        with tempfile.TemporaryDirectory() as td:
            config_path = Path(td) / "rbxbundle.json"
            config_path.write_text(json.dumps({"schema_version": "bad"}), encoding="utf-8")

            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = _cli.cmd_config_validate(type("Args", (), {"file": str(config_path)})())

            self.assertEqual(code, 1)
            self.assertEqual(stderr.getvalue(), "")
            self.assertIn("Config invalid", stdout.getvalue())
            self.assertIn("schema_version must be an integer", stdout.getvalue())

    def test_validate_config_command_finds_default_file_in_cwd(self):
        with tempfile.TemporaryDirectory() as td:
            config_path = Path(td) / "rbxbundle.json"
            config_path.write_text(json.dumps({"input_dir": "legacy-input"}), encoding="utf-8")

            old_cwd = Path.cwd()
            stdout = io.StringIO()
            stderr = io.StringIO()
            try:
                import os

                os.chdir(td)
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    code = _cli.cmd_config_validate(type("Args", (), {"file": None})())
            finally:
                os.chdir(old_cwd)

            self.assertEqual(code, 0)
            self.assertEqual(stderr.getvalue(), "")
            self.assertIn("valid with warnings", stdout.getvalue())
            self.assertIn("missing schema_version", stdout.getvalue())
