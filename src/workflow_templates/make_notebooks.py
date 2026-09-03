import argparse
from pathlib import Path

import jupytext

from assist.workspace.bridge import (
    get_project_workflow_notebooks_dir,
    get_workflow_notebooks_dir,
)


TEMPLATES_ROOT = Path(__file__).resolve().parent

COMMON_DIR = TEMPLATES_ROOT / "common"

# The numbered workflow notebooks live once, in common/. nhm renders only those;
# nhf layers its own workflow-specific templates (the FMI variant and its
# parameter-building utilities) on top; pest is still separate.
WORKFLOW_INPUT_DIRS: dict[str, tuple[Path, ...]] = {
    "nhm": (COMMON_DIR,),
    "nhf": (COMMON_DIR, TEMPLATES_ROOT / "nhf"),
    "pest": (TEMPLATES_ROOT / "pest",),
}


def iter_workflow_templates(name: str) -> list[tuple[Path, Path]]:
    """Return (template_path, output-relative path) for one workflow.

    A later input directory may not shadow an earlier one. If a workflow
    directory ever reintroduces a template whose name collides with a shared
    one, that is precisely the duplication this layout exists to remove, so it
    raises instead of silently overriding.
    """
    collected: list[tuple[Path, Path]] = []
    seen: dict[Path, Path] = {}

    for input_dir in WORKFLOW_INPUT_DIRS[name]:
        if not input_dir.exists():
            raise FileNotFoundError(f"Missing workflow template folder: {input_dir}")
        for py_file in sorted(input_dir.rglob("*.py")):
            relative = py_file.relative_to(input_dir)
            if relative in seen:
                raise ValueError(
                    f"{name}: {relative} exists in both {seen[relative]} and "
                    f"{input_dir}; the copy in common/ must be the only one"
                )
            seen[relative] = input_dir
            collected.append((py_file, relative))

    return collected


def convert_workflow(
    name: str,
    *,
    workspace_root: str | Path | None = None,
    project_name: str | None = None,
    dry_run: bool = False,
) -> list[Path]:
    templates = iter_workflow_templates(name)
    if workspace_root is None:
        output_folder = get_workflow_notebooks_dir(name)
        in_workspace_mode = False
    else:
        if not project_name:
            raise ValueError("project_name is required when workspace_root is set")
        output_folder = get_project_workflow_notebooks_dir(
            name, workspace_root, project_name
        )
        in_workspace_mode = True
    created_paths = []

    output_folder.mkdir(parents=True, exist_ok=True)

    for py_file, relative_path in templates:
        output_path = output_folder / relative_path.with_suffix(".ipynb")
        created_paths.append(output_path)

        print(f"[{name}] Converting {py_file} -> {output_path}")
        if dry_run:
            continue

        output_path.parent.mkdir(parents=True, exist_ok=True)
        notebook = jupytext.read(py_file)
        if in_workspace_mode:
            # Workspace .ipynb files are user-owned copies; they must not pair
            # back to the repo's source templates on save.
            jupytext_meta = notebook.metadata.get("jupytext", {})
            jupytext_meta.pop("formats", None)
        jupytext.write(notebook, output_path)

    return created_paths


def parse_args(argv: list[str] | None = None, *, default_workflow: str = "nhm"):
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--workflow",
        choices=["nhm", "nhf", "pest", "all"],
        default=default_workflow,
        help="Workflow template set to convert.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned conversions without writing notebooks.",
    )
    parser.add_argument(
        "--workspace-root",
        help="Optional external workspace root for notebook output.",
    )
    parser.add_argument(
        "--project-name",
        help="Project name for project-shared workspace notebook output.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None, *, default_workflow: str = "nhm") -> int:
    args = parse_args(argv, default_workflow=default_workflow)
    workflows = list(WORKFLOW_INPUT_DIRS) if args.workflow == "all" else [args.workflow]

    for workflow in workflows:
        convert_workflow(
            workflow,
            workspace_root=args.workspace_root,
            project_name=args.project_name,
            dry_run=args.dry_run,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
