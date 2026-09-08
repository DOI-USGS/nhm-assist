# NHM Port of `find_missing_gage_info` — Design

**Date:** 2026-06-15
**Branch:** `restructure/pixi-workspace` (post-nhf_dev merge)
**Author:** Brainstorming session with senior dev
**Status:** Approved — ready for implementation plan

---

## Goal

When an NHM user runs notebook 1 (`1_create_streamflow_observations.ipynb`) and a gage in their model lacks an entry in `resource_gages.csv`, the workflow currently writes a row with empty metadata into `default_gages.csv`. After this change, NHM will call NLDI + WaterData to fill in that metadata, matching the QoL improvement Adel landed on NHF in commits `3b8d111` and `f35e314`.

## Background

NHF's `nhm_assist_utilities_v2.py::find_missing_gage_info` is a new helper that gathers gages missing from the resource file and queries NLDI (local geojson) + WaterData (network) to fill in their metadata. NHF's `create_default_gages_file` was restructured to delegate to that helper.

NHM's `nhm_hydrofabric.py::create_default_gages_file` does its own inline merging today and has no fallback for gages missing from `resource_gages.csv` — those rows end up in `default_gages.csv` with blank metadata cells.

The branch's `nhf_dev` merge brought in Adel's NHF-side changes (commits `3b8d111`, `f35e314`, `6faf85f`). The matching NHM helpers were not changed. This spec ports the same QoL improvement to NHM with a conservative, additive design.

## Scope

### In scope

- New helper `find_missing_gage_info` in `src/assist/nhm/nhm_assist_utilities.py`.
- A small additive call from `create_default_gages_file` in `src/assist/nhm/nhm_hydrofabric.py` at the end of its existing logic.
- Test module covering the new helper end to end with mocked network calls.
- One orchestration test confirming `create_default_gages_file` invokes the helper when expected.

### Out of scope (deferred to future specs)

- `nwis_*` → `waterdata_*` renames anywhere (config keys, cache filenames, function names).
- The `evaluate_and_fix_nhru_geometry` utility from NHF.
- Restructuring NHM's `create_default_gages_file` to mirror NHF's orchestration.
- Cache file rename `nwis_cache.nc` → `waterdata_cache.nc`.

## New function

In `src/assist/nhm/nhm_assist_utilities.py`:

```python
def find_missing_gage_info(
    *,
    gage_ids: list[str],
    poi_df: pd.DataFrame,
    resource_file_path: Path,
    root_dir: Path,
    nldi_geojson_path: Path | None = None,
) -> pd.DataFrame:
    """Look up metadata for gages missing from the resource file.

    Returns a DataFrame indexed by gage_id (poi_id) with columns matching
    the resource_gages.csv schema. Queries NLDI (local geojson) and
    WaterData (network) only for gages not already in the resource file.
    Returns an empty DataFrame if all gages are accounted for.

    Network failures log a warning and return whatever was successfully
    fetched; the caller is responsible for any rows still missing metadata.
    """
```

### Behavior

1. If `gage_ids` is empty, return empty DataFrame immediately. No network calls.
2. Load `resource_file_path` if it exists; remove any `gage_ids` already present in it (those need no lookup). If everything is covered, return empty.
3. Load the NLDI geojson from `nldi_geojson_path` (default `root_dir / "data_dependencies" / "usgs_nldi_gages.geojson"`). Use the cached `.gpkg` if it's newer than the source (see cache strategy below).
4. For gage IDs that match in NLDI, pull metadata from there.
5. For remaining IDs, call WaterData (`dataretrieval.waterdata.get_monitoring_locations` (returns a `(df, metadata)` tuple)) to fetch metadata.
6. Return the combined DataFrame, indexed by `poi_id`, with columns matching NHM's `resource_gages.csv` schema. NHM-specific column convention is preserved — `poi_id` not `poi_gage_id`.

### Defaults and conventions

