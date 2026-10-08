# BOR Hydromet QU Metadata — How the Station List Was Built

This document describes the one-time data-cataloguing process used to build the
master list of Bureau of Reclamation (BOR) Pacific Northwest Hydromet stations
that report **Estimated Average Unregulated Flow (QU)**, along with their
coordinates, elevation, QU data availability, USGS crosswalk, and nearest NHM
resource gage.

This is **provenance / cataloguing**, not part of the runtime `nhf_assist`
workflow. The consolidated pipeline lives in
[`build_bor_qu_metadata.py`](build_bor_qu_metadata.py). It replaces the earlier
collection of separate one-off scripts (`parse_hydromet_html_to_csv.py`,
`build_bor_qu_stations.py`, `crosswalk_bor_qu_coords.py`,
`crosswalk_bor_qu_usgs.py`, `find_nearest_poi_for_bor.py`, etc.).

> **Note on outputs:** The CSV outputs live under `data_dependencies/` and
> `nhf_assist/hydrofabric_domain_data/`, both of which are gitignored (data, not
> code). The pipeline script and this README are the committed record of *how*
> those files were produced. See
> `data_dependencies/README_hydromet_qu_provenance.md` for a description of the
> output columns.

## What QU is

"Estimated Average Unregulated Flow" (QU) is naturalized streamflow computed by
BOR from measured data in the regulated system. It removes the influence of
reservoir operations, diversions, and irrigation return flows to estimate the
natural inflow. These are useful calibration/validation targets at gages with
heavy anthropogenic influence.

## Access requirements (why this is run step by step)

The pipeline touches endpoints with conflicting network requirements, so it is
**not** run as a single automated job — you toggle VPN between steps:

| Step | Endpoint | Network |
|------|----------|---------|
| 1. parse HTML | local file (previously downloaded from `usbr.gov/pn/hydromet`) | any |
| 2. discover QU stations | `usbr.gov/pn/hydromet/station.js` + `usbr.gov/pn-bin/daily` | **OFF VPN** |
| 3. crosswalk coords (RISE) | RISE ArcGIS FeatureServer | **OFF VPN** |
| 4. crosswalk USGS | USGS WaterData API | **ON VPN** |
| 5. nearest POI | local files only | any |

## Pipeline steps

Run each step explicitly (recommended given the VPN toggling):

```bash
pixi run python scripts/build_bor_qu_metadata.py --list          # show steps
pixi run python scripts/build_bor_qu_metadata.py --step parse_hydromet_html
pixi run python scripts/build_bor_qu_metadata.py --step discover_qu_stations
pixi run python scripts/build_bor_qu_metadata.py --step crosswalk_coords_rise
pixi run python scripts/build_bor_qu_metadata.py --step crosswalk_usgs
pixi run python scripts/build_bor_qu_metadata.py --step find_nearest_poi
```

### 1. `parse_hydromet_html` — station names, coordinates, elevation

Parses the saved BOR Hydromet station report HTML
(`data_dependencies/Hydromet Pacific Northwest Region _ Bureau of Reclamation.html`,
downloaded from `https://www.usbr.gov/pn/hydromet/decod_params.html`). The report
contains a `<pre>` block of stations with CBTT code, description, and coordinates
in degrees-minutes-seconds. DMS values (e.g. `LAT=43-57-37 LONG=111-41-53`) are
converted to decimal degrees; longitudes are negated (Western Hemisphere).

- **Output:** `data_dependencies/hydromet_all_stations.csv` (~457 stations)

### 2. `discover_qu_stations` — which stations actually report QU

Pulls the full station dropdown from `station.js` (~442 stations), then queries
the legacy Hydromet daily endpoint
(`usbr.gov/pn-bin/daily?...&pcode=qu`) for each station over 1980–2024 and counts
valid QU days. Stations with `qu_days > 0` are kept and tagged `poi_agency="BOR-QU"`.

- **Output:** `.../npoigages_data/BOR_QU_gages.csv` (~52 QU stations)
- **Known gaps:** `ARKI` and `GCL` appear in `station.js` but not in the HTML
  report (2 of 52), so they lack HTML-sourced coordinates/elevation.

### 3. `crosswalk_coords_rise` — coordinates from RISE

Queries the RISE ArcGIS FeatureServer for Columbia–Pacific Northwest locations,
extracts CBTT codes from the trailing parentheses of each location name, and
matches to the QU stations (exact code, then 3-char fuzzy) to populate lat/lon.

- **Outputs:**
  - `data_dependencies/rise_cpnw_stations.csv` (RISE reference)
  - `.../npoigages_data/BOR_QU_gages_crosswalk_review.csv` (review file with both
    BOR and RISE names for manual verification)

### 4. `crosswalk_usgs` — USGS site IDs and coordinates

For stations still missing coordinates (or to associate a USGS equivalent),
searches USGS WaterData monitoring locations by name (with a state-name hint
parsed from the station name, and a fallback to the pre-comma short name).

- **Output:** `.../npoigages_data/BOR_QU_gages_usgs_crosswalk.csv`

### 5. `find_nearest_poi` — nearest NHM resource gage

Projects the BOR stations and `resource_gages.csv` to EPSG:5070 (CONUS Albers)
and runs a nearest spatial join to attach `nearest_poi_id` and `dist_m` (meters)
to each BOR station. This is what later lets a BOR-QU station be associated with
an NHM model segment via a composite id `<nearest_poi_id>-<CBTT>`.

- **Output (updated in place):** `.../npoigages_data/BOR_QU_gages_crosswalk_review.csv`

## After the pipeline: manual review

The `BOR_QU_gages_crosswalk_review.csv` is manually reviewed (using the folium
map notebook `src/workflow_templates/nhf/bor_npoigages_map.py`) to produce
`BOR_QU_domain_review.csv`, which adds:

- `good` — 0 = drop, 1 = use `nearest_poi_id`, 2 = use `alt_poi_id`
- `alt_poi_id` — override when the nearest gage is not the correct association
- `note` — reasoning for each decision

That reviewed file is what notebook 1 (`1_create_streamflow_observations.py`)
consumes to build the composite `poi_gage_id` values and pull QU data into
`sf_efc.nc`.

## Downstream consumers

- `src/workflow_templates/nhf/gf_params_parse.py` — clips BOR stations to a child domain
- `src/workflow_templates/nhf/1_create_streamflow_observations.py` — QU retrieval + integration into `sf_efc.nc`
- `src/workflow_templates/nhf/2_model_hydrofabric_visualization.py` — BOR-QU map layer
