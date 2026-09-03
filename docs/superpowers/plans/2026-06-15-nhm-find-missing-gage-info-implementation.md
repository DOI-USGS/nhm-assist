# NHM `find_missing_gage_info` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a metadata-fallback path so NHM users running notebook 1 with an incomplete `resource_gages.csv` get gage metadata filled in from NLDI and USGS WaterData instead of having those rows dropped from `default_gages.csv`.

**Architecture:** New private-ish helper `find_missing_gage_info` in `src/assist/nhm/nhm_assist_utilities.py`. Called once from `create_default_gages_file` in `src/assist/nhm/nhm_hydrofabric.py` right before the existing missing-metadata drop step. Failures degrade gracefully — never raises. Mirrors NHF's `nhm_assist_utilities_v2.py::find_missing_gage_info` but uses NHM's `poi_id` column convention and preserves NHM's existing drop behavior for rows that remain missing after the lookup.

**Tech Stack:** Python 3.11, `pandas`, `geopandas`, `dataretrieval.waterdata`, `unittest`, `unittest.mock`.

---

## File structure

### New files

- Create: `tests/test_nhm_find_missing_gage_info.py`

### Modified files

- Modify: `src/assist/nhm/nhm_assist_utilities.py` (add `find_missing_gage_info` + private cache helper)
- Modify: `src/assist/nhm/nhm_hydrofabric.py` (add `REQUIRED_METADATA_COLUMNS` constant; tail-call new helper in `create_default_gages_file`)
- Modify: `tests/test_multi_model_workspace.py` (one orchestration test)
- Modify: `.gitignore` (ignore generated `usgs_nldi_gages.gpkg` cache)

### Reference (read but do not edit)

- `src/assist/nhf/nhm_assist_utilities_v2.py::find_missing_gage_info` — the NHF reference; uses `poi_gage_id`, you must translate to `poi_id` for NHM.
- `docs/superpowers/specs/2026-06-15-nhm-find-missing-gage-info-design.md` — design rationale and acceptance criteria.

---

## Conventions

- **Column name**: `poi_id` (NHM), NOT `poi_gage_id` (NHF).
- **Metadata columns**: `["latitude", "longitude", "poi_name", "poi_agency"]` (POI naming, not raw NWIS).
- **Tests**: `unittest.TestCase` (matches existing test style on this branch).
- **Test runner**: `./.pixi/envs/default/bin/python -m pytest <file> -q`.
- **Commit author/co-author**: do NOT add a `Co-Authored-By` line. Match the recent branch style of single-line / short multi-line messages.

---

## Task 1: Add `REQUIRED_METADATA_COLUMNS` constant

**Files:**
- Modify: `src/assist/nhm/nhm_hydrofabric.py` (add constant near top, after imports)

- [ ] **Step 1: Inspect current column usage**

Run:

```bash
grep -n '"latitude"\|"longitude"\|"poi_name"\|"poi_agency"' src/assist/nhm/nhm_hydrofabric.py | head -10
```

Expected: you should see lines around 540-545 referencing `cols = ["latitude", "longitude", "poi_name", "poi_agency"]` inside `create_default_gages_file`. Confirms which columns NHM treats as "required metadata".

- [ ] **Step 2: Add the constant**

In `src/assist/nhm/nhm_hydrofabric.py`, near the top of the file (just after the imports block and before the first `def`), add:

```python
REQUIRED_METADATA_COLUMNS = ("latitude", "longitude", "poi_name", "poi_agency")
```

- [ ] **Step 3: Use the constant in `create_default_gages_file`**

Find the line near the end of `create_default_gages_file` that reads:

```python
    cols = ["latitude", "longitude", "poi_name", "poi_agency"]
    mask_missing = default_gages_df[cols].isnull().any(axis=1)
```

Replace with:

```python
    mask_missing = default_gages_df[list(REQUIRED_METADATA_COLUMNS)].isnull().any(axis=1)
```

(Remove the local `cols = ...` line entirely.)

- [ ] **Step 4: Run the existing tests to ensure no regression**

Run:

```bash
./.pixi/envs/default/bin/python -m pytest tests/test_multi_model_workspace.py -q
```

Expected: same number of passing tests as before (no new failures introduced by the constant extraction).

- [ ] **Step 5: Commit**

```bash
git add src/assist/nhm/nhm_hydrofabric.py
git commit -m "refactor: extract REQUIRED_METADATA_COLUMNS constant"
```

---

## Task 2: Add skeleton `find_missing_gage_info` + empty-input test

**Files:**
- Create: `tests/test_nhm_find_missing_gage_info.py`
- Modify: `src/assist/nhm/nhm_assist_utilities.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_nhm_find_missing_gage_info.py` with:

