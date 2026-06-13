from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from assist.workspace import cli, service, setup


class WorkspaceSetupTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.tmp_path = Path(self._tmpdir.name).resolve()
        self.repo_root = self.tmp_path / "repo"
        self.repo_root.mkdir()
        self.workspace_root = self.tmp_path / "workspace"

    def test_load_workspace_root_returns_none_when_dotenv_missing(self):
        result = setup.load_workspace_root_from_dotenv(self.repo_root)

        self.assertIsNone(result)

    def test_save_workspace_root_writes_repo_dotenv(self):
        setup.save_workspace_root_to_dotenv(self.repo_root, self.workspace_root)

        dotenv_text = (self.repo_root / ".env").read_text(encoding="utf-8")
        self.assertIn("NHM_ASSIST_WORKSPACE_ROOT=", dotenv_text)
        self.assertIn(str(self.workspace_root.resolve()), dotenv_text)

    def test_prompt_required_text_reprompts_with_clear_text_message(self):
        prompts: list[str] = []
        answers = iter(["", "Project_A"])

        result = setup.prompt_required_text(
            "Type project name:",
            input_func=lambda prompt: prompts.append(prompt) or next(answers),
        )

        self.assertEqual(result, "Project_A")
        self.assertEqual(
            prompts,
            [
                "Type project name: ",
                "Type project name: ",
            ],
        )

    def test_prompt_menu_choice_uses_number_language(self):
        prompts: list[str] = []
        printed: list[str] = []
        answers = iter(["Project_A", "12", "2"])

        result = setup.prompt_menu_choice(
            9,
            input_func=lambda prompt: prompts.append(prompt) or next(answers),
            print_func=printed.append,
        )

        self.assertEqual(result, 2)
        self.assertEqual(
            prompts,
            [
                "Select menu option number [0-9]: ",
                "Select menu option number [0-9]: ",
                "Select menu option number [0-9]: ",
            ],
        )
        self.assertEqual(
            printed,
            [
                "Please enter a menu number.",
                "Please enter a menu number between 0 and 9.",
            ],
        )

    def test_action_create_project_sets_current_project(self):
        state = setup.SetupState(
            repo_root=self.repo_root,
            workspace_root=self.workspace_root,
        )

        with patch.object(setup, "prompt_required_text", side_effect=["Project_A"]):
            setup.action_create_project(state, print_func=lambda *_: None)

        self.assertEqual(state.current_project, "Project_A")
        self.assertTrue((self.workspace_root / "Project_A" / "models").is_dir())

    def test_action_create_project_uses_type_project_name_prompt(self):
        state = setup.SetupState(
            repo_root=self.repo_root,
            workspace_root=self.workspace_root,
        )

        with patch.object(
            setup,
            "prompt_required_text",
            return_value="Project_A",
        ) as mock_prompt:
            setup.action_create_project(state, print_func=lambda *_: None)

        mock_prompt.assert_called_once_with(
            "Type project name:",
            input_func=input,
        )

    def test_action_open_project_selects_existing_project(self):
        service.create_project(self.workspace_root, "Project_A")
        service.create_project(self.workspace_root, "Project_B")
        state = setup.SetupState(
            repo_root=self.repo_root,
            workspace_root=self.workspace_root,
        )

        with patch.object(setup, "prompt_menu_choice", return_value=2):
            setup.action_open_project(state, print_func=lambda *_: None)

        self.assertEqual(state.current_project, "Project_B")

    def test_action_copy_example_model_uses_numbered_example_selection(self):
        state = setup.SetupState(
            repo_root=self.repo_root,
            workspace_root=self.workspace_root,
            current_project="Project_A",
        )

        with patch.object(
            setup,
            "list_available_example_names",
            return_value=["Rogue_River", "Walla_Walla"],
        ), patch.object(
            setup,
            "prompt_required_text",
            return_value="Model_A",
        ) as mock_text, patch.object(
            setup,
            "prompt_menu_choice",
            return_value=2,
        ) as mock_choice, patch.object(
            setup.service,
            "copy_example_model",
            return_value={"model": self.workspace_root / "Project_A" / "models" / "Model_A"},
        ) as mock_copy:
            setup.action_copy_example_model(state, print_func=lambda *_: None)

        mock_text.assert_called_once_with(
            "Type model name:",
            input_func=input,
        )
        mock_choice.assert_called_once_with(
            2,
            input_func=input,
            print_func=unittest.mock.ANY,
        )
        mock_copy.assert_called_once_with(
            self.workspace_root,
            "Project_A",
            "Model_A",
            "Walla_Walla",
        )

    def test_require_current_project_returns_false_without_selection(self):
        state = setup.SetupState(
            repo_root=self.repo_root,
            workspace_root=self.workspace_root,
        )
        printed: list[str] = []

        ok = setup.require_current_project(state, print_func=printed.append)

        self.assertFalse(ok)
        self.assertTrue(any("Select or create a project first." in line for line in printed))

    def test_action_generate_nhm_notebooks_calls_convert_workflow(self):
        state = setup.SetupState(
            repo_root=self.repo_root,
            workspace_root=self.workspace_root,
            current_project="Project_A",
        )

        with patch.object(
            setup.notebook_builder,
            "convert_workflow",
            return_value=[],
        ) as mock_convert:
            setup.action_generate_nhm_notebooks(state, print_func=lambda *_: None)

        mock_convert.assert_called_once_with(
            "nhm",
            workspace_root=self.workspace_root,
            project_name="Project_A",
            dry_run=False,
        )

    def test_action_launch_jupyter_uses_project_root(self):
        state = setup.SetupState(
            repo_root=self.repo_root,
            workspace_root=self.workspace_root,
            current_project="Project_A",
        )

        with patch("assist.workspace.setup.subprocess.Popen") as mock_popen:
            setup.action_launch_jupyter(state, print_func=lambda *_: None)

        command = mock_popen.call_args.args[0]
        self.assertEqual(
            command,
            [
                sys.executable,
                "-m",
                "jupyter",
                "lab",
                str(self.workspace_root / "Project_A"),
            ],
        )

    def test_build_parser_supports_setup_command(self):
        parser = cli.build_parser()
        args = parser.parse_args(["setup"])

        self.assertEqual(args.command, "setup")


if __name__ == "__main__":
    unittest.main()
