# Phase 4 Unification — Decisions Needed From the Original Creator

**Purpose:** Phases 1–3 unified the *mechanically* mergeable helpers (`efc`, `helpers`,
`output_visualization`, `output_plots`, `display_controls`) plus the `poi_id → poi_gage_id`
and `nwis → waterdata` naming. What remains (Phase 4) is where **nhm and nhf genuinely
diverge in behavior or features** — merging these safely needs product decisions only the
original author can make. This document ranks the remaining files by how far apart they are
and asks the specific questions that unblock each one.

**How to read it:** each file lists the measured divergence, *what* differs, and concrete
questions. Each question has a **suggested default** — if you agree, just reply "confirm";
where you don't, tell us which side (or behavior) is canonical.

**Already decided (context, not open questions):**
- Canonical id name is **`poi_gage_id`** (the parameter-file-native name).
- Retrieval terminology is **`waterdata`** (nhm data source already uses the USGS WaterData API).
- Where one side is a clean superset of the other, **nhm is canonical** (it's the more-evolved implementation).

---

## Ranking (most-diverged first)

| # | File pair | Changed lines¹ | Divergence character |
|---|---|---|---|
| 1 | `map_template` | **~1518** | nhf added 8 whole new map features |
| 2 | `nhm_assist_utilities` | **~1120** | both sides added distinct functions |
| 3 | `nhm_hydrofabric` | **~592** | body-level drift + 1 nhf-only helper |
| 4 | `sf_data_retrieval` | **~139** | nearly unifiable; nhm is a superset |

¹ Diff lines after neutralizing module suffixes, `poi_id/poi_gage_id`, and `nwis/waterdata`
— i.e. *real* logic divergence, not naming.

---

## 1. `map_template` — nhm/map_template.py ↔ nhf/map_template_v2.py
**~1518 changed lines. nhf is ~813 lines larger.**

nhf added **8 functions that don't exist in nhm at all** — these are new capabilities, not
refactors:

| nhf-only function | Apparent purpose |
|---|---|
| `make_geo_map`, `create_geology_map`, `make_geo_legend` | geology map layer |
| `make_gf_map` | geospatial-fabric (GFv2) map |
| `create_FMI_poi_markers` | FMI point-of-interest markers |
| `create_ref_gages_markers`, `create_non_ref_gages_markers` | reference vs non-reference gage markers |
| `make_polygon_icon` | marker/icon helper for the above |

Also: nhm's `make_var_map` / `make_streamflow_map` pass `HW_basins` (headwater-basin overlays);
nhf has those **commented out**.

**Questions:**
1. **Are the 8 nhf map features (geology, GFv2, FMI, ref/non-ref gages) meant to be part of the unified NHM-Assist tool, or were they nhf-only experiments?** *Suggested default: treat them as nhf-only for now — keep them in an nhf-specific module and unify only the shared maps.* If they should be shared, they need review before merging.
2. **Should the unified maps keep the `HW_basins` headwater overlays (nhm) or drop them (nhf)?** *Suggested default: keep them (nhm) — nhf only commented them out, no evidence they were meant to be removed.*

---

## 2. `nhm_assist_utilities` — nhm/nhm_assist_utilities.py ↔ nhf/nhm_assist_utilities_v2.py
**~1120 changed lines. Both sides added distinct functions.**

| Only in nhm | Only in nhf |
|---|---|
| `_load_nldi_cached` (NLDI metadata caching) | `fetch_waterdata_gage_info` (= nhm's `fetch_nwis_gage_info`, renamed + behavior tweaks) |
| `_translate_waterdata_columns` | `fetch_ref_npoigages_info`, `fetch_non_ref_npoigages_info`, `fetch_FMI_npoigages_info` |
| `make_HW_cal_level_files` (headwater calibration levels) | `create_append_gages_to_param_file_v` |
| `fetch_nwis_gage_info` (= nhf's `fetch_waterdata_gage_info`) | |

`fetch_nwis_gage_info` (nhm) and `fetch_waterdata_gage_info` (nhf) are the **same function**
with two real behavior differences: nhf enables date-range filtering (`begin`/`end`) and uses
`site_type_code="ST"`; nhm leaves date-filtering off and uses `["ST","ST-TS"]`. nhf also reads
from `metadata/WaterDataGages.csv` (subfolder) vs nhm's flat `WaterDataGages.csv`.

**Questions:**
1. **For the gage-info fetch, which behavior is canonical — nhf's date-filtered + `ST`-only, or nhm's unfiltered + `ST`/`ST-TS`?** This changes *which gages/records* the tool returns, so it's a data-correctness call, not a style one. *Suggested default: need your call — no safe default.*
2. **The nhf `fetch_ref/non_ref/FMI_npoigages_info` + `create_append_gages_to_param_file_v` functions — part of the unified tool, or nhf-only?** *Suggested default: nhf-only unless they're intended as general features.*
3. **nhm's `_load_nldi_cached` (NLDI caching) and `make_HW_cal_level_files` — should nhf gain these too?** *Suggested default: yes — they look like general improvements with no nhf-specific coupling.*
4. **CSV location: flat `WaterDataGages.csv` (nhm) or `metadata/` subfolder (nhf)?** *Suggested default: flat — one less directory assumption.*

---

## 3. `nhm_hydrofabric` — nhm/nhm_hydrofabric.py ↔ nhf/nhm_hydrofabric_v2.py
**~592 changed lines. nhf ~64 lines larger; 1 nhf-only function.**

- nhf adds **`evaluate_and_fix_nhru_geometry`** — appears to repair invalid HRU geometries.
- `make_hf_map_elements` diverges: nhf takes an extra **`resource_gages_file`** parameter (part
  of nhf's "resource gages" feature cluster — see themes below) that nhm doesn't have.
- The remaining ~592 changed lines are body-level drift in the shared functions — needs a closer
  read to know which side's logic is canonical.

**Questions:**
1. **Should `evaluate_and_fix_nhru_geometry` (nhf) become standard?** *Suggested default: yes — geometry repair is a robustness win, and nhm's `sf_data_retrieval` already does the analogous `_safe_clip_mask`.*
2. **Does the unified `make_hf_map_elements` keep the `resource_gages_file` parameter (nhf)?** Depends on the resource-gages decision in Themes. *Suggested default: follow the resource-gages theme answer.*

---

## 4. `sf_data_retrieval` — nhm/sf_data_retrieval.py ↔ nhf/sf_data_retrieval_v2_1.py
**~139 changed lines — the closest to unifiable.**

nhm is essentially a **superset**: it adds `_safe_clip_mask` (GEOS-safe geometry clip) and
`_should_retry_waterdata` (transient-error retry/stagger for the WaterData API). No nhf-only
functions. The OWRD/ECY state-agency scrapers exist on both sides.

**One cleanup flag:** nhf has **two** files — `sf_data_retrieval_v2.py` (older, still contains the
legacy `create_nwis_sf_df`) and `sf_data_retrieval_v2_1.py` (current; the notebooks import this
one). The `_v2` file looks superseded.

**Questions:**
1. **Adopt nhm's robustness additions (`_safe_clip_mask`, retry logic) as canonical?** *Suggested default: yes — pure hardening, no behavior change to the happy path.*
2. **Can the older `nhf/sf_data_retrieval_v2.py` be deleted (superseded by `_v2_1`)?** *Suggested default: yes — nothing imports it in the current notebooks.*

---

## Cross-cutting themes

**A. The nhf "resource gages" feature cluster.** Several nhf-only pieces hang together:
`resource_gages_file` (`make_hf_map_elements`), `fetch_ref/non_ref/FMI_npoigages_info`, the
ref/non-ref gage markers in `map_template`. This looks like a deliberate nhf capability
(supplemental/reference gage sourcing). **Single question: is "resource gages" a general
NHM-Assist feature that should be unified in, or an nhf-specific workflow?** The answer resolves
pieces across files #1, #2, and #3 at once.

**B. Feature superset vs experiment.** The recurring pattern is nhf added *new features*
(geology/GF/FMI maps, resource gages) while nhm added *robustness* (retry, geometry repair, NLDI
caching, HW cal levels). If the nhf features are meant to ship, they each need their own review;
if not, unification is straightforward with nhm as the base + nhm's robustness folded into nhf.

---

## Suggested sequencing once answered
1. `sf_data_retrieval` (smallest, nhm-superset) — quick win.
2. `nhm_hydrofabric` (moderate) — gated on the resource-gages theme.
3. `nhm_assist_utilities` — gated on the gage-info behavior call + resource-gages theme.
4. `map_template` (largest) — gated on the 8-feature scope call.
