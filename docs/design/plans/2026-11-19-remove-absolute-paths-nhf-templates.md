# Remove absolute paths from the `nhf` workflow templates

Status: draft, not started. Follow-up to the absolute-path sweep of 2026-11-19.

## Problem

Workflow templates must not carry a contributor's absolute paths. The pest
templates and the Hovenweep and local run scripts were cleaned on 2026-11-19
(see "Already done" below). The templates under `src/workflow_templates/nhf/`
were left for this plan: about 110 absolute paths in 33 files.

Most of these are the OHM (Oregon) fabric-build notebooks. Many have no project
config to derive a path from, so each one needs a decision, not a mechanical
replacement.

## Already done (2026-11-19)

- `assist.common.user_paths` adds `USER_PATH_PLACEHOLDER` (`<USER_PATH_HERE>`),
  `require_user_path` and `require_user_value`. A template sets a user path to
  the placeholder, follows it with a `# e.g.` comment, and calls
  `require_user_path` before using it. The notebook then stops with a message
  naming the setting to edit.
- Paths that can come from the project config use it: for example
  `config["model_dir"] / "pestpp_ies"` in `hovenweep_pest_setup` and
  `scripts/local/local_pest_setup.py`.
- The repo root comes from the installed `assist` package
  (`pl.Path(assist.__file__).resolve().parents[2]`).

## Inventory

Counts are absolute-path occurrences, from a regex sweep of the `.py`
templates. Re-run the sweep before starting; the files may have changed.

### By root

| Occurrences | Root | Kind |
|---:|---|---|
| 33 | `D:\nhm-workspace\Oregon_Recharge\fabrics\...` | OHM fabric build folder |
| 20 | `D:\nhm-assist\nhf_assist\hydrofabric_domain_data\...` | Old fabric location inside the repo |
| 16 | `D:\nhm-workspace\...` (GF2v2_conus, models) | Workspace projects and models |
| 7 | `D:\version1_1_params\...` | NHM v1.1 parameter database |
| 6 | `D:\BANKFULL_CONUS\...` | External dataset |
| 6 | `D:\nhm-assist\data_dependencies\NHM_v1_1\...` | Repo `data_dependencies` |
| 6 | `D:\test_hw_calibration_results\...` | Calibration run output |
| 5 | `D:\nhm-assist\data_dependencies\20240524_v1.1_gm_precal_williamette_river` | Repo `data_dependencies` |
| 5 | `D:\reference_flowline.gpkg` | External dataset |
| 4 | `D:\nhm-assist\nhf_assist\data_dependencies`, `data_dependencies\nhm_v1.1_workflows-master`, `hrrr_data` | Repo `data_dependencies` |
| 3 | `d:\nhm-assist\.agents\tasks\...` | Agent scratch output, in markdown text |
| 1 | `C:\users\ahaj\nhm-assist\...` | A user's home folder |
| 1 | `D:\ERA5_data` | Downloaded data |

### By file

| File | Paths point at |
|---|---|
| `01_OHM_starting_params.py` | OHM fabric `param_source_files_2026_10_23` |
| `02_OHM_hru_identity_params.py` | OHM fabric folder, `GIS\model_layers.gpkg` |
| `03_OHM_segment_parameters.py` | OHM fabric, `BANKFULL_CONUS`, `reference_flowline.gpkg`, repo `main_waterbodies.shp` |
| `04_OHM_tmax_allstar_params.py` | OHM fabric, ERA5 folder, repo `land_sea_mask_upk.nc` |
| `05_OHM_solar_rad_params.py` | OHM fabric, gridMET drivers, repo v1.1 parameter database and Willamette model |
| `06_OHM_smidex_exp_param.py` | OHM fabric, gridMET drivers |
| `07_OHM_default_params.py` | OHM fabric, repo v1.1 parameter database |
| `Create_subbasin_model_NHM_v1.py`, `Create_subbasin_model_NHM_v2.py`, `gf_params_parse_v1_1.py` | `D:\nhm-workspace\GF2v2_conus` |
| `HRU_geom_check.py` | `C:\users\ahaj\...` |
| `Make_NHM_params_from_v1_1.py`, `Make_NHM_params_from_v1_1_seg.py`, `Make_hru_deplcrv_from_v1_1.py` | Old repo fabric folder, `D:\version1_1_params` |
| `OHM_CHILD_temp_cbh_adj_params.py`, `create_tmax_tmin_cbh_adj_params.py` | SandyRiver model, calibration run output, `.agents\tasks` notes |
| `create_dprst_params.py`, `create_snow_params.py`, `param_updates_Rich.py` | Old repo fabric folder, `params_from_Rich_7_25_26` |
| `create_segment_parameters.py` | OHM fabric, `BANKFULL_CONUS`, `reference_flowline.gpkg`, repo `main_waterbodies.shp` |
| `create_smidx_exp_param.py`, `create_tmax_allstar_params.py` | FlamingGorge model and fabric, ERA5, repo `data_dependencies` |
| `create_solar_rad_params.py` | Repo v1.1 parameter database and Willamette model, OHM fabric |
| `gfv2r2_*_params.py` (6 files) | `GF2v2_conus\fabrics\gf2v2_conus\param_source_files`, `BANKFULL_CONUS`, `reference_flowline.gpkg` |

## Proposed approach, by kind of path

1. **Repo `data_dependencies`** (`D:\nhm-assist\data_dependencies\...`,
   `nhf_assist\data_dependencies\...`): derive from the repo root found through
   the installed `assist` package. No user input needed.
2. **Workspace projects, models and fabrics**: derive from
   `NHM_ASSIST_WORKSPACE_ROOT`, or from the project config where the notebook
   runs inside a project. Needs a decision on how a fabric folder is chosen,
   because fabric notebooks may run before a model exists (open question 1).
3. **External datasets** (`BANKFULL_CONUS`, `reference_flowline.gpkg`,
   `version1_1_params`, ERA5): `<USER_PATH_HERE>` with a `# e.g.` comment and
   `require_user_path`, unless they are moved under `data_dependencies`
   (open question 2).
4. **Run output and agent notes** (`test_hw_calibration_results`,
   `.agents\tasks`): these sit in markdown text describing an investigation.
   Rewrite them as relative descriptions, or move the notes to a design doc.
5. **Old fabric location** (`nhf_assist\hydrofabric_domain_data\OHM_2026_02_21`):
   check whether these notebooks are still used. They may be superseded by the
   numbered `0N_OHM_*` notebooks (open question 3).
6. **Dated folder names** (`param_source_files_2026_10_23`,
   `params_from_Rich_7_25_26`): make the date or version a single setting at the
   top of the notebook, not part of each path.

## Open questions

1. How should a fabric notebook find its fabric folder: a setting naming the
   fabric under `<workspace>/<project>/fabrics/`, or a full user path?
2. Should the external datasets (`BANKFULL_CONUS`, `reference_flowline.gpkg`,
   the v1.1 parameter database) live under `data_dependencies` with a download
   step, so they can be derived instead of entered?
3. Which `nhf` templates are still in use? The `Make_*`, `create_*` and
   `param_updates_Rich` notebooks may be retired in favor of `0N_OHM_*`. If so,
   delete them instead of fixing them.
4. Are the `OHM_*` notebooks meant to be general, or OHM-only? An OHM-only
   notebook could keep OHM-specific defaults as long as they are not absolute.

## Check that proves it done

A sweep of `src/workflow_templates/` and `scripts/` finds no drive-letter,
`/home/<user>` or `C:\users\<user>` paths outside comments that start with
`# e.g.` and documentation examples. Add that sweep as a test, so a new
absolute path fails CI.
