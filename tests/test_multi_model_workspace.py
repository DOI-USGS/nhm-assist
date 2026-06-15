from __future__ import annotations

import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from assist.workspace import bridge, cli, service


class ProjectSharedNotebookBridgeTests(unittest.TestCase):
    def test_resolve_project_notebook_context_detects_project_and_workflow(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_root = Path(tmpdir).resolve()
            (workspace_root / "Project_A" / "models").mkdir(parents=True)
            cwd = workspace_root / "Project_A" / "notebooks" / "nhm"
            cwd.mkdir(parents=True)

            context = bridge.resolve_project_notebook_context(cwd=cwd)

            self.assertIsNotNone(context)
            self.assertEqual(context["workspace_root"], workspace_root)
            self.assertEqual(context["project_root"], workspace_root / "Project_A")
            self.assertEqual(
                context["project_config_root"],
                workspace_root / "Project_A" / "project_config",
            )
            self.assertEqual(context["workflow"], "nhm")
            self.assertEqual(context["workflow_dir"], cwd)

    def test_resolve_project_notebook_context_returns_none_for_model_local_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_root = Path(tmpdir).resolve()
            cwd = (
                workspace_root
                / "Project_A"
                / "models"
                / "Walla_Walla"
                / "notebooks"
                / "nhm"
            )
            cwd.mkdir(parents=True)

            context = bridge.resolve_project_notebook_context(cwd=cwd)

            self.assertIsNone(context)


class ProjectSharedNotebookServiceTests(unittest.TestCase):
    def test_bootstrap_workspace_only_creates_workspace_root(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_root = Path(tmpdir).resolve() / "workspace"

            paths = service.bootstrap_workspace(workspace_root)

            self.assertEqual(paths["workspace"], workspace_root)
            self.assertTrue(workspace_root.is_dir())

    def test_create_project_creates_models_and_project_config_containers(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_root = Path(tmpdir).resolve()

            paths = service.create_project(workspace_root, "Project_A")

            self.assertEqual(paths["project"], workspace_root / "Project_A")
            self.assertTrue((paths["project"] / "models").is_dir())
            self.assertTrue((paths["project"] / "project_config").is_dir())
            self.assertTrue((paths["project"] / "notebooks").is_dir())

    def test_create_model_does_not_require_model_local_notebooks_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_root = Path(tmpdir).resolve()
            service.create_project(workspace_root, "Project_A")

            paths = service.create_model(workspace_root, "Project_A", "Walla_Walla")

            model_root = workspace_root / "Project_A" / "models" / "Walla_Walla"
            self.assertEqual(paths["model"], model_root)
            self.assertTrue((model_root / "config").is_dir())
            self.assertTrue((model_root / "inputs").is_dir())
            self.assertTrue((model_root / "outputs").is_dir())
            self.assertFalse((model_root / "notebooks").exists())

    def test_set_active_model_writes_project_config_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_root = Path(tmpdir).resolve()
            service.create_project(workspace_root, "Project_A")
            service.create_model(workspace_root, "Project_A", "Walla_Walla")

            config_path = service.set_active_model(
                workspace_root,
                project_name="Project_A",
                model_name="Walla_Walla",
            )

            self.assertEqual(
                config_path,
                workspace_root
                / "Project_A"
                / "project_config"
                / "active_model.yaml",
            )
            self.assertTrue(config_path.exists())
            self.assertEqual(
                service.get_active_model_name(workspace_root, "Project_A"),
                "Walla_Walla",
            )
            self.assertEqual(
                service.get_active_model_root(workspace_root, "Project_A"),
                workspace_root / "Project_A" / "models" / "Walla_Walla",
            )

    def test_set_active_model_rejects_missing_model(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_root = Path(tmpdir).resolve()
            service.create_project(workspace_root, "Project_A")

            with self.assertRaisesRegex(FileNotFoundError, "Walla_Walla"):
                service.set_active_model(
                    workspace_root,
                    project_name="Project_A",
                    model_name="Walla_Walla",
                )

    def test_prepare_model_runtime_copies_source_data_without_model_notebooks_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_root = Path(tmpdir).resolve()
            service.create_project(workspace_root, "Project_A")
            service.create_model(workspace_root, "Project_A", "Walla_Walla")
            model_root = workspace_root / "Project_A" / "models" / "Walla_Walla"
            source_root = model_root / "inputs" / "source_data"
            source_root.mkdir(parents=True, exist_ok=True)
            (source_root / "control.default.bandit").write_text("control\n")
            (source_root / "GIS").mkdir()
            (source_root / "GIS" / "model_layers.gpkg").write_text("gpkg\n")

            runtime = service.prepare_model_runtime(
                workspace_root,
                project_name="Project_A",
                model_name="Walla_Walla",
            )

            self.assertEqual(runtime["project_root"], workspace_root / "Project_A")
            self.assertEqual(runtime["model_root"], model_root)
            self.assertEqual(runtime["source_model_dir"], source_root)
            self.assertEqual(runtime["config_root"], model_root / "config")
            self.assertEqual(
                runtime["runtime_model_dir"], model_root / "outputs" / "runtime"
            )
            self.assertTrue(
                (runtime["runtime_model_dir"] / "control.default.bandit").exists()
            )
            self.assertTrue(
                (runtime["runtime_model_dir"] / "GIS" / "model_layers.gpkg").exists()
            )

    def test_resolve_nhm_runtime_paths_uses_repo_local_domain_data_outside_workspace(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir).resolve() / "nhm-assist"
            cwd = repo_root / "notebooks"
            cwd.mkdir(parents=True)

            runtime = service.resolve_nhm_runtime_paths(
                "Walla_Walla",
                cwd=cwd,
                env={"PIXI_PROJECT_ROOT": str(repo_root)},
            )

            self.assertEqual(runtime["repo_root"], repo_root)
            self.assertEqual(runtime["config_root"], repo_root)
            self.assertIsNone(runtime["workspace_root"])
            self.assertEqual(
                runtime["model_dir"], repo_root / "domain_data" / "Walla_Walla"
            )

    def test_resolve_nhm_runtime_paths_raises_when_project_has_no_active_model(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sandbox = Path(tmpdir).resolve()
            repo_root = sandbox / "nhm-assist"
            workspace_root = sandbox / "workspace"
            service.create_project(workspace_root, "Project_A")
            service.create_model(workspace_root, "Project_A", "Walla_Walla")
            source_root = (
                workspace_root
                / "Project_A"
                / "models"
                / "Walla_Walla"
                / "inputs"
                / "source_data"
            )
            source_root.mkdir(parents=True, exist_ok=True)
            (source_root / "control.default.bandit").write_text("control\n")
            cwd = workspace_root / "Project_A" / "notebooks" / "nhm"
            cwd.mkdir(parents=True, exist_ok=True)

            with self.assertRaisesRegex(FileNotFoundError, "active_model.yaml"):
                service.resolve_nhm_runtime_paths(
                    "Walla_Walla",
                    cwd=cwd,
                    env={"PIXI_PROJECT_ROOT": str(repo_root)},
                )

    def test_resolve_nhm_runtime_paths_uses_active_model_from_project_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sandbox = Path(tmpdir).resolve()
            repo_root = sandbox / "nhm-assist"
            workspace_root = sandbox / "workspace"
            service.create_project(workspace_root, "Project_A")
            service.create_model(workspace_root, "Project_A", "Walla_Walla")
            source_root = (
                workspace_root
                / "Project_A"
                / "models"
                / "Walla_Walla"
                / "inputs"
                / "source_data"
            )
            source_root.mkdir(parents=True, exist_ok=True)
            (source_root / "control.default.bandit").write_text("control\n")
            service.set_active_model(
                workspace_root,
                project_name="Project_A",
                model_name="Walla_Walla",
            )
            cwd = workspace_root / "Project_A" / "notebooks" / "nhm"
            cwd.mkdir(parents=True, exist_ok=True)

            runtime = service.resolve_nhm_runtime_paths(
                "Walla_Walla",
                cwd=cwd,
                env={"PIXI_PROJECT_ROOT": str(repo_root)},
            )

            self.assertEqual(runtime["repo_root"], repo_root)
            self.assertEqual(runtime["workspace_root"], workspace_root)
            self.assertEqual(runtime["project_root"], workspace_root / "Project_A")
            self.assertEqual(
                runtime["model_root"],
                workspace_root / "Project_A" / "models" / "Walla_Walla",
            )
            self.assertEqual(
                runtime["config_root"],
                workspace_root / "Project_A" / "models" / "Walla_Walla" / "config",
            )
            self.assertEqual(
                runtime["model_dir"],
                workspace_root
                / "Project_A"
                / "models"
                / "Walla_Walla"
                / "outputs"
                / "runtime",
            )
            self.assertTrue(
                (runtime["model_dir"] / "control.default.bandit").exists()
            )

    def test_switching_active_models_keeps_runtime_outputs_separate(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sandbox = Path(tmpdir).resolve()
            repo_root = sandbox / "nhm-assist"
            workspace_root = sandbox / "workspace"
            service.create_project(workspace_root, "Project_A")
            for model_name in ("Model_A", "Model_B"):
                service.create_model(workspace_root, "Project_A", model_name)
                source_root = (
                    workspace_root
                    / "Project_A"
                    / "models"
                    / model_name
                    / "inputs"
                    / "source_data"
                )
                source_root.mkdir(parents=True, exist_ok=True)
                (source_root / "control.default.bandit").write_text("control\n")
            cwd = workspace_root / "Project_A" / "notebooks" / "nhm"
            cwd.mkdir(parents=True, exist_ok=True)

            service.set_active_model(
                workspace_root, project_name="Project_A", model_name="Model_A"
            )
            runtime_a = service.resolve_nhm_runtime_paths(
                "Model_A",
                cwd=cwd,
                env={"PIXI_PROJECT_ROOT": str(repo_root)},
            )

            service.set_active_model(
                workspace_root, project_name="Project_A", model_name="Model_B"
            )
            runtime_b = service.resolve_nhm_runtime_paths(
                "Model_B",
                cwd=cwd,
                env={"PIXI_PROJECT_ROOT": str(repo_root)},
            )

            self.assertNotEqual(runtime_a["model_root"], runtime_b["model_root"])
            self.assertTrue((runtime_a["model_dir"] / "control.default.bandit").exists())
            self.assertTrue((runtime_b["model_dir"] / "control.default.bandit").exists())


class ProjectSharedNotebookCliTests(unittest.TestCase):
    def test_build_parser_supports_project_set_active_model(self):
        parser = cli.build_parser()

        args = parser.parse_args(
            [
                "project-set-active-model",
                "--workspace-root",
                "/tmp/workspace",
                "--project-name",
                "Project_A",
                "--model-name",
                "Walla_Walla",
            ]
        )

        self.assertEqual(args.command, "project-set-active-model")
        self.assertEqual(args.project_name, "Project_A")
        self.assertEqual(args.model_name, "Walla_Walla")

    def test_build_parser_supports_model_list(self):
        parser = cli.build_parser()

        args = parser.parse_args(
            [
                "model-list",
                "--workspace-root",
                "/tmp/workspace",
                "--project-name",
                "Project_A",
            ]
        )

        self.assertEqual(args.command, "model-list")
        self.assertEqual(args.project_name, "Project_A")

    def test_main_lists_models_for_project(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_root = Path(tmpdir).resolve()
            service.create_project(workspace_root, "Project_A")
            service.create_model(workspace_root, "Project_A", "Walla_Walla")

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = cli.main(
                    [
                        "model-list",
                        "--workspace-root",
                        str(workspace_root),
                        "--project-name",
                        "Project_A",
                    ]
                )

        self.assertEqual(exit_code, 0)
        self.assertEqual(stdout.getvalue().strip(), "Walla_Walla")


if __name__ == "__main__":
    unittest.main()