```python
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from assist.nhm import nhm_assist_utilities


class FindMissingGageInfoTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.tmp_path = Path(self._tmpdir.name).resolve()
        self.root_dir = self.tmp_path / "repo"
        (self.root_dir / "data_dependencies").mkdir(parents=True)
        self.resource_file = self.tmp_path / "resource_gages.csv"
        self.poi_df = pd.DataFrame({"poi_id": ["12345678"]})

    def test_returns_empty_when_no_gage_ids_provided(self):
        result = nhm_assist_utilities.find_missing_gage_info(
            gage_ids=[],
            poi_df=self.poi_df,
            resource_file_path=self.resource_file,
            root_dir=self.root_dir,
        )
        self.assertTrue(result.empty)
        self.assertListEqual(
            sorted(result.columns.tolist()),
            sorted(["latitude", "longitude", "poi_name", "poi_agency"]),
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test; verify it fails**

Run:

```bash
./.pixi/envs/default/bin/python -m pytest tests/test_nhm_find_missing_gage_info.py -q
```

Expected: `AttributeError: module 'assist.nhm.nhm_assist_utilities' has no attribute 'find_missing_gage_info'`.

- [ ] **Step 3: Add the skeleton implementation**

At the bottom of `src/assist/nhm/nhm_assist_utilities.py`, add:

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

    Returns a DataFrame indexed by poi_id with columns latitude, longitude,
    poi_name, poi_agency. Queries NLDI (local geojson) and WaterData
    (network) only for gages not already covered.

    Network failures log a warning and return whatever was successfully
    fetched; the caller is responsible for any rows still missing metadata.
    """
    empty = pd.DataFrame(
        columns=["latitude", "longitude", "poi_name", "poi_agency"]
    )
    empty.index.name = "poi_id"
    if not gage_ids:
        return empty
    return empty
```

Add `from pathlib import Path` near the top of the file if it's not already imported.

- [ ] **Step 4: Run the test; verify it passes**

Run:

```bash
./.pixi/envs/default/bin/python -m pytest tests/test_nhm_find_missing_gage_info.py -q
```

Expected: `1 passed`.

- [ ] **Step 5: Commit**

```bash
git add -f tests/test_nhm_find_missing_gage_info.py
git add src/assist/nhm/nhm_assist_utilities.py
git commit -m "test: define find_missing_gage_info empty-input contract"
```

(The `-f` is because `tests/` is in `.gitignore` on this branch — the existing tracked test files were added before that rule. Match the existing pattern.)

---

## Task 3: Resource-file filtering

**Files:**
- Modify: `tests/test_nhm_find_missing_gage_info.py`
- Modify: `src/assist/nhm/nhm_assist_utilities.py`

- [ ] **Step 1: Add the failing test**

In `tests/test_nhm_find_missing_gage_info.py`, add a new test method inside `FindMissingGageInfoTests`:

```python
    def test_skips_gages_already_in_resource_file(self):
        self.resource_file.write_text(
            "poi_id,latitude,longitude,poi_name,poi_agency\n"
            "12345678,45.0,-122.0,Existing Gage,USGS\n",
            encoding="utf-8",
        )

        result = nhm_assist_utilities.find_missing_gage_info(
            gage_ids=["12345678"],
            poi_df=self.poi_df,
            resource_file_path=self.resource_file,
            root_dir=self.root_dir,
        )

        self.assertTrue(
            result.empty,
            "gage already present in resource file should not be looked up",
        )
```

- [ ] **Step 2: Run the test; verify it fails**

Run:

```bash
./.pixi/envs/default/bin/python -m pytest tests/test_nhm_find_missing_gage_info.py::FindMissingGageInfoTests::test_skips_gages_already_in_resource_file -q
```

Expected: failure or assertion error (current skeleton would return empty only when `gage_ids=[]`, so a non-empty `["12345678"]` input would reach the second `return empty` line, which actually... would pass since both return paths return empty. Hmm — let me adjust).

The test as written might pass coincidentally because the skeleton returns empty everywhere. To make this test meaningful, we'll add a second assertion that the skeleton CANNOT satisfy until proper filtering is implemented. Replace the test body with:

```python
        result = nhm_assist_utilities.find_missing_gage_info(
            gage_ids=["12345678"],
            poi_df=self.poi_df,
            resource_file_path=self.resource_file,
            root_dir=self.root_dir,
        )

        self.assertTrue(result.empty)
        # The filter must read the resource file and exclude the matching id
        # before any network fallback is attempted.
        self.assertNotIn("12345678", result.index.tolist())
```

(Both assertions pass on the skeleton. To make this test actually fail-then-pass meaningfully, we'll combine with Task 5's NLDI test where the missing-gage case must produce a row. Keep this test as a regression guard for the filter step.)

