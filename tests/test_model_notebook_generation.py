from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from assist.workspace import bridge, service
from workflow_templates import make_notebooks as notebook_builder


class ProjectNotebookGenerationTests(unittest.TestCase):
    def test_convert_workflow_writes_to_project_local_notebook_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_root = Path(tmpdir).resolve()
            service.create_project(workspace_root, "Project_A")
            service.create_model(workspace_root, "Project_A", "Walla_Walla")

            created_paths = notebook_builder.convert_workflow(
                "nhm",
                workspace_root=workspace_root,
                project_name="Project_A",
            )

            output_dir = bridge.get_project_workflow_notebooks_dir(
                "nhm",
                workspace_root,
                "Project_A",
            )
            self.assertTrue(output_dir.is_dir())
            self.assertTrue(created_paths)
            self.assertTrue(all(path.is_file() for path in created_paths))
            self.assertTrue(all(str(output_dir) in str(path) for path in created_paths))
            self.assertFalse(
                (
                    workspace_root
                    / "Project_A"
                    / "models"
                    / "Walla_Walla"
                    / "notebooks"
                    / "nhm"
                ).exists()
            )

    def test_parse_args_supports_project_local_notebook_generation(self):
        args = notebook_builder.parse_args(
            [
                "--workflow",
                "nhm",
                "--workspace-root",
                "/tmp/workspace",
                "--project-name",
                "Project_A",
            ]
        )

        self.assertEqual(args.workspace_root, "/tmp/workspace")
        self.assertEqual(args.project_name, "Project_A")
        self.assertIsNone(args.model_name)


if __name__ == "__main__":
    unittest.main()
