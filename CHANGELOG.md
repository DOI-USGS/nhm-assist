# Changelog

All notable changes to nhm-assist will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

_Changes on the `nhf_dev` branch since the 1.1.0 release._

### Added

- **NHF Assist workflow tree (`nhf_assist/`):** Added a parallel National Hydrofabric (NHF) workflow alongside the existing NHM notebooks, with its own `notebook_scripts/` and a set of `_v2` helper modules (`nhm_assist_utilities_v2.py`, `nhm_hydrofabric_v2.py`, `nhm_output_visualization_v2.py`, `output_plots_v2.py`, `map_template_v2.py`, `sf_data_retrieval_v2.py`, `display_controls_v2.py`, `nhm_helpers_v2.py`, `efc.py`, and a new `nhm_config.py` config module). Includes the core numbered notebooks (`0_workspace_setup` through `6_streamflow_output_visualization_new`) and a work-in-progress `2_model_hydrofabric_visualization_FMI` (Flow Management Index) variant.
- **POI supplemental information notebook:** `Fetch_poi_supplimental_information.py` builds an interactive map of hydrofabric elements and fetches supplemental Point-of-Interest (POI) metadata; the new POI metadata fetch function was also added to the shared helper functions and notebooks.
- **Domain geopackage builders:** `Create_OHM_domain_geopackage.py` and `Create_child_domain_geopackage.py` generate domain polygons (e.g. one per `basin_id`) for parent and child/subdomain hydrofabrics.
- **HUC / gage / parameter utilities:** Added supplemental processing notebooks — `Write_huc_12pp_data_as_netcdf.py`, `get_huc_ids.py`, `gf_params_parse.py`, `make_hydat_gage_resource.py`, `make_param_file.py`, `Oregon_GFv2_parameters.py`, and `HRU_geom_check.py`.
- **PEST++ IES observation & control file workflow:** Added `01_Prepare_observations.py` (builds `allobs.dat` and related observation inputs, replacing `01_Create_allobs_dat.py`), `02_Create_pest_instruction_file.py`, `02b_Create_pest_template_file.py`, and `05_Re-weighting_obs.py` (switches from manual re-weighting to a "phi factor" objective-function approach and prunes localization groups containing only zero-weighted observations).
- **PEST++ IES forward run scripts:** Added `forward_run.py` and `forward_run_revised.py` for the PESTPP-IES forward model run.
- Added `make_notebooks.py` to the PESTPP-IES calibration directory to regenerate notebooks from `.py` scripts.

### Changed

- **Reorganized NHF directory layout:** Renamed the `nhf-assist` directory to `nhf_assist`, moved and reorganized folder paths, and corrected `.gitignore` entries accordingly (including ignoring `claude.md`).
- **Rewrote PEST++ setup notebook:** Substantially reworked `03_set_up_PEST++.py` and updated `04_add_localization_matrix.py`, `00_Subset_NHM_baselines.py`, and `helpers/pest_utils.py`.
- Updated `Observation_standard_deviation.csv` and `localization_groups.csv` ancillary templates, and moved the `pestpp-ies` binary out of the `dependencies/` subdirectory.
- Merged the latest `main` into `nhf_dev` several times to keep the branch current with the 1.1.0 line.

### Fixed

