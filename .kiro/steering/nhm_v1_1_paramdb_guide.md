---
inclusion: manual
---

# NHM v1.1 Parameter Database Guide

Reference for working with the NHM v1.1 CONUS parameter database and comparing
parameters across model versions.

## Notebook Workflow

- Always edit the `.py` (percent format) files in `src/workflow_templates/nhf/`.
- Sync to `.ipynb` with jupytext after changes:
  ```
  & "C:\Users\ahaj\AppData\Local\miniforge3\envs\nhm\python.exe" -m jupytext --sync "src/workflow_templates/nhf/<filename>.py"
  ```
- The `.ipynb` files live in `nhf_assist/notebooks/` and are paired via the
  jupytext header in each `.py` file.
- Large notebooks (>200 KB) can exceed context limits. Work with the `.py`
  version and use targeted reads (line offsets, grep) when needed.

## Python Environment

- Python environment: `C:\Users\ahaj\AppData\Local\miniforge3\envs\nhm\python.exe`
- Invoke as: `& "C:\Users\ahaj\AppData\Local\miniforge3\envs\nhm\python.exe" <script or -m module>`
- Key packages available: geopandas, xarray, pywatershed, pyPRMS, fiona, ipywidgets, folium

## v1.1 Parameter Database Location

```
D:\nhm-assist\data_dependencies\NHM_v1_1\version1_1_params\
├── GFv1.1.gdb                          # Geodatabase with HRU/segment geometry
└── paramdb_v1.1_gridmet_CONUS-master\   # CSV parameter files (114,958 HRUs)
    ├── nhm_id.csv                       # Defines HRU ordering for all param CSVs
    ├── dday_intcp.csv
    ├── dday_slope.csv
    ├── jh_coef.csv
    ├── jh_coef_hru.csv
    └── ... (120+ parameter files)
```

## Reading Parameter CSVs

### HRU Ordering

The file `nhm_id.csv` defines the canonical HRU order for ALL parameter CSVs.
Row 0 in `nhm_id.csv` corresponds to row 0 in every other param CSV.

```python
df_nhm_id = pd.read_csv(paramdb / "nhm_id.csv")
nhm_id_order = df_nhm_id["nhm_id"].values  # array of nhm_ids in param-row order
nhm_id_to_row = {nid: idx for idx, nid in enumerate(nhm_id_order)}
```

### Scalar Parameters (one value per HRU)

Files like `jh_coef_hru.csv` have 114,958 rows (one per HRU).

```python
df = pd.read_csv(paramdb / "jh_coef_hru.csv")
values = df["jh_coef_hru"].values  # shape: (114958,)
```

### Monthly Parameters (12 values per HRU)

Files like `dday_intcp.csv`, `dday_slope.csv`, `jh_coef.csv` have
1,379,496 rows (= 114,958 HRUs x 12 months).

Storage is **month-major**: all HRUs for month 1, then all HRUs for month 2, etc.

```python
df = pd.read_csv(paramdb / "dday_intcp.csv")
values = df["dday_intcp"].values.reshape(12, 114958)  # shape: (12, nhru)
# values[0, :] = January for all HRUs
# values[6, :] = July for all HRUs
```

### The `$id` Column

Ignore `$id` in the CSV files. It is NOT related to `nhm_id`. It is just a
sequential row counter. Always use `nhm_id.csv` to establish the HRU identity
for each row position.

## GFv1.1.gdb Geodatabase

### Layers

| Layer | Description |
|-------|-------------|
| `nhru_v1_1` | HRU polygons (114,958 features) |
| `nhru_v1_1_simp` | Simplified HRU polygons |
| `nsegment_v1_1` | Stream segment lines |
| `POIs_v1_1` | Points of interest |
| `TBtoGFv1_POIs` | Transboundary POIs |

### nhru_v1_1 Attributes

| Column | Type | Description |
|--------|------|-------------|
| `nhru_v1_1` | int32 | HRU index (use this to link to nhm_id.csv) |
| `hru_segment_v1_1` | int32 | Associated segment |
| `nhm_id` | int32 | NHM identifier (range 1–122118, with gaps) |
| `hru_id_nat` | int32 | National HRU ID (same as nhm_id) |
| `Version` | str | Version flag |

### Linking GDB Geometry to Param Values

Use the `nhru_v1_1` attribute from the GDB to look up the row position in
`nhm_id.csv`, then use that row position to index into parameter arrays:

```python
import geopandas as gpd

gdf = gpd.read_file(gdb_path, layer="nhru_v1_1")
hru_ids = gdf["nhru_v1_1"].values

# Build lookup from nhm_id.csv
nhm_id_to_row = {nid: idx for idx, nid in enumerate(nhm_id_order)}

# Filter to HRUs that exist in the paramdb (GDB may have extras)
valid_mask = np.isin(hru_ids, nhm_id_order)
gdf = gdf[valid_mask].copy()
hru_ids = gdf["nhru_v1_1"].values
row_indices = np.array([nhm_id_to_row[nid] for nid in hru_ids])

# Now index into any param array
gdf["jh_coef_hru"] = jh_coef_hru_values[row_indices]
gdf["dday_intcp_Jan"] = dday_intcp_values[0, row_indices]  # month 0
```

### CRS

The GDB uses USA Contiguous Albers Equal Area Conic (ESRI:102039 / NAD83-based).
Reproject other datasets to match before spatial operations.

## Comparing v1.1 to v2 OHM

- **nhm_id does NOT carry across versions.** v1.1 and v2 OHM have completely
  independent HRU delineations and ID systems.
- All comparisons must be **geometric** (spatial clipping, visual side-by-side).
- Clip v1.1 to v2 extent using a bounding box intersection:

```python
from shapely.geometry import box

v2_bounds = v2_gdf_proj.total_bounds
buffer_m = 10000
clip_box = box(v2_bounds[0] - buffer_m, v2_bounds[1] - buffer_m,
               v2_bounds[2] + buffer_m, v2_bounds[3] + buffer_m)
v11_clipped = v11_gdf[v11_gdf.intersects(clip_box)].copy()
```

## v2 OHM Data Location

```
D:\nhm-assist\nhf_assist\hydrofabric_domain_data\OHM_2026_02_21\
├── GIS\model_layers.gpkg          # v2 HRU geometry (layer: "nhru")
├── param_source_files\            # Input params (hru_lat, hru_slope, etc.)
├── gridmet_climate_drivers\       # Climate inputs (tmin.nc, tmax.nc, prcp.nc)
└── created_hru_params\            # Output params computed by notebooks
```

## Willamette v1.1 Subdomain

A pre-extracted v1.1 subdomain for the Willamette River basin:

```
D:\nhm-assist\data_dependencies\20240524_v1.1_gm_precal_williamette_river\
├── GIS\model_nhru.shp    # HRU geometry
└── myparam.param          # All params in PRMS param file format
```

Read with pyPRMS:
```python
from pyPRMS import ParameterFile
from pyPRMS.metadata.metadata import MetaData

prms_meta = MetaData().metadata
pdb = ParameterFile(param_file, metadata=prms_meta, verbose=False)
values = pdb.get("dday_slope").data  # shape: (nhru, 12) — NOTE: (nhru, month) order
```

Note: pyPRMS returns monthly params as `(nhru, 12)`, which is the transpose of
the CSV reshape `(12, nhru)`. Be mindful of axis order.