- `nldi_geojson_path` defaults to `root_dir / "data_dependencies" / "usgs_nldi_gages.geojson"`.
- `poi_id` is used throughout (NHM convention, not NHF's `poi_gage_id`).
- `resource_file_path` is used as-is (no path normalization or directory creation).

## Integration point

In `src/assist/nhm/nhm_hydrofabric.py::create_default_gages_file`, **at the very end** of the function (after the existing inline merge logic completes):

```python
# (existing inline logic populates default_gages_df as today)

missing_mask = default_gages_df[REQUIRED_METADATA_COLUMNS].isna().any(axis=1)
if missing_mask.any():
    missing_ids = default_gages_df.loc[missing_mask, "poi_id"].tolist()
    fetched = find_missing_gage_info(
        gage_ids=missing_ids,
        poi_df=poi_df,
        resource_file_path=resource_gages_file,
        root_dir=root_dir,
    )
    if not fetched.empty:
        # fetched is indexed by poi_id; default_gages_df is row-indexed.
        # Align via set_index before update so cells merge by gage, not row.
        default_gages_df = (
            default_gages_df
            .set_index("poi_id")
            .combine_first(fetched)
            .reset_index()
        )
```

`combine_first` (rather than `update`) is the right primitive here: it fills in `NaN` cells in `default_gages_df` from `fetched` without overwriting any existing non-null values. Index alignment is explicit so the merge happens by `poi_id`, not by row position.

### What's intentional about this shape

- **No signature change to `create_default_gages_file`.** Notebook 1 is untouched.
- **Existing happy path is unchanged.** When `resource_gages.csv` is complete, `missing_mask.any()` is False and no API calls happen.
- **`DataFrame.update` semantics**: existing non-null values in `default_gages_df` are preserved; only the cells fetched for missing-metadata rows get filled in. We never overwrite user-curated rows.

### `REQUIRED_METADATA_COLUMNS`

Defined as a module-level constant in `nhm_hydrofabric.py`:

```python
REQUIRED_METADATA_COLUMNS = ("station_nm", "dec_lat_va", "dec_long_va", "drain_area_va")
```

This is the set of columns that constitute "this row has minimum metadata." Implementation will confirm against the current `resource_gages.csv` schema in the Walla_Walla example. If the schema includes more columns we care about (e.g. `huc_cd`), they'll be added.

## Failure handling

Per the brainstorming decision: graceful degradation. The helper never raises a network exception.

```python
try:
    nldi_rows = _query_nldi_cached(...)
except Exception as exc:
    nldi_rows = pd.DataFrame()
    print(f"WARNING: could not reach NLDI ({exc}); "
          f"{len(missing_ids)} gages may lack metadata.")

try:
    waterdata_rows = _query_waterdata(...)
except Exception as exc:
    waterdata_rows = pd.DataFrame()
    print(f"WARNING: could not reach WaterData ({exc}); "
          f"{len(missing_ids_still)} gages may lack metadata.")
```

Notebook 1 continues regardless. Users on planes, behind corporate proxies, or during USGS outages still get a usable `default_gages.csv` — same rows as before this change, plus whatever the partial network call managed to fill.

## NLDI cache strategy

Mirror NHF's caching:

- Cache lives at `<root_dir>/data_dependencies/usgs_nldi_gages.gpkg` (gitignored — derived artifact).
- Regenerated only when the `.geojson` is newer than the `.gpkg` (or the `.gpkg` is missing).
- Read-only access after that. Concurrent runs are safe because the input is static.
- If `data_dependencies/` is not writable (rare — read-only filesystem on shared HPC), the helper falls back to in-memory parsing every call. No error raised.

## Testing

### New test module

`tests/test_nhm_assist_utilities_find_missing.py` with five focused tests:

1. **Short-circuit** — `gage_ids=[]`; helper returns empty DataFrame; no network mocks invoked.
2. **All-found in NLDI** — NLDI mock returns rows for every missing gage; WaterData mock not called.
3. **Partial — NLDI then WaterData** — NLDI returns half the gages; WaterData mock fills the rest.
4. **NLDI failure** — NLDI mock raises (e.g. `OSError`); helper logs warning, falls through to WaterData, returns what WaterData returned.
5. **Total network failure** — both NLDI and WaterData mocks raise; helper logs both warnings, returns empty DataFrame; no exception propagates.

Mocking strategy: patch at the boundary.
- NLDI: mock the file read of `usgs_nldi_gages.geojson` (via `geopandas.read_file`) and the `.gpkg` cache path.
- WaterData: mock `dataretrieval.waterdata.get_monitoring_locations` (returns a `(df, metadata)` tuple). If implementation discovers a different method is needed, update the spec before changing the test surface.

No real network in tests.

### Integration test

Add one test to `tests/test_multi_model_workspace.py` (or a new file if it grows too large):

- Set up a fake project with a `poi_df` containing one gage that is NOT in a (deliberately incomplete) `resource_gages.csv`.
- Run `create_default_gages_file`.
- Assert `find_missing_gage_info` is called exactly once with the expected missing gage ID.

Patch `find_missing_gage_info` itself to return a fixture DataFrame; we're only verifying the orchestration in this test, not the helper's internals.

## Out-of-scope but worth noting (risks for implementation)

- **NLDI geojson presence**: `data_dependencies/usgs_nldi_gages.geojson` must exist for the helper to do useful work. If it's not present, the helper degrades to WaterData-only (which still works). Implementation should confirm the file ships with the repo or document the prerequisite in the helper docstring.
- **WaterData column semantics**: the `dataretrieval` library's WaterData methods return column names that differ between releases. Lock the column renamer at the boundary so NHM's `default_gages.csv` schema is stable regardless of `dataretrieval` version.
- **`poi_df` shape**: NHM's `poi_df` has different columns than NHF's. The helper only uses `poi_df["poi_id"]` for matching; verify this assumption holds in NHM during implementation.

## Acceptance criteria

The feature is successful when:

1. A user runs NHM notebook 1 with a `resource_gages.csv` missing entries for some gages.
2. After the notebook runs, `default_gages.csv` contains those previously-missing rows with `station_nm`, `dec_lat_va`, `dec_long_va`, and `drain_area_va` populated from NLDI or WaterData.
3. A user running NHM notebook 1 offline gets the same `default_gages.csv` they would have gotten before this change (rows with blank metadata), plus a clear warning that NLDI/WaterData were unreachable.
4. A user with a complete `resource_gages.csv` sees no behavioral change and no network calls happen.
5. All new tests pass; existing tests still pass; the pre-existing copy-example blocker remains the only failing test on the branch.

## Files expected to change

| Path | Change |
| --- | --- |
| `src/assist/nhm/nhm_assist_utilities.py` | Add `find_missing_gage_info` + private cache helper |
| `src/assist/nhm/nhm_hydrofabric.py` | Add `REQUIRED_METADATA_COLUMNS` constant; tail-call new helper in `create_default_gages_file` |
| `tests/test_nhm_assist_utilities_find_missing.py` (new) | 5 unit tests with mocked network |
| `tests/test_multi_model_workspace.py` | 1 orchestration test |
| `.gitignore` | Add `data_dependencies/usgs_nldi_gages.gpkg` if not already covered by an existing pattern |

No changes expected to:
- `src/workflow_templates/nhm/1_create_streamflow_observations.py` (signature unchanged)
- Any other notebook template
- `pyproject.toml` / `pixi.lock` (no new dependencies — `geopandas` and `dataretrieval` are already pulled in)
- `README.md`

## Non-goals

Do not, in this change:

- Rename anything from `nwis_*` to `waterdata_*`.
- Touch the streamflow cache file (`nwis_cache.nc`).
- Refactor the inline merge logic in `create_default_gages_file`.
- Add the `evaluate_and_fix_nhru_geometry` utility.
- Surface NLDI/WaterData failures via raised exceptions.
- Change any column names in NHM's data files.