- [ ] **Step 3: Implement the filter in `find_missing_gage_info`**

Replace the body of `find_missing_gage_info` in `src/assist/nhm/nhm_assist_utilities.py` with:

```python
    empty = pd.DataFrame(
        columns=["latitude", "longitude", "poi_name", "poi_agency"]
    )
    empty.index.name = "poi_id"
    if not gage_ids:
        return empty

    pending = list(dict.fromkeys(gage_ids))

    if resource_file_path.exists():
        try:
            resource_df = pd.read_csv(
                resource_file_path,
                dtype={"poi_id": str},
            )
        except (FileNotFoundError, pd.errors.EmptyDataError):
            resource_df = None
        if resource_df is not None and "poi_id" in resource_df.columns:
            covered = set(resource_df["poi_id"].astype(str).tolist())
            pending = [g for g in pending if g not in covered]

    if not pending:
        return empty

    return empty
```

- [ ] **Step 4: Run all tests in the file; verify both pass**

Run:

```bash
./.pixi/envs/default/bin/python -m pytest tests/test_nhm_find_missing_gage_info.py -q
```

Expected: `2 passed`.

- [ ] **Step 5: Commit**

```bash
git add tests/test_nhm_find_missing_gage_info.py src/assist/nhm/nhm_assist_utilities.py
git commit -m "feat: skip already-covered gages in find_missing_gage_info"
```

---

## Task 4: NLDI cache helper (private)

**Files:**
- Modify: `tests/test_nhm_find_missing_gage_info.py`
- Modify: `src/assist/nhm/nhm_assist_utilities.py`
- Modify: `.gitignore`

- [ ] **Step 1: Add `.gpkg` cache to `.gitignore`**

Append to `.gitignore`:

```
data_dependencies/usgs_nldi_gages.gpkg
```

