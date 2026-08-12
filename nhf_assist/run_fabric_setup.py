"""Batch runner: Create child domain geopackages and parse parameters for all child models.

This script:
1. Runs Create_child_domain_geopackage.py ONCE (it loops over all basin_ids internally)
2. Runs gf_params_parse.py for EACH child model (it only processes one at a time)

Usage
-----
    pixi run python nhf_assist/run_fabric_setup.py

Or from the repo root:
    python nhf_assist/run_fabric_setup.py
"""

import subprocess
import sys
import pathlib as pl
import time
import re

# === CONFIGURATION ===
# List of child model names (must match basin_id values and folder names in hydrofabric_domain_data/)
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
    # Add more child models here
]

# Workflow scripts
CREATE_GPKG_SCRIPT = "src/workflow_templates/nhf/Create_child_domain_geopackage.py"
PARAMS_PARSE_SCRIPT = "src/workflow_templates/nhf/gf_params_parse.py"

# Root directory (auto-detect from this script's location)
root_dir = pl.Path(__file__).resolve().parent.parent

# Path to gf_params_parse.py (where child_name is defined)
params_parse_py = root_dir / PARAMS_PARSE_SCRIPT


def set_child_name_in_params_parse(child_name: str):
    """Update the child_name variable in gf_params_parse.py."""
    content = params_parse_py.read_text(encoding="utf-8")

    new_content = re.sub(
        r'^child_name = ".*?"',
        f'child_name = "{child_name}"',
        content,
        count=1,
        flags=re.MULTILINE,
    )

    if new_content == content:
        print(f"  [WARNING] Could not find child_name line to replace in {params_parse_py.name}")
        return False

    params_parse_py.write_text(new_content, encoding="utf-8")
    return True


def execute_workflow(workflow_path: str, timeout: int = 3600):
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
    print("NHF-Assist Fabric Setup Runner")
    print("=" * 70)
    print(f"Root directory: {root_dir}")
    print(f"Child models: {child_models}")
    print()

    # --- Step 1: Create all geopackages (runs once, loops internally) ---
    print(f"\n{'─' * 70}")
    print("Step 1: Create child domain geopackages (all basins)")
    print(f"{'─' * 70}")

    gpkg_success = execute_workflow(CREATE_GPKG_SCRIPT)
    if not gpkg_success:
        print("\n[STOPPING] Geopackage creation failed.")
        return

    # --- Step 2: Parse parameters for each child model ---
    print(f"\n{'─' * 70}")
    print("Step 2: Parse parameters for each child model")
    print(f"{'─' * 70}")

    results = {}

    for model_name in child_models:
        print(f"\n  --- {model_name} ---")

        # Check that the hydrofabric domain folder exists
        hf_dir = root_dir / "nhf_assist" / "hydrofabric_domain_data" / model_name
        if not hf_dir.exists():
            hf_dir = root_dir / "hydrofabric_domain_data" / model_name
        if not hf_dir.exists():
            print(f"  [SKIP] Hydrofabric folder not found: {model_name}")
            results[model_name] = "SKIPPED - folder not found"
            continue

        # Update child_name in gf_params_parse.py
        if not set_child_name_in_params_parse(model_name):
            results[model_name] = "FAILED - could not set child_name"
            continue

        # Execute params parse
        success = execute_workflow(PARAMS_PARSE_SCRIPT)
        results[model_name] = "SUCCESS" if success else "FAILED"

    # Summary
    print(f"\n{'=' * 70}")
    print("SUMMARY")
    print(f"{'=' * 70}")
    print(f"\n  Geopackage creation: {'SUCCESS' if gpkg_success else 'FAILED'}")
    print(f"\n  Parameter parsing:")
    for model_name, status in results.items():
        symbol = "+" if status == "SUCCESS" else "-"
        print(f"    {symbol} {model_name:<35} {status}")


if __name__ == "__main__":
    main()
