import os
from pathlib import Path
import jupytext

# Specify input folders and output folder
input_folders = [Path('./notebook_scripts')]
output_folder = Path('./notebooks')

if not output_folder.exists():
    output_folder.mkdir(exist_ok=True)

for folder in input_folders:
    # Recursively find all .py files in the folder
    for py_file in folder.rglob('*.py'):
        # Compute relative path from input folder root
        # Calculate the relative path based on the input folder's parent
        relative_path = py_file.relative_to(folder)

        # Create corresponding output notebook path by changing suffix to .ipynb
        output_path = output_folder / relative_path.with_suffix('.ipynb')

        print(f'Converting {py_file} -> {output_path}')
        # Read the .py content and convert
        notebook = jupytext.read(py_file)
        jupytext.write(notebook, output_path)
