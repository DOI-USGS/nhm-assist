import argparse
import os
import pathlib as pl
import subprocess
import sys

from pywatershed.utils.utils import timer

repo_dir = pl.Path("../../").resolve()
support_dir = repo_dir / "supporting_notebooks"

all_notebooks = set(repo_dir.glob("*.ipynb"))
support_notebooks = set(support_dir.glob("*.ipynb"))

# Add notebooks here as needed
notebooks_to_not_test = set()
notebooks_to_test = sorted(all_notebooks - notebooks_to_not_test - support_notebooks)


def run_cmd(cmd):
    print(f"Running command: {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=repo_dir)  # , shell=True)
    assert proc.returncode == 0, f"Error running command: {' '.join(cmd)}"


@timer
def run_notebook(nb_name):
    # Since we are stripping the metadata on pre-commit, we have to restore
    # this much (empty) metadata before jupytext execute
    cmd = (
        "jupytext",
        "--update",
        f"{nb_name}",
        "--update-metadata",
        '{"kernelspec": {"display_name": "", "language": "", "name": ""}}',
    )
    run_cmd(cmd)

    cmd = ("jupytext", "--execute", f"{nb_name}")
    run_cmd(cmd)


if __name__ == "__main__":
    failed_list = []
    for nb in notebooks_to_test:
        print(f"Testing notebook: {nb}")
        try:
            run_notebook(nb)
        except AssertionError:
            failed_list += [nb]

    # <<
    if len(failed_list):
        msg = f"The following notebooks failed: {failed_list}"
        raise ValueError(msg)
