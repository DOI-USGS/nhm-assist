"""Shared assist utilities for the nhm and nhf workflows.

Unified from src/assist/nhm/nhm_assist_utilities.py and
src/assist/nhf/nhm_assist_utilities_v2.py. See
docs/superpowers/specs/2026-08-30-helper-unification-design.md.
"""
from __future__ import annotations

import os
import pathlib as pl

import yaml

# nhm used the NWIS spelling; nhf renamed to WaterData. Accept both, canonical
# form is the WaterData spelling.
CONFIG_KEY_ALIASES: dict[str, str] = {
    "nwis_gages_file": "waterdata_gages_file",
    "nwis_gage_nobs_min": "waterdata_gage_nobs_min",
}

# All 14 keys both baselines wrapped in pl.Path(). Omitting any of these leaves a
# raw str in the config, and consumers doing `config["out_dir"] / "x.nc"` raise
# TypeError. Verified against both baselines at 27f7144.
_PATH_KEYS = (
    "Folium_maps_dir",
    "model_dir",
    "param_filename",
    "gages_file",
    "default_gages_file",
    "output_netcdf_filename",
    "waterdata_gages_file",
    "resource_gages_file",
    "NHM_dir",
    "out_dir",
    "notebook_output_dir",
    "html_maps_dir",
    "html_plots_dir",
    "nc_files_dir",
)


def load_subdomain_config(root_dir: pl.Path) -> dict:
    """Load `subdomain_config.yaml`, accepting either the NWIS or WaterData schema."""
    config_path = pl.Path(root_dir) / "subdomain_config.yaml"
    if not config_path.exists():
        raise FileNotFoundError(
            "Missing subdomain config at "
            f"{config_path}. Set the active model for the project, then run "
            "0_workspace_setup.ipynb first from the same project notebook "
            "directory before running later notebooks."
        )

    with open(config_path) as handle:
        raw = yaml.load(handle, Loader=yaml.FullLoader)

    # Fold the retired NWIS key names onto their WaterData equivalents.
    for old_key, new_key in CONFIG_KEY_ALIASES.items():
        if old_key in raw and new_key not in raw:
            raw[new_key] = raw.pop(old_key)

    config: dict = dict(raw)
    for key in _PATH_KEYS:
        value = raw.get(key)
        config[key] = pl.Path(value) if value is not None else None

    config.setdefault("resource_gages_file", None)
    return config


def delete_notebook_output_files(
    *,
    notebook_output_dir: pl.Path,
    model_dir: pl.Path,
) -> None:
    """Clear prior notebook output so a rerun starts clean."""
    notebook_output_dir = pl.Path(notebook_output_dir)
    model_dir = pl.Path(model_dir)

    subfolders = ["Folium_maps", "html_maps", "html_plots", "nc_files"]
    deleted_by_subfolder: dict[str, int] = {}
    for subfolder in subfolders:
        folder_path = notebook_output_dir / subfolder
        if not folder_path.exists():
            continue
        count = 0
        for file_name in os.listdir(folder_path):
            file_path = folder_path / file_name
            if file_path.is_file():
                os.remove(file_path)
                count += 1
        if count:
            deleted_by_subfolder[subfolder] = count

    deleted_model_files = 0
    files = [
        "default_gages.csv",
        "append_gages_to_param_file.csv",
        "default_gages_file.csv",
        "NWISgages.csv",
    ]
    for file_name in files:
        target = model_dir / file_name
        if target.exists():
            os.remove(target)
            deleted_model_files += 1

    metadata_files = ["WaterDataGages.csv"]
    for file_name in metadata_files:
        target = model_dir / "metadata" / file_name
        if target.exists():
            os.remove(target)
            deleted_model_files += 1

    total = sum(deleted_by_subfolder.values()) + deleted_model_files
    if total == 0:
        print("No prior notebook output files to delete.")
    else:
        print(f"Deleted {total} prior notebook output file(s).")