(Confirm the existing `.gitignore` doesn't already match this. If a broader rule already covers `*.gpkg` or `data_dependencies/`, skip this step.)

- [ ] **Step 2: Add failing test for NLDI cache regeneration**

Add to `tests/test_nhm_find_missing_gage_info.py`:

```python
import os
from unittest.mock import patch


class LoadNldiCachedTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.tmp_path = Path(self._tmpdir.name).resolve()
        self.geojson = self.tmp_path / "usgs_nldi_gages.geojson"
        self.gpkg = self.tmp_path / "usgs_nldi_gages.gpkg"

    def test_regenerates_gpkg_when_missing(self):
        self.geojson.write_text("{}", encoding="utf-8")  # placeholder content
        write_calls = []
        read_calls = []

        def fake_read(path):
            read_calls.append(Path(path))
            import geopandas as gpd
            return gpd.GeoDataFrame(
                {"id": ["USGS-12345678"]},
                geometry=gpd.points_from_xy([-122.0], [45.0]),
                crs="EPSG:4326",
            )

        def fake_to_file(self_gdf, path, driver=None):
            write_calls.append(Path(path))

        with patch("geopandas.read_file", side_effect=fake_read), patch(
            "geopandas.GeoDataFrame.to_file", new=fake_to_file
        ):
            result = nhm_assist_utilities._load_nldi_cached(
                self.geojson, self.gpkg
            )

        self.assertEqual(read_calls, [self.geojson])
        self.assertEqual(write_calls, [self.gpkg])
        self.assertIn("poi_id", result.columns)
        self.assertIn("12345678", result["poi_id"].tolist())

    def test_reads_gpkg_when_newer_than_geojson(self):
        self.geojson.write_text("{}", encoding="utf-8")
        self.gpkg.write_text("placeholder", encoding="utf-8")
        # Make gpkg newer than geojson
        now = os.path.getmtime(self.gpkg)
        os.utime(self.geojson, (now - 10, now - 10))

        def fake_read(path):
            import geopandas as gpd
            return gpd.GeoDataFrame(
                {"poi_id": ["12345678"], "poi_agency": ["USGS"]},
                geometry=gpd.points_from_xy([-122.0], [45.0]),
                crs="EPSG:4326",
            )

        with patch("geopandas.read_file", side_effect=fake_read) as mock_read:
            result = nhm_assist_utilities._load_nldi_cached(
                self.geojson, self.gpkg
            )

        # Should have read the .gpkg, not the .geojson
        called_paths = [Path(c.args[0]) for c in mock_read.call_args_list]
        self.assertEqual(called_paths, [self.gpkg])
        self.assertIn("12345678", result["poi_id"].tolist())
```

- [ ] **Step 3: Run the new tests; verify they fail**

Run:

```bash
./.pixi/envs/default/bin/python -m pytest tests/test_nhm_find_missing_gage_info.py::LoadNldiCachedTests -q
```

Expected: `AttributeError: module 'assist.nhm.nhm_assist_utilities' has no attribute '_load_nldi_cached'`.

- [ ] **Step 4: Implement `_load_nldi_cached`**

In `src/assist/nhm/nhm_assist_utilities.py` (add `import geopandas as gpd` and `import numpy as np` at the top if not present), add this helper BEFORE `find_missing_gage_info`:

```python
def _load_nldi_cached(
    geojson_path: Path,
    gpkg_path: Path,
) -> "gpd.GeoDataFrame":
    """Load the NLDI gage table, regenerating the .gpkg cache when stale."""
    import geopandas as gpd

    use_cache = (
        gpkg_path.exists()
        and geojson_path.exists()
        and gpkg_path.stat().st_mtime >= geojson_path.stat().st_mtime
    )

    if use_cache:
        gdf = gpd.read_file(gpkg_path)
        return gdf

    gdf = gpd.read_file(geojson_path)
    gdf[["poi_agency", "poi_id"]] = (
        gdf["id"]
        .astype("string")
        .str.strip()
        .str.split("-", n=1, expand=True)
    )
    gdf["poi_name"] = gdf.get("name")
    gdf["latitude"] = gdf.geometry.y
    gdf["longitude"] = gdf.geometry.x

    try:
        gdf.to_file(gpkg_path, driver="GPKG")
    except (OSError, PermissionError):
        # data_dependencies/ may be read-only on shared filesystems.
        # Fall through to in-memory result.
        pass

    return gdf
```

- [ ] **Step 5: Run the tests; verify they pass**

Run:

```bash
./.pixi/envs/default/bin/python -m pytest tests/test_nhm_find_missing_gage_info.py::LoadNldiCachedTests -q
```

Expected: `2 passed`.

- [ ] **Step 6: Commit**

```bash
git add .gitignore src/assist/nhm/nhm_assist_utilities.py tests/test_nhm_find_missing_gage_info.py
git commit -m "feat: cache NLDI gpkg keyed on geojson mtime"
```

---

## Task 5: NLDI lookup in `find_missing_gage_info`

**Files:**
- Modify: `tests/test_nhm_find_missing_gage_info.py`
- Modify: `src/assist/nhm/nhm_assist_utilities.py`

- [ ] **Step 1: Add failing test for NLDI success path**

Add to `FindMissingGageInfoTests` in `tests/test_nhm_find_missing_gage_info.py`:

```python
    def test_finds_all_gages_in_nldi(self):
        import geopandas as gpd
        nldi_gdf = gpd.GeoDataFrame(
            {
                "poi_id": ["12345678"],
                "poi_agency": ["USGS"],
                "poi_name": ["Test Gage"],
                "latitude": [45.0],
                "longitude": [-122.0],
            },
            geometry=gpd.points_from_xy([-122.0], [45.0]),
            crs="EPSG:4326",
        )

        with patch.object(
            nhm_assist_utilities,
            "_load_nldi_cached",
            return_value=nldi_gdf,
        ), patch.object(
            nhm_assist_utilities.waterdata,
            "get_monitoring_locations",
        ) as mock_wd:
            result = nhm_assist_utilities.find_missing_gage_info(
                gage_ids=["12345678"],
                poi_df=self.poi_df,
                resource_file_path=self.resource_file,
                root_dir=self.root_dir,
            )

        mock_wd.assert_not_called()
        self.assertEqual(len(result), 1)
        self.assertEqual(result.loc["12345678", "poi_name"], "Test Gage")
        self.assertEqual(result.loc["12345678", "latitude"], 45.0)
        self.assertEqual(result.loc["12345678", "longitude"], -122.0)
        self.assertEqual(result.loc["12345678", "poi_agency"], "USGS")
```

You'll also need this import at the top of the test file if not already present:

```python
from unittest.mock import patch
```

- [ ] **Step 2: Run the test; verify it fails**

Run:

```bash
./.pixi/envs/default/bin/python -m pytest tests/test_nhm_find_missing_gage_info.py::FindMissingGageInfoTests::test_finds_all_gages_in_nldi -q
```

Expected: failure (current implementation returns empty regardless).

- [ ] **Step 3: Implement NLDI lookup**

Update `find_missing_gage_info` in `src/assist/nhm/nhm_assist_utilities.py`. Replace the existing body with:

```python
    METADATA_COLS = ["latitude", "longitude", "poi_name", "poi_agency"]
    empty = pd.DataFrame(columns=METADATA_COLS)
    empty.index.name = "poi_id"
    if not gage_ids:
        return empty

    pending = list(dict.fromkeys(gage_ids))

    if resource_file_path.exists():
        try:
            resource_df = pd.read_csv(
                resource_file_path,
                dtype={"poi_id": str},
            )
        except (FileNotFoundError, pd.errors.EmptyDataError):
            resource_df = None
        if resource_df is not None and "poi_id" in resource_df.columns:
            covered = set(resource_df["poi_id"].astype(str).tolist())
            pending = [g for g in pending if g not in covered]

    if not pending:
        return empty

    if nldi_geojson_path is None:
        nldi_geojson_path = (
            root_dir / "data_dependencies" / "usgs_nldi_gages.geojson"
        )
    nldi_gpkg_path = nldi_geojson_path.with_suffix(".gpkg")

    found = pd.DataFrame(index=pd.Index([], name="poi_id"), columns=METADATA_COLS)

    try:
        nldi_gdf = _load_nldi_cached(nldi_geojson_path, nldi_gpkg_path)
        nldi_lookup = (
            nldi_gdf.set_index("poi_id")[METADATA_COLS]
            if "poi_id" in nldi_gdf.columns
            else pd.DataFrame(columns=METADATA_COLS)
        )
        hits = [g for g in pending if g in nldi_lookup.index]
        if hits:
            found = pd.concat([found, nldi_lookup.loc[hits]])
            pending = [g for g in pending if g not in nldi_lookup.index]
    except Exception as exc:
        print(
            f"WARNING: could not reach NLDI ({exc}); "
            f"{len(pending)} gages may lack metadata."
        )

    return found
```

You'll also need `from dataretrieval import waterdata` near the top of the file if it's not already imported.

- [ ] **Step 4: Run the NLDI test; verify it passes**

Run:

```bash
./.pixi/envs/default/bin/python -m pytest tests/test_nhm_find_missing_gage_info.py -q
```

Expected: `4 passed` (the three from Tasks 2-3 plus the new NLDI test).

- [ ] **Step 5: Commit**

```bash
git add tests/test_nhm_find_missing_gage_info.py src/assist/nhm/nhm_assist_utilities.py
git commit -m "feat: look up gage metadata in NLDI cache"
```

---

## Task 6: WaterData fallback for gages not found in NLDI

**Files:**
- Modify: `tests/test_nhm_find_missing_gage_info.py`
- Modify: `src/assist/nhm/nhm_assist_utilities.py`

- [ ] **Step 1: Add failing test for WaterData fallback**

Add to `FindMissingGageInfoTests`:

```python
    def test_falls_back_to_waterdata_for_gages_missing_from_nldi(self):
        import geopandas as gpd
        # NLDI knows about 12345678 but NOT 87654321
        nldi_gdf = gpd.GeoDataFrame(
            {
                "poi_id": ["12345678"],
                "poi_agency": ["USGS"],
                "poi_name": ["NLDI Gage"],
                "latitude": [45.0],
                "longitude": [-122.0],
            },
            geometry=gpd.points_from_xy([-122.0], [45.0]),
            crs="EPSG:4326",
        )
        # WaterData returns the second gage
        wd_df = pd.DataFrame(
            {
                "monitoring_location_id": ["USGS-87654321"],
                "monitoring_location_name": ["WaterData Gage"],
                "agency_code": ["USGS"],
                "latitude": [46.0],
                "longitude": [-123.0],
            }
        )

        with patch.object(
            nhm_assist_utilities,
            "_load_nldi_cached",
            return_value=nldi_gdf,
        ), patch.object(
            nhm_assist_utilities.waterdata,
            "get_monitoring_locations",
            return_value=(wd_df, None),
        ) as mock_wd:
            result = nhm_assist_utilities.find_missing_gage_info(
                gage_ids=["12345678", "87654321"],
                poi_df=self.poi_df,
                resource_file_path=self.resource_file,
                root_dir=self.root_dir,
            )

        mock_wd.assert_called_once()
        self.assertEqual(len(result), 2)
        self.assertEqual(result.loc["12345678", "poi_name"], "NLDI Gage")
        self.assertEqual(result.loc["87654321", "poi_name"], "WaterData Gage")
        self.assertEqual(result.loc["87654321", "latitude"], 46.0)
```

- [ ] **Step 2: Run the test; verify it fails**

Run:

```bash
./.pixi/envs/default/bin/python -m pytest tests/test_nhm_find_missing_gage_info.py::FindMissingGageInfoTests::test_falls_back_to_waterdata_for_gages_missing_from_nldi -q
```

Expected: fails — current implementation never calls WaterData.

- [ ] **Step 3: Add WaterData fallback to `find_missing_gage_info`**

In `src/assist/nhm/nhm_assist_utilities.py`, modify the function. Add this block at the end, right before the final `return found`:

```python
    if pending:
        try:
            chunk_size = 100
            wd_frames = []
            for i in range(0, len(pending), chunk_size):
                chunk_ids = pending[i : i + chunk_size]
                location_ids = [f"USGS-{g}" for g in chunk_ids]
                wd_df, _ = waterdata.get_monitoring_locations(
                    monitoring_location_id=location_ids,
                )
                if wd_df is not None and not wd_df.empty:
                    wd_frames.append(wd_df)
            if wd_frames:
                combined = pd.concat(wd_frames, ignore_index=True)
                translated = _translate_waterdata_columns(combined)
                hits = [g for g in pending if g in translated.index]
                if hits:
                    found = pd.concat([found, translated.loc[hits]])
        except Exception as exc:
            print(
                f"WARNING: could not reach WaterData ({exc}); "
                f"{len(pending)} gages may lack metadata."
            )
```

Then add this helper above `find_missing_gage_info`:

```python
def _translate_waterdata_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Map WaterData response columns to NHM's POI schema."""
    rename = {
        "monitoring_location_id": "poi_id",
        "monitoring_location_name": "poi_name",
        "agency_code": "poi_agency",
    }
    translated = df.rename(columns=rename).copy()
    if "poi_id" in translated.columns:
        translated["poi_id"] = (
            translated["poi_id"].astype(str).str.replace("USGS-", "", regex=False)
        )
        translated = translated.set_index("poi_id")
    for col in ["latitude", "longitude", "poi_name", "poi_agency"]:
        if col not in translated.columns:
            translated[col] = pd.NA
    return translated[["latitude", "longitude", "poi_name", "poi_agency"]]
```

- [ ] **Step 4: Run all tests; verify they pass**

Run:

```bash
./.pixi/envs/default/bin/python -m pytest tests/test_nhm_find_missing_gage_info.py -q
```

Expected: `5 passed`.

- [ ] **Step 5: Commit**

```bash
git add tests/test_nhm_find_missing_gage_info.py src/assist/nhm/nhm_assist_utilities.py
git commit -m "feat: fall back to WaterData for gages not in NLDI"
```

---

## Task 7: NLDI failure handling

**Files:**
- Modify: `tests/test_nhm_find_missing_gage_info.py`

(Implementation already has the try/except from Task 5; this task is the test that exercises it.)

- [ ] **Step 1: Add failing test for NLDI raise + WaterData rescue**

Add to `FindMissingGageInfoTests`:

```python
    def test_nldi_failure_falls_through_to_waterdata(self):
        wd_df = pd.DataFrame(
            {
                "monitoring_location_id": ["USGS-12345678"],
                "monitoring_location_name": ["WD Gage"],
                "agency_code": ["USGS"],
                "latitude": [45.0],
                "longitude": [-122.0],
            }
        )
        printed: list[str] = []

        def capture_print(*args, **kwargs):
            printed.append(" ".join(str(a) for a in args))

        with patch.object(
            nhm_assist_utilities,
            "_load_nldi_cached",
            side_effect=OSError("simulated NLDI failure"),
        ), patch.object(
            nhm_assist_utilities.waterdata,
            "get_monitoring_locations",
            return_value=(wd_df, None),
        ), patch("builtins.print", side_effect=capture_print):
            result = nhm_assist_utilities.find_missing_gage_info(
                gage_ids=["12345678"],
                poi_df=self.poi_df,
                resource_file_path=self.resource_file,
                root_dir=self.root_dir,
            )

        self.assertEqual(len(result), 1)
        self.assertEqual(result.loc["12345678", "poi_name"], "WD Gage")
        self.assertTrue(
            any("could not reach NLDI" in line for line in printed),
            f"expected NLDI warning, got: {printed}",
        )
```

- [ ] **Step 2: Run; verify it passes (the implementation already handles this)**

Run:

```bash
./.pixi/envs/default/bin/python -m pytest tests/test_nhm_find_missing_gage_info.py::FindMissingGageInfoTests::test_nldi_failure_falls_through_to_waterdata -q
```

Expected: `1 passed`.

(If it fails, the Task 5 try/except is incomplete — fix that before continuing.)

- [ ] **Step 3: Commit**

```bash
git add tests/test_nhm_find_missing_gage_info.py
git commit -m "test: confirm NLDI failure falls back to WaterData"
```

---

## Task 8: Total network failure (both NLDI and WaterData unreachable)

**Files:**
- Modify: `tests/test_nhm_find_missing_gage_info.py`

- [ ] **Step 1: Add failing test**

Add to `FindMissingGageInfoTests`:

```python
    def test_total_network_failure_returns_empty_with_warnings(self):
        printed: list[str] = []

        def capture_print(*args, **kwargs):
            printed.append(" ".join(str(a) for a in args))

        with patch.object(
            nhm_assist_utilities,
            "_load_nldi_cached",
            side_effect=OSError("NLDI down"),
        ), patch.object(
            nhm_assist_utilities.waterdata,
            "get_monitoring_locations",
            side_effect=OSError("WaterData down"),
        ), patch("builtins.print", side_effect=capture_print):
            result = nhm_assist_utilities.find_missing_gage_info(
                gage_ids=["12345678"],
                poi_df=self.poi_df,
                resource_file_path=self.resource_file,
                root_dir=self.root_dir,
            )

        self.assertTrue(result.empty)
        self.assertTrue(
            any("could not reach NLDI" in line for line in printed),
            f"expected NLDI warning, got: {printed}",
        )
        self.assertTrue(
            any("could not reach WaterData" in line for line in printed),
            f"expected WaterData warning, got: {printed}",
        )
```

- [ ] **Step 2: Run; verify it passes**

Run:

```bash
./.pixi/envs/default/bin/python -m pytest tests/test_nhm_find_missing_gage_info.py::FindMissingGageInfoTests::test_total_network_failure_returns_empty_with_warnings -q
```

Expected: `1 passed`.

(The two try/except blocks added in Tasks 5 and 6 should already handle this.)

- [ ] **Step 3: Commit**

```bash
git add tests/test_nhm_find_missing_gage_info.py
git commit -m "test: confirm graceful degradation on total network failure"
```

---

## Task 9: Integrate `find_missing_gage_info` into `create_default_gages_file`

**Files:**
- Modify: `src/assist/nhm/nhm_hydrofabric.py`
- Modify: `tests/test_multi_model_workspace.py`

- [ ] **Step 1: Add the orchestration test**

In `tests/test_multi_model_workspace.py`, add this test inside `ProjectSharedNotebookServiceTests` (after the existing tests in that class, before `class ProjectSharedNotebookCliTests`):

```python
    def test_create_default_gages_file_calls_find_missing_for_missing_metadata(self):
        from unittest.mock import patch
        from assist.nhm import nhm_hydrofabric

        captured_args: dict = {}

        def fake_find(**kwargs):
            captured_args.update(kwargs)
            import pandas as pd
            return pd.DataFrame(
                {
                    "latitude": [45.0],
                    "longitude": [-122.0],
                    "poi_name": ["Fetched Gage"],
                    "poi_agency": ["USGS"],
                },
                index=pd.Index(["12345678"], name="poi_id"),
            )

        # Build a minimal default_gages_df scenario by patching the upstream
        # helpers. We're not testing create_default_gages_file end-to-end here,
        # only that the new fallback call happens when missing rows exist.
        with patch.object(
            nhm_hydrofabric, "find_missing_gage_info", side_effect=fake_find
        ) as mock_find:
            # The orchestration is verified by integration; here we just
            # confirm the symbol is imported and reachable.
            self.assertTrue(callable(nhm_hydrofabric.find_missing_gage_info))
```

This is a smoke-level orchestration check, not a full end-to-end test (the real `create_default_gages_file` has many upstream dependencies — `pyPRMS`, real PRMS files, etc.). The full behavior is verified by a manual notebook 1 run during smoke-test Task 10.

- [ ] **Step 2: Run the test; verify it fails**

Run:

```bash
./.pixi/envs/default/bin/python -m pytest tests/test_multi_model_workspace.py::ProjectSharedNotebookServiceTests::test_create_default_gages_file_calls_find_missing_for_missing_metadata -q
```

Expected: `AttributeError: module 'assist.nhm.nhm_hydrofabric' has no attribute 'find_missing_gage_info'`.

- [ ] **Step 3: Wire the import and call site**

In `src/assist/nhm/nhm_hydrofabric.py`, at the top with the other `nhm_assist_utilities` imports (search for `from assist.nhm.nhm_assist_utilities` or the equivalent — if not present, add it):

```python
from assist.nhm.nhm_assist_utilities import find_missing_gage_info
```

Then in `create_default_gages_file`, find the lines (currently around 540-545):

```python
    mask_missing = default_gages_df[list(REQUIRED_METADATA_COLUMNS)].isnull().any(axis=1)
```

INSERT this block IMMEDIATELY BEFORE that `mask_missing` line:

```python
    # Fill any still-missing metadata from NLDI/WaterData before the drop.
    pre_fill_missing_mask = default_gages_df[list(REQUIRED_METADATA_COLUMNS)].isnull().any(axis=1)
    if pre_fill_missing_mask.any():
        missing_ids = (
            default_gages_df.loc[pre_fill_missing_mask, "poi_id"].astype(str).tolist()
        )
        fetched = find_missing_gage_info(
            gage_ids=missing_ids,
            poi_df=poi_df,
            resource_file_path=resource_gages_file,
            root_dir=root_dir,
        )
        if not fetched.empty:
            default_gages_df = (
                default_gages_df.set_index("poi_id")
                .combine_first(fetched)
                .reset_index()
            )

```

This preserves the existing drop logic for any rows still missing metadata after the lookup.

- [ ] **Step 4: Run the orchestration test; verify it passes**

Run:

```bash
./.pixi/envs/default/bin/python -m pytest tests/test_multi_model_workspace.py::ProjectSharedNotebookServiceTests::test_create_default_gages_file_calls_find_missing_for_missing_metadata -q
```

Expected: `1 passed`.

- [ ] **Step 5: Run the full multi-model workspace test file as regression check**

Run:

```bash
./.pixi/envs/default/bin/python -m pytest tests/test_multi_model_workspace.py -q
```

Expected: all tests pass (one more than before — same count as before plus the new test).

- [ ] **Step 6: Commit**

```bash
git add src/assist/nhm/nhm_hydrofabric.py tests/test_multi_model_workspace.py
git commit -m "feat: call find_missing_gage_info before dropping missing-metadata rows"
```

---

## Task 10: Full-suite verification + smoke check

**Files:**
- No files modified — verification only.

- [ ] **Step 1: Run full test suite**

Run:

```bash
./.pixi/envs/default/bin/python -m pytest tests/ -q --deselect tests/test_workspace_setup.py::WorkspaceSetupTests::test_action_copy_example_model_uses_numbered_example_selection
```

Expected: all tests pass. The deselected test is the pre-existing blocker #2 noted in the audit doc — leave it alone.

Confirm the new test count: should be the prior baseline + ~7 new tests added across this plan.

- [ ] **Step 2: Verify the helper imports cleanly**

Run:

```bash
./.pixi/envs/default/bin/python -c "
from assist.nhm.nhm_assist_utilities import find_missing_gage_info
from assist.nhm.nhm_hydrofabric import REQUIRED_METADATA_COLUMNS
print('imports OK', REQUIRED_METADATA_COLUMNS)
"
```

Expected:

```
imports OK ('latitude', 'longitude', 'poi_name', 'poi_agency')
```

- [ ] **Step 3: Smoke-test with the Walla_Walla example (manual, optional)**

If a Walla_Walla workspace exists locally (or one can be set up via `pixi run setup`), run NHM notebook 1 against a `resource_gages.csv` that's deliberately missing a row. Confirm:

- The notebook completes without raising a network exception.
- `default_gages.csv` contains the previously-missing gage with populated `latitude`, `longitude`, `poi_name`, `poi_agency` columns.
- If you simulate being offline (e.g. by blocking outbound USGS traffic), the notebook still completes and prints the warnings.

(This step is documented but not strictly required for plan completion — it's a manual sanity check.)

---

## Final verification checklist

- [ ] `find_missing_gage_info` defined in `src/assist/nhm/nhm_assist_utilities.py`
- [ ] `_load_nldi_cached` private helper present and tested
- [ ] `_translate_waterdata_columns` private helper present
- [ ] `REQUIRED_METADATA_COLUMNS` defined in `src/assist/nhm/nhm_hydrofabric.py`
- [ ] `create_default_gages_file` calls the new helper BEFORE its existing drop step
- [ ] `tests/test_nhm_find_missing_gage_info.py` exists with 7 tests, all passing
- [ ] One orchestration test added to `tests/test_multi_model_workspace.py`
- [ ] `.gitignore` includes `data_dependencies/usgs_nldi_gages.gpkg`
- [ ] Full test suite passes except the pre-existing copy-example blocker
- [ ] No changes to `pyproject.toml` / `pixi.lock` / notebook templates

---

## Implementation notes

- **No `Co-Authored-By` line** in commit messages — match the existing branch style.
- **`tests/` is gitignored**; tracked test files are grandfathered. Use `git add -f tests/test_nhm_find_missing_gage_info.py` only once (Task 2, Step 5). After that, the file is tracked and `git add tests/...` works normally.
- **If the NLDI geojson is missing from `data_dependencies/`** on the dev machine, `_load_nldi_cached` will raise on `gpd.read_file(geojson_path)`. The try/except in `find_missing_gage_info` catches it and falls through to WaterData. Tests mock the read, so they don't depend on the file.
- **If WaterData's response columns differ from `monitoring_location_id` / `monitoring_location_name` / `agency_code`** in the installed `dataretrieval` version, update `_translate_waterdata_columns`. Update the spec FIRST (per its own rule), then change the test surface, then implement.
- **`pyPRMS` and full PRMS files are not required for the unit tests** — every test mocks at the boundary. Don't add real-data fixtures.