- **Reduced SCA memory usage (PR #63):** Lowered memory consumption in snow-covered-area (SCA) calculations by computing Dask tasks earlier and deleting intermediate variables after use.
- Fixed bugs in the PEST++ IES setup notebooks and several NHF workflow tweaks.
- Removed user-specific `kernelspec` metadata from notebooks for cleaner, reproducible diffs.
- Removed an extraneous file and applied small corrections in `03_set_up_PEST++.py` and the `utilities_v2` / `2_FMI` notebook.

## [1.1.1] — 2026-06-16

### Fixed

- **`IndexError` in `create_poi_df` for non-NWIS gauges (#34):** Notebooks 2 and 3 previously aborted with `IndexError: index 0 is out of bounds for axis 0 with size 0` when a subdomain's parameter file referenced gauges absent from NWIS (e.g., Canadian Water Survey IDs `01AK004`, `02OE018`). `create_poi_df` now guards the metadata lookup with a `len(matches) > 0` check and emits a single user-facing warning at the end of the function listing each affected gauge, the columns it needs, and the path to `<model_dir>/resource_gages.csv` where the user can fill in `poi_agency`, `poi_name`, `latitude`, `longitude`. Notebooks complete; missing-metadata gauges flow into the existing `mask_missing` drop logic as before. Affects users running the Maine and New England v1.1 subdomains.
- **`GEOSException` in `create_OR_sf_df` and `create_ecy_sf_df` (#36):** Notebook 1 aborted with `shapely.errors.GEOSException` for Pacific Northwest subdomains (and any domain extending beyond the HUC2 shapefile coverage, e.g., into Canada) because `huc2_gdf.clip(hru_gdf)` choked on invalid HRU polygons during its internal `unary_union`. A new `_safe_clip_mask()` helper repairs HRU geometries via `shapely.make_valid` before the clip.
- **Silent missing observations on large WaterData batch fetches (#35):** `fetch_daily_discharge_batch` previously swallowed any error from `dataretrieval.waterdata.get_daily` into a `WaterDataBatchResult(error=…)` and silently dropped every site in that batch. Rate-limit responses (HTTP 429, 503) and transient connection drops caused missing observations in `sf_efc.nc` on large subdomain runs — invisible unless the user counted observations. Now retries on `429 / 502 / 503 / 504`, `ConnectionError`, and `Timeout` with exponential backoff (1s, 2s, 4s) up to 3 retries; non-transient errors still return immediately. Additionally, batch submissions are staggered by 250 ms in the `ThreadPoolExecutor.submit` loop so the WaterData edge does not see a 4-wide burst of large multi-site queries all at once. Concurrency unchanged (`max_workers=4`).

## [1.1.0] — 2026-06-01

### Added

- **Water Data Retrieval API integration:** Replaced legacy NWIS direct calls with the USGS Water Data Retrieval API across streamflow data retrieval workflows. Includes support for API Personal Access Tokens (PAT) stored via `.env` for local use and from the home directory on Nebari. Metadata fetch now uses a bounding box (AOI) query rather than state(s) boundaries.
- **PESTPP-IES parameter estimation workflow:** Added PESTPP-IES workflows directory.
- **NHGF modification workflow:** Added nhgf_v2_fabric_modification directory that contains National Hydrofabric HRU modification Upland/Lowland workflow as a notebook.
- **New supporting notebook — Adds POI parameters to parameter file:** Notebook for adding Points of Interest (POIs) parameters to pywatershed parameter file with gage ranking logic. Revamped how the default gages file is created and handled.
- **Nebari/WSL plotting support:** Added helper functions so Plotly plots render correctly across local, WSL, and Nebari environments without duplicating OS-check code in individual notebooks.
- Added `ST-TS` (stream/tidal) to the site type code list in utilities.
- Added `subdomain_config.yaml` to `.gitignore`.
- Added NHM-Assist logo to README.
- Added instructions to README for generating notebooks from `.py` scripts.
- Added docstrings to helper functions.

### Changed

- **Notebooks → Python scripts (CI/CD):** Converted all notebooks to `.py` files tracked via Jupytext; `.ipynb` files added to `.gitignore`. Added `make_notebooks.py` script to regenerate notebooks from scripts. CI reconfigured to execute `.py` scripts instead of `.ipynb` notebooks and now runs only on pull requests.
- **EFC module:** Refactored to use NumPy arrays instead of pandas Series, squashing deprecation warnings and improving efficiency.
- **NWIS fetch:** Switched to bounding-box query from HRU extents and added time lag between requests to handle API rate limiting. Patched to respond to updated NWIS data tags. This change was superseded by Water Data Retrieval API integration.
- **Metadata fetch:** Updated start date and switched to bbox-based AOI query in `utilities.py`.
- Updated `pyPRMS` source to PyPI (previously from a git location).
- Locked `pandas` to `2.2.3` for compatibility.
- Constrained `numpy < 2.3.0`.
- Added `python-dotenv`, `dask`, and `distributed` packages to `environment.yaml`.
- Added `gdptools` support to `environment.yaml`.

### Fixed

- **Stabilized legacy NHM visualization helpers (!29):** Fixed crashes and `NameError` exceptions in `display_controls.py` when notebook widget state was not yet initialized. All module-level state variables are now explicitly initialized to `None`, and a new `_require_state()` guard function emits a user-friendly warning rather than crashing when controls are used before setup. Added `_ensure_output_dirs()` to create output directories on demand.
- **Normalized HRU identifier column names (!29):** `nhm_output_visualization.py` now handles both `nhm_id` and `nhru` as valid HRU dimension and column names via new helper functions `_normalize_hru_id_column()` and `_hru_dim_name()`. Removed forced `nhm_id → nhru` dimension rename that caused `KeyError` with newer pywatershed output. Updated README to note that `nhru` in map outputs corresponds to `nhm_id`.
- Removed stale `states_gdf` reference from `nhm_assist_utilities.py` (!29).
- Fixed column name mismatch (PR #62).
- Fixed values outside valid range in `pref_flow_infil_frac` (Notebook 4).
- Fixed `delete_model_output` function and cleaned up Notebooks 1 and 2.
- Fixed `ecy_df` initialization bug in `sf_data_retrieval.py`.
- Fixed NWIS fetch bounds method for `fetch_nwis_gage_info` (PR #19).
- Fixed bugs in the new POI notebook and default gages file creation/handling.
- Added try/catch error handling for Notebook 6 (PR #48).
- Hotfix for pandas Series referencing warning in `efc.py`.
- Improved Oregon state data fetch performance.

## [1.0.0] — 2025-05-14

This is the initial release of the NHM-Assist notebooks, which are a collection of python workflows presented in Jupyter notebooks for evaluating, running and interpreting National Hydrologic Model (NHM) subdomain models using pywatershed.

### Citation
Haj, A.E., Barker, M.I., Norton, P.A., McCreight, J.L., Ludden, L.L., and Snyder, A.M., 2025, nhm-assist: a collection of python workflows presented in Jupyter notebooks for evaluating, running and interpreting National Hydrologic Model (NHM) subdomain models, version 1.0.0: U.S. Geological Survey software release, https://doi.org/10.5066/P1NMW6US.


[1.1.0]: https://code.usgs.gov/wma/hytest/nhm-assist/-/releases/1.1.0
[1.0.0]: https://code.usgs.gov/wma/hytest/nhm-assist/-/releases/1.0.0
