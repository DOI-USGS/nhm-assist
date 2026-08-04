"""Batch runner: Generate gridMET climate drivers for all child models.

For each child model, updates the `subdomain` variable in the workspace setup,
then executes the gridMET climate drivers script.

Usage
-----
    pixi run python nhf_assist/run_gridmet_drivers.py

Or from the repo root:
    python nhf_assist/run_gridmet_drivers.py
"""

import subprocess
import sys
import pathlib as pl
import time
import re

# === CONFIGURATION ===
child_models = [
    "MiddleWillamette",
    "NorthCoast_MidCoastA",
    "OwyheeRiver",
    "PowderRiver",
    "SandyRiver",
    "SouthCoastB_LowerRogue",
    "UmatillaRiver",
    "UpperRogue",
    "UpperUmpqua",
    "UpperWillamette",
]

# Workflow scripts
SETUP_SCRIPT = "src/workflow_templates/nhf/0_workspace_setup.py"
GRIDMET_SCRIPT = "src/workflow_templates/nhf/Create_gridmet_climate_drivers_gdptools.py"

# Root directory
root_dir = pl.Path(__file__).resolve().parent.parent

# Path to workspace setup (where subdomain is defined)
setup_py = root_dir / SETUP_SCRIPT


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
        print(f"  [WARNING] Could not find subdomain line to replace")
        return False
    setup_py.write_text(new_content, encoding="utf-8")
    return True


def execute_workflow(workflow_path: str, timeout: int = 7200):
    """Execute a .py workflow script directly with Python."""
    full_path = root_dir / workflow_path
    if not full_path.exists():
        print(f"  [ERROR] Script not found: {full_path}")
        return False

    cmd = [sys.executable, str(full_path)]
    print(f"  Running: {pl.Path(workflow_path).name}")
    start = time.time()

    result = subprocess.run(
        cmd,
        cwd=str(root_dir / "nhf_assist"),
        capture_output=True,
        text=True,
        timeout=timeout,
    )

    elapsed = time.time() - start
    if result.returncode != 0:
        print(f"  [FAILED] ({elapsed:.1f}s)")
        error_output = result.stderr.strip() or result.stdout.strip()
        if error_output:
            lines = error_output.splitlines()[-15:]
            for line in lines:
                print(f"    {line}")
        return False
    else:
        print(f"  [OK] ({elapsed:.1f}s)")
        return True


def main():
    print("=" * 70)
    print("NHF-Assist GridMET Climate Drivers Runner")
    print("=" * 70)
    print(f"Root directory: {root_dir}")
    print(f"Child models: {child_models}")
    print()

    results = {}

    for model_name in child_models:
        print(f"\n{'─' * 70}")
        print(f"Processing: {model_name}")
        print(f"{'─' * 70}")

        # Set subdomain in workspace setup
        print(f"  Setting subdomain = '{model_name}'")
        if not set_subdomain_in_setup(model_name):
            results[model_name] = "FAILED - could not set subdomain"
            continue

        # Run workspace setup (generates config)
        success = execute_workflow(SETUP_SCRIPT)
        if not success:
            results[model_name] = "FAILED at workspace setup"
            continue

        # Run gridMET drivers
        success = execute_workflow(GRIDMET_SCRIPT)
        results[model_name] = "SUCCESS" if success else "FAILED at gridMET"

    # Summary
    print(f"\n{'=' * 70}")
    print("SUMMARY")
    print(f"{'=' * 70}")
    for model_name, status in results.items():
        symbol = "+" if status == "SUCCESS" else "-"
        print(f"  {symbol} {model_name:<35} {status}")


if __name__ == "__main__":
    main()
