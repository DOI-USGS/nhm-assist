import argparse
from pathlib import Path

import jupytext

from assist.workspace.bridge import get_workflow_notebooks_dir


TEMPLATES_ROOT = Path(__file__).resolve().parent

WORKFLOW_INPUT_DIRS = {
    "nhm": TEMPLATES_ROOT / "nhm",
    "nhf": TEMPLATES_ROOT / "nhf",
    "pest": TEMPLATES_ROOT / "pest",
}


def convert_workflow(
    name: str,
    *,
    workspace_root: str | Path | None = None,
    dry_run: bool = False,
) -> list[Path]:
    input_folder = WORKFLOW_INPUT_DIRS[name]
    output_folder = get_workflow_notebooks_dir(name, workspace_root)
    created_paths = []

    if not input_folder.exists():
        raise FileNotFoundError(f"Missing workflow template folder: {input_folder}")

    output_folder.mkdir(parents=True, exist_ok=True)

    for py_file in sorted(input_folder.rglob("*.py")):
        relative_path = py_file.relative_to(input_folder)
        output_path = output_folder / relative_path.with_suffix(".ipynb")
        created_paths.append(output_path)

        print(f"[{name}] Converting {py_file} -> {output_path}")
        if dry_run:
            continue

        output_path.parent.mkdir(parents=True, exist_ok=True)
        notebook = jupytext.read(py_file)
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
    return parser.parse_args(argv)


def main(argv: list[str] | None = None, *, default_workflow: str = "nhm") -> int:
    args = parse_args(argv, default_workflow=default_workflow)
    workflows = list(WORKFLOW_INPUT_DIRS) if args.workflow == "all" else [args.workflow]

    for workflow in workflows:
        convert_workflow(
            workflow,
            workspace_root=args.workspace_root,
            dry_run=args.dry_run,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
