"""Batch runner: generate streamflow visualization maps and plots for all child models.

This script runs the workspace setup and then generates:
1. A streamflow map (KGE-colored gage markers) for each child model
2. Streamflow plots (simulated vs observed) for every gage in each child model

Usage
-----
    pixi run python nhf_assist/run_streamflow_visualization.py

Or edit the `child_models` list below and run interactively.
"""

import subprocess
import sys
import os
import pathlib as pl
import time
import re
import warnings

warnings.filterwarnings("ignore")

# Suppress browser popups — maps/plots are saved as HTML but not displayed
os.environ["NHM_BATCH_MODE"] = "1"

# === CONFIGURATION ===
# List of child model subdomain names (folder names in domain_data/)
child_models = [
    'DeschutesRiver',
    'GooseSummerLakes',
    'GrandeRonde',
    'HoodRiver',
    'JohnDayRiver',
    'KlamathRiver',
    'LowerWillamette',
    'MalheurLake',
    'MalheurRiver',
    'MidCoastB_LowerUmpqua_SouthCoastA',
    'MiddleWillamette',
    'NorthCoast_MidCoastA',
    'OwyheeRiver',
    'PowderRiver',
    'SandyRiver',
    'SouthCoastB_LowerRogue',
    'UmatillaRiver',
    'UpperRogue',
    'UpperUmpqua',
    'UpperWillamette',
]

# Workflow script for workspace setup
SETUP_SCRIPT = "src/workflow_templates/nhf/0_workspace_setup.py"

# Root directory (auto-detect from this script's location)
root_dir = pl.Path(__file__).resolve().parent.parent

# Path to the workspace setup .py file (where subdomain is defined)
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
        print(f"  [WARNING] Could not find subdomain line to replace in {setup_py.name}")
        return False

    setup_py.write_text(new_content, encoding="utf-8")
    return True


def run_setup(timeout: int = 120):
    """Run the workspace setup script to write subdomain_config.yaml."""
    cmd = [sys.executable, str(setup_py)]
    env = {**os.environ, "NHM_BATCH_MODE": "1"}

    result = subprocess.run(
        cmd,
        cwd=str(root_dir / "nhf_assist"),
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )
    return result.returncode == 0


def generate_streamflow_outputs(model_name: str):
    """Generate streamflow map and plots for all gages in a single model."""
    from assist.nhf.output_plots_v2 import create_streamflow_plot
    from assist.nhf.nhm_hydrofabric_v2 import make_hf_map_elements
    from assist.nhf.map_template_v2 import make_streamflow_map
    from assist.nhf.nhm_output_visualization_v2 import retrieve_hru_output_info
    from assist.nhf.nhm_assist_utilities_v2 import load_subdomain_config

    # Reload config for this model
    nhf_root = root_dir / "nhf_assist"
    config = load_subdomain_config(nhf_root)

    # Load hydrofabric elements
    (
        hru_gdf,
        hru_txt,
        seg_gdf,
        seg_txt,
        waterdata_gages_aoi,
        poi_df,
        gages_df,
        gages_txt,
        gages_txt_nb2,
    ) = make_hf_map_elements(
        root_dir=nhf_root,
        model_dir=config["model_dir"],
        GIS_format=config["GIS_format"],
        param_filename=config["param_filename"],
        control_file_name=config["control_file_name"],
        waterdata_gages_file=config["waterdata_gages_file"],
        gages_file=config["gages_file"],
        resource_gages_file=config["resource_gages_file"],
        default_gages_file=config["default_gages_file"],
        nhru_params=config["nhru_params"],
        nhru_nmonths_params=config["nhru_nmonths_params"],
        waterdata_gage_nobs_min=config["waterdata_gage_nobs_min"],
    )

    # Get output variable info
    plot_start_date, plot_end_date, year_list, output_var_list = retrieve_hru_output_info(
        out_dir=config["out_dir"],
        water_years=config["water_years"],
    )

    # --- Generate the streamflow map (KGE-colored gage markers) ---
    print(f"    Generating streamflow map...")
    try:
        make_streamflow_map(
            root_dir=nhf_root,
            out_dir=config["out_dir"],
            plot_start_date=plot_start_date,
            plot_end_date=plot_end_date,
            water_years=config["water_years"],
            hru_gdf=hru_gdf,
            poi_df=poi_df,
            poi_gage_id_sel=None,
            seg_gdf=seg_gdf,
            html_maps_dir=config["html_maps_dir"],
            subdomain=config["subdomain"],
            output_netcdf_filename=config["output_netcdf_filename"],
        )
        print(f"      [OK] Streamflow map")
    except Exception as e:
        print(f"      [FAILED] Streamflow map: {e}")

    # --- Generate streamflow plots for all gages ---
    gage_list = poi_df["poi_gage_id"].tolist()
    print(f"    Generating streamflow plots for {len(gage_list)} gages...")

    for gage_id in gage_list:
        try:
            create_streamflow_plot(
                poi_gage_id_sel=gage_id,
                plot_start_date=plot_start_date,
                plot_end_date=plot_end_date,
                water_years=config["water_years"],
                html_plots_dir=config["html_plots_dir"],
                output_netcdf_filename=config["output_netcdf_filename"],
                out_dir=config["out_dir"],
                subdomain=config["subdomain"],
            )
            print(f"      [OK] {gage_id}")
        except Exception as e:
            print(f"      [FAILED] {gage_id}: {e}")

    return True


def main():
    print("=" * 70)
    print("NHF-Assist Batch Streamflow Visualization Runner")
    print("=" * 70)
    print(f"Root directory: {root_dir}")
    print(f"Child models: {len(child_models)}")
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

        # Run workspace setup
        print(f"  Running workspace setup...")
        start = time.time()
        if not run_setup():
            print(f"  [FAILED] Workspace setup failed")
            results[model_name] = "FAILED at 0_workspace_setup.py"
            continue
        print(f"  [OK] Setup ({time.time() - start:.1f}s)")

        # Generate streamflow outputs
        start = time.time()
        try:
            success = generate_streamflow_outputs(model_name)
            elapsed = time.time() - start
            if success:
                results[model_name] = f"SUCCESS ({elapsed:.1f}s)"
                print(f"  Streamflow outputs generated for {model_name} ({elapsed:.1f}s)")
            else:
                results[model_name] = "FAILED"
        except Exception as e:
            elapsed = time.time() - start
            results[model_name] = f"FAILED ({elapsed:.1f}s): {e}"
            print(f"  [FAILED] ({elapsed:.1f}s): {e}")

    # Summary
    print(f"\n{'=' * 70}")
    print("SUMMARY")
    print(f"{'=' * 70}")
    for model_name, status in results.items():
        print(f"  {model_name:<35} {status}")

    # Reset subdomain to placeholder after batch run
    set_subdomain_in_setup("Put your subbasin model name here")
    print(f"\n  Reset subdomain in {setup_py.name} to placeholder.")


if __name__ == "__main__":
    main()
