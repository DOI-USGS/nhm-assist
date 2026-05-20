# Changelog

All notable changes to nhm-assist will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0] — 2025-05-14 through 2026-05-19

### Added

- **Water Data Retrieval API integration:** Replaced legacy NWIS direct calls with the USGS Water Data Retrieval API across streamflow data retrieval workflows. Includes support for API Personal Access Tokens (PAT) stored via `.env` for local use and from the home directory on Nebari. Metadata fetch now uses a bounding box (AOI) query rather than explicit date ranges.
- **PESTPP-IES parameter estimation workflow:** Added Notebook 6 containing PESTPP-IES workflows ported from the nhm-pestpp repository, including supporting button logic in helpers and NHGF modification workflow files.
- **NHGF modification workflow:** Added National Hydrologic Geospatial Framework (NHGF) modification workflow as a new notebook with supporting scripts and folders.
- **New supporting notebook — Add POIs to Parameters:** Notebook for adding Points of Interest (POIs) to NHM parameters with gage ranking logic. Revamped how the default gages file is created and handled.
- **Nebari/WSL plotting support:** Added helper functions so Plotly plots render correctly across local, WSL, and Nebari environments without duplicating OS-check code in individual notebooks.
- Added `ST-TS` (stream/tidal) to the site type code list in utilities.
- Added `subdomain_config.yaml` to `.gitignore`.
- Added NHM-Assist logo to README.
- Added instructions to README for generating notebooks from `.py` scripts.
- Added docstrings to helper functions.

### Changed

- **Notebooks → Python scripts (CI/CD):** Converted all notebooks to `.py` files tracked via Jupytext; `.ipynb` files added to `.gitignore`. Added `make_notebooks.py` script to regenerate notebooks from scripts. CI reconfigured to execute `.py` scripts instead of `.ipynb` notebooks and now runs only on pull requests.
- **EFC module:** Refactored to use NumPy arrays instead of pandas Series, squashing deprecation warnings and improving efficiency.
- **NWIS fetch:** Switched to bounding-box query from HRU extents and added time lag between requests to handle API rate limiting. Patched to respond to updated NWIS data tags.
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
