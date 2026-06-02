from datetime import datetime
import sys
from pathlib import Path

import jupytext


def resolve_folders(base_dir_name=None):
    base_dir = Path(".") if base_dir_name is None else Path(base_dir_name)
    input_folder = base_dir / "notebook_scripts"
    output_folder = base_dir / "notebooks"
    return input_folder, output_folder


def build_conversion_plan(input_folder, output_folder):
    conversion_plan = []
    for py_file in input_folder.rglob("*.py"):
        relative_path = py_file.relative_to(input_folder)
        output_path = output_folder / relative_path.with_suffix(".ipynb")
        conversion_plan.append((py_file, output_path))

    return conversion_plan


def find_existing_outputs(conversion_plan):
    return [output_path for _, output_path in conversion_plan if output_path.exists()]


def prompt_conflict_action():
    while True:
        choice = input("Archive existing notebooks? [Y/N] ").strip().upper()
        if choice in {"Y", "N"}:
            return choice


def archive_notebook(output_folder, output_path, timestamp):
    relative_path = output_path.relative_to(output_folder)
    archive_dir = output_folder / "archive" / relative_path.parent
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_path = archive_dir / f"{output_path.stem}_{timestamp}{output_path.suffix}"
    output_path.rename(archive_path)


def handle_existing_outputs(output_folder, existing_outputs):
    if not existing_outputs:
        return

    action = prompt_conflict_action()
    if action == "Y":
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        for output_path in existing_outputs:
            archive_notebook(output_folder, output_path, timestamp)
        return

    for output_path in existing_outputs:
        output_path.unlink()


def convert_notebooks(conversion_plan, output_folder):
    output_folder.mkdir(parents=True, exist_ok=True)

    for py_file, output_path in conversion_plan:
        print(f"Converting {py_file} -> {output_path}")
        notebook = jupytext.read(py_file)
        jupytext.write(notebook, output_path)


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) > 1:
        sys.stderr.write("Usage: python make_notebooks.py [base_directory]\n")
        return 2

    base_dir_name = args[0] if args else None
    input_folder, output_folder = resolve_folders(base_dir_name)

    if not input_folder.exists():
        sys.stderr.write(f"Input folder does not exist: {input_folder}\n")
        return 1

    conversion_plan = build_conversion_plan(input_folder, output_folder)
    existing_outputs = find_existing_outputs(conversion_plan)
    handle_existing_outputs(output_folder, existing_outputs)
    convert_notebooks(conversion_plan, output_folder)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
