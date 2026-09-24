# Changelog

All notable changes to nhm-assist will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

_Changes since the 1.1.1 release: the pixi workspace restructure, the NHF and PEST++ IES workflows, and one shared codebase for NHM and NHF. Merge request numbers point to the details._

### Upgrading

- **pixi is the only install path.** The legacy `mamba env create -f environment.yaml` flow remains available at the [`1.1.1` release](https://code.usgs.gov/wma/hytest/nhm-assist/-/releases/1.1.1).
- **Existing checkouts must rebuild their environment** and point their notebooks at `.pixi/envs/default`. Follow the [upgrade steps in !56](https://code.usgs.gov/wma/hytest/nhm-assist/-/merge_requests/56#note_1115829).
- **Update imports in your own notebooks and scripts.** Shared helpers now live in `assist.common` (for example `assist.common.map_template`, formerly `assist.nhm.map_template` or `assist.nhf.map_template_v2`). The old `assist.nhm.*` and `assist.nhf.*_v2` modules have been removed.
- **Regenerating a project's notebooks keeps their cells,** so existing notebooks do not pick up template changes. Create a new project to get the updated notebooks.

### Added

- **Workspaces and a guided setup menu (!31, !32):** `pixi run setup` creates a workspace outside the repository, holding projects, models and one active model per project. Models, generated notebooks and outputs no longer live in the repository.
- **NHF workflow (!27, !34):** National Hydrofabric (GFv2) notebooks alongside the NHM ones, under `src/workflow_templates/nhf/`. These include domain geopackage builders for parent and child domains, parameter builders from GFv1.1 and GFv2 sources, POI supplemental information, HUC and HYDAT utilities, a gridMET climate driver template, a Flow Management Index variant of notebook 2, and batch runners in `nhf_assist/` for running workflows across many child models.
- **PEST++ IES calibration workflow (!35):** notebooks `00` through `05` under `src/workflow_templates/pest/`, with GFv2 variants. Observation preparation replaces `01_Create_allobs_dat`, re-weighting uses a phi-factor objective function, and localization groups with only zero-weighted observations are pruned. Helpers live in `src/assist/pest/`.
- **BOR Hydromet streamflow:** notebooks 1 and 2 can include Bureau of Reclamation Hydromet gages, with a BOR gage scraper and map.
- **Contributor dev mode (!46, !55):** `pixi run dev-mode` generates a project's notebooks paired back to the repository templates, so saving a notebook edits the template.
- **Repair editor settings (!55):** a setup-menu action that brings an existing project's editor settings up to date.
- **`dev-future` environment (!47):** tracks the next major versions of `pywatershed` and `dataretrieval`.
- **Environment sanity check (!54):** the first cell of `0_workspace_setup` warns when packages installed outside the environment override it.
- Module-level map pop-ups, and `scripts/count_domain_hrus.py` to tabulate HRU counts per domain.
- `AGENTS.md` with operating notes for AI coding agents, and design specs and plans under `docs/design/` (!45, !54).

### Changed

- **One shared codebase for NHM and NHF (!49, !50, !51, !52, !53):** helper modules that existed as separate nhm and nhf copies now live once in `assist.common`, and the numbered workflow notebooks (`0` through `6` and `add_pois_to_parameters`) are one template set in `src/workflow_templates/common/`.
- **WaterData is the canonical streamflow source (!50).** Configs using the retired `nwis_*` names still load. GFv1.1-only map layers are hidden automatically for GFv2 models.
- **Environments (!47, !54):** `default` carries the analysis stack plus the test and lint tools, and is the one environment users and contributors need. `ci` and `dev-future` exist alongside it.
- **`pywatershed` is installed from PyPI (!56),** which drops a documentation and lint toolchain the conda-forge package pulled in. Python is pinned to 3.11.
- **Packaging (!40, !42):** the build backend is `hatchling`, and `[project.dependencies]` declares the full runtime contract.
- **Notebooks and editors (!46, !54, !55):** nhm-assist no longer registers Jupyter kernels, so choose `.pixi/envs/default` in your editor. No task launches Jupyter, and generated projects sync notebooks when opened.
- **`check_par_bounds` is stricter (!57):** it stops with an error when bounds are missing or invalid, and checks that each lower bound is below its upper bound.
- **README** reorganized with sections for users first and developers second (!55).

### Fixed

- **`pyproj` behind the USGS VPN (#33, !47, !54):** the `default` environment ships PROJ datum grids, so no per-machine setup is needed.
- **User site-packages overriding the environment (!54):** anything run through pixi now ignores packages from `pip install --user`.
- **Parameter-file gages are no longer dropped** by the 1000 m distance filter (#46).
- **Broken PEST++ IES imports (!57):** restored `pest_utils`, which had been overwritten by a re-export shim.
- **Notebook breaks found by executing every nhm notebook (!51, !53),** including several `KeyError`s and a latent `NameError` in `Fetch_poi_supplimental_information`.
- **Stale template headers (!55)** that could make a notebook save overwrite a template.
- **Reduced SCA memory usage (PR #63):** snow-covered-area calculations compute Dask tasks earlier and free intermediate variables.
- NaN-coordinate gages no longer crash NHF POI marker maps (!31), and NHF triangle markers are restored.
- **Tests (!45, !54, !55):** CI previously ran zero tests; the suite now collects every test, and file reads decode as UTF-8 on Windows.

### Removed

- `environment.yaml` and the mamba install flow (!45).
- The `dev` pixi environment; use `default` (!54).
- The `nhm-assist` and `nhm-assist-dev` Jupyter kernels. Remove previously registered copies as described in the README's _Upgrading from an older checkout_ section (!54).
- The `nhm_helpers/` and `nhf_assist/helpers/` folders (!31), and the `assist.nhm.*` and `assist.nhf.*_v2` modules, now in `assist.common`.

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


[Unreleased]: https://code.usgs.gov/wma/hytest/nhm-assist/-/compare/1.1.1...main
[1.1.1]: https://code.usgs.gov/wma/hytest/nhm-assist/-/releases/1.1.1
[1.1.0]: https://code.usgs.gov/wma/hytest/nhm-assist/-/releases/1.1.0
[1.0.0]: https://code.usgs.gov/wma/hytest/nhm-assist/-/releases/1.0.0
