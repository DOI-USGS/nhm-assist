import sys
from pathlib import Path

import jupytext


def resolve_folders(base_dir_name=None):
    base_dir = Path(".") if base_dir_name is None else Path(base_dir_name)
    input_folder = base_dir / "notebook_scripts"
    output_folder = base_dir / "notebooks"
    return input_folder, output_folder


def convert_notebooks(input_folder, output_folder):
    output_folder.mkdir(parents=True, exist_ok=True)

    for py_file in input_folder.rglob("*.py"):
        relative_path = py_file.relative_to(input_folder)
        output_path = output_folder / relative_path.with_suffix(".ipynb")

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

    convert_notebooks(input_folder, output_folder)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
