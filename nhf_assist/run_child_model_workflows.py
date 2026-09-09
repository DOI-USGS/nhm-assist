"""Batch runner: execute NHF-Assist workflows 0, 1, 2 for a list of child models.

This script runs the workspace setup, streamflow observation creation, and
hydrofabric visualization workflows in sequence for each child model listed
in `child_models`. Each workflow .py file is executed directly with Python,
which is faster than running notebooks via nbconvert (no Jupyter kernel overhead).

The key mechanism: for each child model, the script temporarily updates the
`subdomain` variable in the workspace setup script, executes it (which writes
subdomain_config.yaml), then executes workflows 1 and 2 (which read the config).

Usage
-----
    pixi run python nhf_assist/run_child_model_workflows.py

Or edit the `child_models` list below and run interactively.
"""

import subprocess
import sys
import os
import pathlib as pl
import shutil
import time
import re

# === CONFIGURATION ===
# List of child model subdomain names (folder names in domain_data/)
child_models = [
    'CrookedRiver',
    'DeschutesRiver',
    # 'GooseSummerLakes',
    # 'GrandeRonde',
    # 'HoodRiver',
    # 'JohnDayRiver',
    # 'KlamathRiver',
    # 'LowerWillamette',
    # 'MalheurLake',
    # 'MalheurRiver',
    # 'MidCoastB_LowerUmpqua_SouthCoastA',
    # 'MiddleWillamette',
    # 'NorthCoast_MidCoastA',
    # 'OwyheeRiver',
    # 'PowderRiver',
    # 'SandyRiver',
    # 'SouthCoastB_LowerRogue',
    # 'UmatillaRiver',
    # 'UpperRogue',
    # 'UpperUmpqua',
    # 'UpperWillamette',
]


# Workflow .py scripts to execute in order
workflows = [
    "src/workflow_templates/nhf/0_workspace_setup.py",
    "src/workflow_templates/nhf/1_create_streamflow_observations.py",
    "src/workflow_templates/nhf/Create_gridmet_climate_drivers.py",
    "src/workflow_templates/nhf/2_model_hydrofabric_visualization_FMI.py",
]

# Root directory (auto-detect from this script's location)
root_dir = pl.Path(__file__).resolve().parent.parent

# Path to the workspace setup .py file (where subdomain is defined)
setup_py = root_dir / workflows[0]


def set_subdomain_in_setup(subdomain_name: str):
    """Update the subdomain variable in 0_workspace_setup.py."""
    content = setup_py.read_text(encoding="utf-8")

    new_content = re.sub(
        r'^subdomain = ".*?"',
        f'subdomain = "{subdomain_name}"',
        content,
        count=1,
        flags=re.MULTILINE,
    )

    if new_content == content:
        print(f"  [WARNING] Could not find subdomain line to replace in {setup_py.name}")
        return False

    setup_py.write_text(new_content, encoding="utf-8")
    return True


def execute_workflow(workflow_path: str, timeout: int = 1800):
    """Execute a .py workflow script directly with Python."""
    full_path = root_dir / workflow_path

    if not full_path.exists():
        print(f"  [ERROR] Script not found: {full_path}")
        return False

    cmd = [sys.executable, str(full_path)]
    env = {**os.environ, "NHM_BATCH_MODE": "1"}

    print(f"  Running: {pl.Path(workflow_path).name}")
    start = time.time()

    result = subprocess.run(
        cmd,
        cwd=str(root_dir / "nhf_assist"),
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )

    elapsed = time.time() - start

    if result.returncode != 0:
        print(f"  [FAILED] ({elapsed:.1f}s)")
        # Show last few lines of stderr/stdout for debugging
        error_output = result.stderr.strip() or result.stdout.strip()
        if error_output:
            lines = error_output.splitlines()[-10:]
            for line in lines:
                print(f"    {line}")
        return False
    else:
        print(f"  [OK] ({elapsed:.1f}s)")
        return True


def main():
    print("=" * 70)
    print("NHF-Assist Batch Workflow Runner")
    print("=" * 70)
    print(f"Root directory: {root_dir}")
    print(f"Child models: {child_models}")
    print(f"Workflows: {[pl.Path(w).name for w in workflows]}")
    print()

    results = {}

    for model_name in child_models:
        print(f"\n{'─' * 70}")
        print(f"Processing: {model_name}")
        print(f"{'─' * 70}")

        # Check that the domain folder exists
        domain_dir = root_dir / "nhf_assist" / "domain_data" / model_name
        if not domain_dir.exists():
            domain_dir = root_dir / "domain_data" / model_name
            if not domain_dir.exists():
                print(f"  [SKIP] Domain folder not found: {model_name}")
                results[model_name] = "SKIPPED - folder not found"
                continue

        # Update subdomain in workflow 0
        print(f"  Setting subdomain = '{model_name}'")
        if not set_subdomain_in_setup(model_name):
            results[model_name] = "FAILED - could not set subdomain"
            continue

        # Execute each workflow in order
        all_passed = True
        for workflow in workflows:
            success = execute_workflow(workflow)
            if not success:
                all_passed = False
                results[model_name] = f"FAILED at {pl.Path(workflow).name}"
                break

        if all_passed:
            results[model_name] = "SUCCESS"
            print(f"  All workflows completed for {model_name}")

    # Summary
    print(f"\n{'=' * 70}")
    print("SUMMARY")
    print(f"{'=' * 70}")
    for model_name, status in results.items():
        print(f"  {model_name:<30} {status}")

    # Reset subdomain to placeholder after batch run
    set_subdomain_in_setup("Put your subbasin model name here")
    print(f"\n  Reset subdomain in {setup_py.name} to placeholder.")


if __name__ == "__main__":
    main()
