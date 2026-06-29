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
            mock_popen.return_value.poll.return_value = None
            mock_popen.return_value.pid = 12345
            setup.action_launch_jupyter(
                state,
                print_func=lambda *_: None,
                startup_probe_seconds=0,
            )

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

    def test_action_launch_jupyter_reports_when_jupyterlab_missing(self):
        state = setup.SetupState(
            repo_root=self.repo_root,
            workspace_root=self.workspace_root,
            current_project="Project_A",
        )
        printed: list[str] = []

        with patch(
            "assist.workspace.setup.importlib.util.find_spec",
            return_value=None,
        ), patch("assist.workspace.setup.subprocess.Popen") as mock_popen:
            result = setup.action_launch_jupyter(
                state,
                print_func=printed.append,
                startup_probe_seconds=0,
            )

        self.assertIsNone(result)
        mock_popen.assert_not_called()
        self.assertTrue(
            any("JupyterLab is not installed" in line for line in printed),
            f"expected missing-jupyterlab message, got: {printed}",
        )

    def test_action_launch_jupyter_reports_when_process_exits_immediately(self):
        state = setup.SetupState(
            repo_root=self.repo_root,
            workspace_root=self.workspace_root,
            current_project="Project_A",
        )
        printed: list[str] = []

        with patch("assist.workspace.setup.subprocess.Popen") as mock_popen:
            mock_popen.return_value.poll.return_value = 1
            mock_popen.return_value.returncode = 1
            mock_popen.return_value.pid = 12345
            result = setup.action_launch_jupyter(
                state,
                print_func=printed.append,
                startup_probe_seconds=0,
            )

        self.assertIsNone(result)
        self.assertTrue(
            any("exited immediately with code 1" in line for line in printed),
            f"expected immediate-exit message, got: {printed}",
        )

    def test_action_launch_jupyter_reports_when_popen_raises(self):
        state = setup.SetupState(
            repo_root=self.repo_root,
            workspace_root=self.workspace_root,
            current_project="Project_A",
        )
        printed: list[str] = []

        with patch(
            "assist.workspace.setup.subprocess.Popen",
            side_effect=FileNotFoundError("python not found"),
        ):
            result = setup.action_launch_jupyter(
                state,
                print_func=printed.append,
                startup_probe_seconds=0,
            )

        self.assertIsNone(result)
        self.assertTrue(
            any("failed to start Jupyter" in line for line in printed),
            f"expected popen-failure message, got: {printed}",
        )

    def test_build_parser_supports_setup_command(self):
        parser = cli.build_parser()
        args = parser.parse_args(["setup"])

        self.assertEqual(args.command, "setup")

    def test_prompt_workspace_root_uses_default_on_blank_input(self):
        printed: list[str] = []
        default_target = self.tmp_path / "default_workspace"

        with patch.object(
            setup,
            "DEFAULT_WORKSPACE_ROOT",
            default_target,
        ):
            result = setup.prompt_workspace_root(
                self.repo_root,
                print_func=printed.append,
                input_func=lambda *_: "",
            )

        self.assertEqual(result, default_target.expanduser().resolve())
        self.assertTrue(result.is_dir())
        self.assertTrue(
            any(str(default_target.expanduser().resolve()) in line for line in printed),
            f"expected default path in guidance lines, got: {printed}",
        )

    def test_prompt_workspace_root_warns_when_inside_repo_and_re_prompts_on_no(self):
        printed: list[str] = []
        inside_repo = self.repo_root / "ws_inside"
        outside_repo = self.tmp_path / "ws_outside"
        answers = iter([str(inside_repo), "n", str(outside_repo), "y"])

        result = setup.prompt_workspace_root(
            self.repo_root,
            print_func=printed.append,
            input_func=lambda *_: next(answers),
        )

        self.assertEqual(result, outside_repo.resolve())
        self.assertTrue(result.is_dir())
        self.assertTrue(
            any("inside the repository" in line for line in printed),
            f"expected an inside-repo warning, got: {printed}",
        )

    def test_action_set_workspace_root_clears_current_project_when_absent_in_new_workspace(self):
        old_workspace = self.tmp_path / "ws_old"
        new_workspace = self.tmp_path / "ws_new"
        from assist.workspace import service
        service.create_project(old_workspace, "Columbia_Study")
        state = setup.SetupState(
            repo_root=self.repo_root,
            workspace_root=old_workspace,
            current_project="Columbia_Study",
        )
        printed: list[str] = []

        with patch.object(setup, "prompt_workspace_root", return_value=new_workspace):
            setup.action_set_workspace_root(
                state,
                print_func=printed.append,
                input_func=lambda *_: "",
            )

        self.assertIsNone(state.current_project)
        self.assertTrue(
            any("Cleared current project 'Columbia_Study'" in line for line in printed),
            f"expected clear notice, got: {printed}",
        )

    def test_action_set_workspace_root_keeps_current_project_when_present_in_new_workspace(self):
        old_workspace = self.tmp_path / "ws_old"
        new_workspace = self.tmp_path / "ws_new"
        from assist.workspace import service
        service.create_project(old_workspace, "Columbia_Study")
        service.create_project(new_workspace, "Columbia_Study")
        state = setup.SetupState(
            repo_root=self.repo_root,
            workspace_root=old_workspace,
            current_project="Columbia_Study",
        )

        with patch.object(setup, "prompt_workspace_root", return_value=new_workspace):
            setup.action_set_workspace_root(
                state,
                print_func=lambda *_: None,
                input_func=lambda *_: "",
            )

        self.assertEqual(state.current_project, "Columbia_Study")

    def test_action_set_workspace_root_no_change_keeps_current_project(self):
        from assist.workspace import service
        service.create_project(self.workspace_root, "Columbia_Study")
        state = setup.SetupState(
            repo_root=self.repo_root,
            workspace_root=self.workspace_root,
            current_project="Columbia_Study",
        )

        with patch.object(setup, "prompt_workspace_root", return_value=self.workspace_root):
            setup.action_set_workspace_root(
                state,
                print_func=lambda *_: None,
                input_func=lambda *_: "",
            )

        self.assertEqual(state.current_project, "Columbia_Study")


if __name__ == "__main__":
    unittest.main()
