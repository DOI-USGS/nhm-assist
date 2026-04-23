import argparse
from pathlib import Path

import jupytext


REPO_ROOT = Path(__file__).resolve().parents[1]

WORKFLOW_DIRS = {
    "nhm": {
        "input": REPO_ROOT / "workflow_templates" / "nhm",
        "output": REPO_ROOT / "notebooks",
    },
    "nhf": {
        "input": REPO_ROOT / "workflow_templates" / "nhf",
        "output": REPO_ROOT / "nhf_assist" / "notebooks",
    },
    "pest": {
        "input": REPO_ROOT / "workflow_templates" / "pest",
        "output": REPO_ROOT / "pestpp_ies_calibration" / "notebooks",
    },
}


def convert_workflow(name: str, *, dry_run: bool = False) -> list[Path]:
    config = WORKFLOW_DIRS[name]
    input_folder = config["input"]
    output_folder = config["output"]
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
    return parser.parse_args(argv)


def main(argv: list[str] | None = None, *, default_workflow: str = "nhm") -> int:
    args = parse_args(argv, default_workflow=default_workflow)
    workflows = list(WORKFLOW_DIRS) if args.workflow == "all" else [args.workflow]

    for workflow in workflows:
        convert_workflow(workflow, dry_run=args.dry_run)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
