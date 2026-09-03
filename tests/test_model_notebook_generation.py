from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import jupytext
from jupytext.paired_paths import paired_paths
from nbformat.v4 import new_code_cell

from assist.workspace import bridge, kernels, service
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
        self.assertFalse(hasattr(args, "model_name"))

    def test_repo_relative_notebook_helpers_are_gone(self):
        self.assertFalse(hasattr(bridge, "REPO_NOTEBOOK_DIRS"))
        self.assertFalse(hasattr(bridge, "get_workflow_notebooks_dir"))

    def test_convert_workflow_requires_a_project(self):
        with self.assertRaises(TypeError):
            notebook_builder.convert_workflow("nhm")

        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(ValueError):
                notebook_builder.convert_workflow(
                    "nhm",
                    workspace_root=Path(tmpdir).resolve(),
                    project_name="",
                )


class PairingModeTests(unittest.TestCase):
    def setUp(self):
        # dev pairing is a relative path, so the workspace has to share a
        # parent with the repo. The platform temp directory does not on macOS
        # (/var/folders/... vs /Users/...), so anchor the temp workspace beside
        # the repo instead of wherever tempfile would default to.
        repo_root = notebook_builder.TEMPLATES_ROOT.parents[1]
        self._tmpdir = tempfile.TemporaryDirectory(dir=repo_root.parent)
        self.addCleanup(self._tmpdir.cleanup)
        self.workspace_root = Path(self._tmpdir.name).resolve()
        service.create_project(self.workspace_root, "Project_A")
        self.notebook_dir = bridge.get_project_workflow_notebooks_dir(
            "nhm", self.workspace_root, "Project_A"
        )

    def _generate(self, pairing_mode):
        return notebook_builder.convert_workflow(
            "nhm",
            workspace_root=self.workspace_root,
            project_name="Project_A",
            pairing_mode=pairing_mode,
            print_func=lambda *_: None,
        )

    def test_dev_pairing_formats_is_relative_and_resolves_to_the_template(self):
        template_dir = notebook_builder.WORKFLOW_INPUT_DIRS["nhm"][0]

        formats = notebook_builder.dev_pairing_formats(
            template_dir, self.notebook_dir
        )

        prefix = formats.split(",", 1)[1]
        self.assertFalse(
            prefix.startswith("/"),
            "jupytext concatenates the prefix onto the notebook dir, so an "
            "absolute path resolves to a nonsense location",
        )
        self.assertTrue(prefix.endswith("//py:percent"))

        # Ask jupytext itself where the pairing lands. Resolving this with
        # os.path semantics instead would pass even when jupytext gets it
        # wrong, which is exactly how this bug went unnoticed.
        paired = [
            path
            for path, fmt in paired_paths(
                str(self.notebook_dir / "probe.ipynb"), "ipynb", formats
            )
            if fmt.get("extension") == ".py"
        ]
        self.assertEqual([Path(p) for p in paired], [template_dir / "probe.py"])

    def test_local_mode_embeds_no_formats_but_stamps_the_default_kernel(self):
        created = self._generate("local")

        self.assertTrue(created)
        notebook = jupytext.read(created[0])
        self.assertIsNone(notebook.metadata.get("jupytext", {}).get("formats"))
        self.assertEqual(
            notebook.metadata["kernelspec"]["name"], kernels.DEFAULT_KERNEL_NAME
        )

    def test_dev_mode_embeds_formats_pointing_at_the_repo_template(self):
        created = self._generate("dev")

        notebook = jupytext.read(created[0])
        formats = notebook.metadata["jupytext"]["formats"]
        template_dir = notebook_builder.WORKFLOW_INPUT_DIRS["nhm"][0]
        self.assertEqual(
            formats,
            notebook_builder.dev_pairing_formats(template_dir, self.notebook_dir),
        )
        self.assertEqual(
            notebook.metadata["kernelspec"]["name"], kernels.DEV_KERNEL_NAME
        )

    def test_dev_mode_writes_a_header_free_template(self):
        # Regression: without notebook_metadata_filter, syncing a dev-mode
        # notebook stamps the workspace's own relative formats path and local
        # jupytext_version into the shared, committed repo template, churning
        # on every contributor's save. Generates against a scratch copy of
        # the template dir so the sync-triggered write never touches the
        # real, tracked template.
        scratch_template_dir = self.workspace_root / "template_scratch" / "nhm"
        shutil.copytree(
            notebook_builder.WORKFLOW_INPUT_DIRS["nhm"][0], scratch_template_dir
        )

        with patch.dict(
            notebook_builder.WORKFLOW_INPUT_DIRS, {"nhm": (scratch_template_dir,)}
        ):
            created = self._generate("dev")
            target = created[0]

            notebook = jupytext.read(target)
            self.assertEqual(
                notebook.metadata["jupytext"]["notebook_metadata_filter"], "-all"
            )

            notebook.cells.append(new_code_cell("print('synced from the workspace')"))
            jupytext.write(notebook, target)
            subprocess.run(
                [sys.executable, "-m", "jupytext", "--sync", str(target)],
                check=True,
            )

        template_path = scratch_template_dir / target.relative_to(
            self.notebook_dir
        ).with_suffix(".py")
        template_text = template_path.read_text()
        self.assertFalse(template_text.startswith("# ---"))
        self.assertIn("synced from the workspace", template_text)

    def test_dev_mode_repairs_notebooks_missing_the_metadata_filter(self):
        created = self._generate("dev")
        target = created[0]

        notebook = jupytext.read(target)
        del notebook.metadata["jupytext"]["notebook_metadata_filter"]
        jupytext.write(notebook, target)

        self._generate("dev")

        reread = jupytext.read(target)
        self.assertEqual(
            reread.metadata["jupytext"]["notebook_metadata_filter"], "-all"
        )

    def test_dev_mode_never_rewrites_existing_cell_content(self):
        created = self._generate("local")
        target = created[0]

        notebook = jupytext.read(target)
        notebook.cells[0].source = "# EDITED BY THE USER"
        jupytext.write(notebook, target)

        self._generate("dev")

        reread = jupytext.read(target)
        self.assertEqual(reread.cells[0].source, "# EDITED BY THE USER")
        self.assertIn("jupytext", reread.metadata)
        self.assertEqual(
            reread.metadata["kernelspec"]["name"], kernels.DEV_KERNEL_NAME
        )

    def test_switching_to_local_mode_preserves_cell_content(self):
        # Regression: regenerating in local mode over an existing notebook
        # used to always re-read the repo template and overwrite cells,
        # silently discarding anything not yet synced back to the template
        # -- whether that notebook came from dev mode or was hand-edited
        # in local mode. This is also what nhm_notebooks_need_generation's
        # mtime check triggers automatically after a `git pull`.
        created = self._generate("dev")
        target = created[0]

        notebook = jupytext.read(target)
        notebook.cells[0].source = "# UNSYNCED EDIT MADE IN DEV MODE"
        jupytext.write(notebook, target)

        self._generate("local")

        reread = jupytext.read(target)
        self.assertEqual(reread.cells[0].source, "# UNSYNCED EDIT MADE IN DEV MODE")

    def test_switching_to_local_mode_clears_dev_pairing_metadata(self):
        self._generate("dev")
        target = self.notebook_dir / "0_workspace_setup.ipynb"

        self._generate("local")

        reread = jupytext.read(target)
        self.assertIsNone(reread.metadata.get("jupytext", {}).get("formats"))
        self.assertIsNone(
            reread.metadata.get("jupytext", {}).get("notebook_metadata_filter")
        )
        self.assertEqual(
            reread.metadata["kernelspec"]["name"], kernels.DEFAULT_KERNEL_NAME
        )

    def test_local_mode_regeneration_preserves_existing_cell_edits(self):
        created = self._generate("local")
        target = created[0]

        notebook = jupytext.read(target)
        notebook.cells[0].source = "# HAND EDIT IN LOCAL MODE"
        jupytext.write(notebook, target)

        self._generate("local")

        reread = jupytext.read(target)
        self.assertEqual(reread.cells[0].source, "# HAND EDIT IN LOCAL MODE")

    def test_local_mode_regeneration_does_not_require_a_reachable_repo(self):
        # Local mode's own pairing comes from the project's jupytext.toml,
        # not from the repo, so regenerating over an existing notebook must
        # not need dev_pairing_formats' repo-reachability at all -- unlike a
        # dev-mode workspace, a real end user's workspace has no relationship
        # to the nhm-assist repo path whatsoever.
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_root = Path(tmpdir).resolve()
            service.create_project(workspace_root, "Project_A")
            notebook_dir = bridge.get_project_workflow_notebooks_dir(
                "nhm", workspace_root, "Project_A"
            )

            notebook_builder.convert_workflow(
                "nhm",
                workspace_root=workspace_root,
                project_name="Project_A",
                pairing_mode="local",
                print_func=lambda *_: None,
            )
            notebook_builder.convert_workflow(
                "nhm",
                workspace_root=workspace_root,
                project_name="Project_A",
                pairing_mode="local",
                print_func=lambda *_: None,
            )

            self.assertTrue(any(notebook_dir.rglob("*.ipynb")))

    def test_dev_mode_is_idempotent(self):
        self._generate("dev")
        second = {path: path.read_bytes() for path in self.notebook_dir.rglob("*.ipynb")}

        self._generate("dev")
        third = {path: path.read_bytes() for path in self.notebook_dir.rglob("*.ipynb")}

        self.assertEqual(second.keys(), third.keys())
        for path, payload in second.items():
            self.assertEqual(payload, third[path], f"{path} changed on a repeat run")

    def test_dev_pairing_rejects_a_workspace_it_cannot_reach(self):
        template_dir = notebook_builder.WORKFLOW_INPUT_DIRS["nhm"][0]
        # Only common ancestor with the repo is the filesystem root, so
        # jupytext would silently resolve the pairing into the current working
        # directory instead of the repo.
        unreachable = Path(os.sep) / "nhm_probe" / "notebooks" / "nhm"

        with self.assertRaises(ValueError) as ctx:
            notebook_builder.dev_pairing_formats(template_dir, unreachable)

        message = str(ctx.exception)
        self.assertIn("cannot reach the nhm-assist repo", message)
        self.assertIn(str(unreachable), message)

    def test_convert_workflow_rejects_an_unknown_pairing_mode(self):
        with self.assertRaises(ValueError):
            self._generate("sideways")

    def test_parse_args_defaults_to_local_pairing(self):
        args = notebook_builder.parse_args(
            ["--workspace-root", "/tmp/ws", "--project-name", "Project_A"]
        )
        self.assertEqual(args.pairing_mode, "local")

        dev_args = notebook_builder.parse_args(
            [
                "--workspace-root",
                "/tmp/ws",
                "--project-name",
                "Project_A",
                "--pairing-mode",
                "dev",
            ]
        )
        self.assertEqual(dev_args.pairing_mode, "dev")


if __name__ == "__main__":
    unittest.main()
