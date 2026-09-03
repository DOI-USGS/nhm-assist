# Helper Unification: Collapsing the nhm / nhf Module Duplication

**Date:** 2026-08-30
**Branch:** `restructure/helper-unification-2`
**Status:** design approved, awaiting spec review

## 1. Problem

`src/assist/` carries two parallel implementations of the same nine concerns: one
under `nhm/` and one under `nhf/` (mostly suffixed `_v2`). The two have drifted
in both directions. Neither is a superset of the other, so the duplication cannot
be resolved by declaring one side authoritative.

Four concerns are already unified on this branch and establish the pattern:
`efc`, `nhm_helpers` (as `common/helpers.py`), `nhm_output_visualization` (as
`common/output_visualization.py`), and `output_plots`. In each, the shared
implementation lives in `src/assist/common/` and both `nhm/` and `nhf/` are
reduced to re-export shims.

### Current state

| Concern | nhm | nhf | `common/` | Status |
| --- | --- | --- | --- | --- |
| `efc` | 19L shim | 19L shim | 363L | done |
| `nhm_helpers` | 7L shim | 7L shim | 193L (`helpers.py`) | done |
| `nhm_output_visualization` | 27L shim | 25L shim | 692L | done |
| `output_plots` | 25L shim | 25L shim | 1579L | done |
| `display_controls` | absent | 213L full | 389L | half done |
| `map_template` | 2467L | 3317L | missing | not started |
| `nhm_assist_utilities` | 1100L | 1614L | missing | not started |
| `nhm_hydrofabric` | 838L | 930L | missing | not started |
| `sf_data_retrieval` | 1189L | 1162L (`_v2_1`) | missing | not started |

Roughly 12,800 lines remain across five concerns (5,594 on the nhm side,
7,023 on the nhf side, plus 213 for `display_controls`). A further 1,269 lines
sit in the dead `sf_data_retrieval_v2.py`.

### Blast radius

These modules have almost no unit coverage, and many notebooks import them. The
85-test suite on this branch imports exactly one `assist` module
(`assist.nhm.streamflow_postprocess`); it would not catch a regression in
anything this work touches.

| Concern | test files referencing | workflow templates importing |
| --- | --- | --- |
| `nhm_assist_utilities` | 1 | 38 |
| `nhm_hydrofabric` | 2 | 23 |
| `map_template` | 0 | 19 |
| `sf_data_retrieval` | 0 | 5 |

## 2. Decisions

1. **Target is `common/`.** Continue the established pattern rather than merging
   into `nhm/` or promoting `_v2`. Keeps the branch internally consistent.
2. **Divergence is handled with version-tolerant adapters.** One implementation
   in `common/` that accommodates both hydrofabrics, following the
   `_hru_dim_name` / `_normalize_hru_id_column` precedent already in
   `common/output_visualization.py`. An adapter must be justified by an observed
   difference; no speculative ones.
3. **Verification is differential.** For each unified function, call the
   pre-unification `nhm/` and `nhf/` implementations and the new `common/` one
   with identical inputs and compare. The old code is the oracle.
4. **Spec covers all five concerns; implementation lands one concern at a time**,
   each with its own commit and passing differential tests before the next
   begins.
5. **`fmi_gages_info.csv` is removed from the `delete_notebook_output_files`
   delete list**, as part of Step 1. It is the only entry in that list that
   cannot be regenerated: its sole writer is the dead `else` branch of
   `fetch_FMI_npoigages_info`, which requires the absent
   `TableA2_FlowManagementIndex.csv`. The other three entries have live writers
   and were observed regenerating. The same function currently spares
   `ref_npoigages_info.csv` and `non_ref_npoigages_info.csv`, which *are*
   regenerable, so the list as written destroys the one irreplaceable file and
   preserves two replaceable siblings.
6. **Layer labels settle on the NHM-prefixed form** — `"NHM HRUs"` and
   `"NHM Segments"` — for both workflows, rather than being parameterized.
7. **WaterData is the canonical terminology**, replacing NWIS everywhere: config keys
   (`waterdata_gages_file`, `waterdata_gage_nobs_min`), function names
   (`fetch_waterdata_gage_info` over `fetch_nwis_gage_info`), and prose. Legacy NWIS
   *filenames* stay in cleanup lists so older models still get tidied.
8. **When the two sides differ, nhf wins by default.** It is the more actively developed
   side and generally has far more callers. Two standing exceptions, both about safety
   rather than convention:
   - `delete_notebook_output_files` keeps nhm's behaviour, because nhf's deletes the
     unrecoverable `metadata/fmi_gages_info.csv` (decision 5).
   - Where nhf's and nhm's functions share a name but are genuinely different functions
     with different signatures and return contracts, the nhf one takes the name and the
     nhm one is carried under a private name until its caller can be migrated. Silently
     swapping return contracts under a live caller is not a rename.
9. **`load_subdomain_config` fails fast on a missing required key.** Derived from evidence,
   not preference: parsing every `config[...]` and `config.get(...)` read under `src/` finds
   28 keys read and **none read defensively**, so there is no optional-key category in
   practice and both pre-unification baselines subscripted every key. The `raw.get(key)`
   tolerance introduced during concern 1 was therefore a regression, and the test pinning it
   is removed. `resource_gages_file` is the one genuine exception — read in 7 places but
   present only in nhf-shaped configs — so it stays tolerated, explicitly. Resolves final-review
   finding I2 and its live exposure at
   `src/workflow_templates/pest/00_Subset_NHM_baselines_gfv2.py:145`.
10. **Each remaining concern moves its dominant file with a two-commit `git mv`**, so the
    unified module keeps default-discoverable history. Verified experimentally on a throwaway
    branch: committing a bare `git mv` first makes git record `R100`, and plain `git blame`
    then attributes lines in the new file to their original author, path and date with no
    `-C` flags. Recreating the shim in a *second* commit preserves that.

    Procedure, per concern:
    1. `git mv <dominant side> src/assist/common/<name>.py` and commit that alone.
    2. Recreate the shim at the old path, and make the second side a shim too, in a
       following commit.
    3. Only then append the other side's unique functions and any merged logic.

    Two costs, both accepted deliberately:
    - The intermediate commit has nothing at the old path, so importers break at exactly
      that commit. This does not affect the final state but it does poison `git bisect`,
      which will fail on that commit for an unrelated reason. Note it in the commit message.
    - A file can be renamed from only one ancestor. Pick the side contributing the most
      content — nhf for every concern so far — and accept that the other side's lineage
      still needs `git blame -C -C -C`. Unifying two files into one cannot preserve both
      lineages by default.

    Concerns 1 and 2 are already committed without this and are not being rewritten:
    `restructure/helper-unification-2` tracks a remote, so rewriting its history would be
    disruptive for no functional gain. Their provenance is instead recorded by the
    AST-identity tests, which assert each unified function is byte-identical to a named
    baseline commit, and reachable via the `pblame` alias (`blame -C -C -C`).

    Applies to: `sf_data_retrieval`, `map_template`, and the remainder of
    `display_controls`. It matters most for `map_template` — 5,784 lines across two files
    with years of history.

## 3. Target shape

For each concern, create `src/assist/common/<name>.py` holding the union
implementation, then reduce both existing files to re-export shims exposing
`__all__`.

| New module | Replaces |
| --- | --- |
| `common/assist_utilities.py` | `nhm/nhm_assist_utilities.py`, `nhf/nhm_assist_utilities_v2.py` |
| `common/hydrofabric.py` | `nhm/nhm_hydrofabric.py`, `nhf/nhm_hydrofabric_v2.py` |
| `common/sf_data_retrieval.py` | `nhm/sf_data_retrieval.py`, `nhf/sf_data_retrieval_v2_1.py` |
| `common/map_template.py` | `nhm/map_template.py`, `nhf/map_template_v2.py` |
| `common/display_controls.py` (exists) | plus `nhf/display_controls_v2.py` |

Names drop the `nhm_` prefix to match the existing `common/` files.

**Shim filenames must not change.** The nhf shim for streamflow retrieval stays
at `sf_data_retrieval_v2_1.py`, because that is the filename six notebooks
import. `sf_data_retrieval_v2.py` is dead (zero importers) and is deleted
separately.

## 4. Divergence: measured, not assumed

36 functions are shared-but-different. Classified by whether HRU/segment/POI
identifier naming is involved in the diff:

| Category | Count | Meaning |
| --- | --- | --- |
| identifier-only | 1 | resolved purely by an id adapter |
| identifier + other | 16 | id naming is one of several differences |
| no identifier involvement | 19 | differ for unrelated reasons |

Identifier naming is a genuine cross-cutting concern — `nhm_id` vs `hru_id`,
`hru_segment_nhm` vs `hru_segment`, `tosegment_nhm` vs `tosegment`, plus `nhru`
and the recent `poi_id` to `poi_gage_id` rename — but it explains only one
function on its own. The bulk of the work is per-function judgment.

Seven functions have more than 100 changed lines, which means substantive
behavioral divergence rather than drift:

| Function | Concern | Changed lines |
| --- | --- | --- |
| `create_streamflow_poi_markers` | map_template | 451 |
| `find_missing_gage_info` | assist_utilities | 426 |
| `ecy_scrape` | sf_data_retrieval | 190 |
| `create_default_gages_file` | hydrofabric | 178 |
| `make_hf_map` | map_template | 169 |
| `create_poi_df` | hydrofabric | 160 |
| `make_obs_plot_files` | assist_utilities | 121 |

These are effectively one-sided rewrites and must be merged by hand, function by
function, with the differential test as the arbiter.

### Classification buckets

Every differing function is assigned exactly one bucket:

- **Identical modulo whitespace** — move verbatim.
- **Drift** — one side is better or carries a bugfix. Take it; name the choice in
  the commit message.
- **Genuine fabric difference** — one implementation plus a private adapter in
  `common/`.
- **Irreconcilable** — leave split across `nhm/` and `nhf/`, with a comment
  explaining why. This is an escape hatch, not a strategy.

## 5. The identifier adapter

Add a small private helper set to `common/` (extending, not duplicating, the
existing `_normalize_hru_id_column` / `_hru_dim_name` in
`common/output_visualization.py`) covering the observed identifier pairs:

- HRU id: `nhm_id` / `hru_id` / `nhru` / `hruid`
- HRU-to-segment: `hru_segment_nhm` / `hru_segment`
- Segment id: `nhm_seg` / `seg_id`
- Segment topology: `tosegment_nhm` / `tosegment`
- Gage id: `poi_gage_id` (canonical; `poi_id` is the retired name)

Canonical form inside `common/` is the `nhm_id` / `nhm_seg` / `poi_gage_id`
family, matching what `common/output_visualization.py` already normalizes to.
The adapters accept either input naming and normalize on the way in.

Because the adapters resolve at most a contributing factor in 17 functions, they
are a supporting mechanism, not the plan.

## 6. Sequence

Forced by the import graph:

```
assist_utilities  ->  { hydrofabric, sf_data_retrieval }  ->  map_template  ->  display_controls
```

`assist_utilities` is imported by every other concern. `display_controls`
imports `map_template`, `hydrofabric`, `output_visualization`, and
`output_plots`, so it goes last.

### Step 1: `assist_utilities`

10 shared (3 identical, 7 differ), 5 nhf-only, 4 nhm-only.

- differ: `create_append_gages_to_param_file`, `delete_notebook_output_files`,
  `find_missing_gage_info`, `load_subdomain_config`,
  `make_myparam_addl_gages_param_file`, `make_obs_plot_files`,
  `make_plots_par_vals`
- nhf-only, carry over: `create_append_gages_to_param_file_v2`,
  `fetch_FMI_npoigages_info`, `fetch_non_ref_npoigages_info`,
  `fetch_ref_npoigages_info`, `fetch_waterdata_gage_info`
- nhm-only, must not be lost: `_load_nldi_cached`,
  `_translate_waterdata_columns`, `fetch_nwis_gage_info`,
  `make_HW_cal_level_files`

Two specifics for this step:

- `fetch_FMI_npoigages_info` carries the graceful-skip guard added in `01fc9b6`.
  Preserve it verbatim.
- `delete_notebook_output_files` drops `'fmi_gages_info.csv'` from its metadata
  delete list (decision 5), keeping `WaterDataGages.csv`. This is a **deliberate
  behavior change** and therefore the plan's first "drift" case: its differential
  test asserts the new behavior and will intentionally disagree with both prior
  implementations. Accepted trade-off: a stale FMI cache may persist. It degrades
  gracefully, because the merge onto gages is an inner join, so unmatched gages
  simply do not join. Any future refresh belongs behind an explicit flag, never
  as default behavior.

### Step 2a: `hydrofabric`

6 shared (0 identical, 6 differ), 1 nhf-only, 1 nhm-only.

- differ: `create_default_gages_file`, `create_hru_gdf`, `create_poi_df`,
  `create_segment_gdf`, `make_hf_map_elements`, `read_gages_file`
- nhf-only: `evaluate_and_fix_nhru_geometry`
- nhm-only: `_load_byhwobs_cal_gages`

`create_hru_gdf` and `create_segment_gdf` are the clearest identifier-adapter
cases: they differ precisely on the `nhm_id`/`hru_id` and
`tosegment_nhm`/`tosegment` pairs.

### Step 2b: `sf_data_retrieval`

Against the live `_v2_1` file: 10 shared (4 identical, 6 differ), 0 nhf-only,
2 nhm-only.

- differ: `create_OR_sf_df`, `create_ecy_sf_df`, `create_sf_efc_df`,
  `create_waterdata_sf_df`, `ecy_scrape`, `fetch_daily_discharge_batch`
- nhm-only: `_safe_clip_mask`, `_should_retry_waterdata`

The nhm-only pair is the "GEOS-safe clip + WaterData retry/stagger" hardening.
It must survive.

### Step 3: `map_template`

21 shared (4 identical, 17 differ), 8 nhf-only, 0 nhm-only. The hardest concern.

- identical: `create_minimap`, `folium_map_elements`, `folium_map_tiles`,
  `is_wsl`
- nhf-only, carry over: `create_FMI_poi_markers`, `create_geology_map`,
  `create_non_ref_gages_markers`, `create_ref_gages_markers`,
  `make_geo_legend`, `make_geo_map`, `make_gf_map`, `make_polygon_icon`
- `make_hf_map` differs by 169 lines with no identifier involvement: the nhf
  version wires in the FMI, reference-gage, and geology layers.
- Exactly two labels differ: `"NHM HRUs"` vs `"HRUs"` and `"NHM Segments"` vs
  `"Segments"`. Thirteen layer names are already identical and the remaining nine
  nhf names are new layers with no counterpart, so this is two strings, not a
  systemic divergence. Per decision 6, both take the NHM-prefixed form. The
  prefix is not version-specific (both workflows model the NHM regardless of
  fabric) and it distinguishes the model's own mesh from the nhf-only geometry
  layers `"HUC-10 basins"`, `"HUC12 points"`, and `"SGMC Geology"`. Verified
  non-breaking: layer names appear nowhere programmatically — the only reference
  outside `map_template` is a commented-out line at
  `create_upland_lowland_breaks.py:923` — and the map legend is a baked PNG using
  different wording. Like the FMI change, this is a deliberate divergence, so the
  differential test asserts the canonical set rather than either old version.

### Step 4: `display_controls`

`common/display_controls.py` already exists (389L, derived from the nhm side).
Fold in the 9 functions unique to `nhf/display_controls_v2.py` — `_get_valid_poi`,
`_get_valid_poi1`, `generate_flux`, `generate_map`, `generate_summary`,
`on_generate_clicked`, `on_map_clicked`, `on_plot_clicked`, `warn` — then shim.

## 7. Differential testing

For each concern, `tests/test_unification_<concern>.py`:

1. Materialize the pre-unification `nhm/` and `nhf/` implementations by reading
   them out of git (`git show <base>:<path>`) into temporary modules.
2. Call old and new with identical inputs.
3. Assert equivalence.

Inputs come from real models so both fabrics are exercised: bundled
`Walla_Walla`, plus `WWGW_Basin` (GFv1.1) and `UmatillaRiver` (GFv2).

Comparison by return type:

- DataFrame / GeoDataFrame: `assert_frame_equal`, with column-name normalization
  applied to both sides so identifier renames do not register as failures
- folium objects: layer names and feature counts, not rendered HTML
- plotly figures: trace data, not pixels
- paths and files written: existence plus content hash

Network-dependent functions (`fetch_waterdata_gage_info`, `ecy_scrape`,
`fetch_daily_discharge_batch`, `create_waterdata_sf_df`) get a
`@pytest.mark.network` marker and are excluded from the default run.

**The tests must pass against current, un-unified code first.** That proves the
harness before it is trusted to judge a rewrite. A harness that cannot
distinguish the two existing implementations is worthless as an oracle.

`tests/` is gitignored (`.gitignore:487`) but holds tracked files, so new test
files need `git add -f`.

## 8. Per-concern workflow

1. Write the differential test; confirm it passes against current code.
2. Create `common/<name>.py` as the union.
3. Reduce both sides to shims.
4. Differential tests green.
5. Smoke-check the affected notebooks.
6. Commit.

Each concern is a safe stopping point.

## 9. Dead code

Delete `src/assist/nhf/sf_data_retrieval_v2.py` (1269L, zero importers) in its
own commit. Do not touch the large commented-out blocks inside
`map_template_v2.py` as part of this work.

## 10. Risks and stop conditions

- **`map_template` is the main risk.** 17 of 21 shared functions differ, two by
  more than 160 lines, and folium objects resist exact comparison, so its
  differential tests are structural rather than exact. **Stop condition:** if the
  irreconcilable bucket fires more than twice in one concern, halt and
  re-brainstorm rather than pushing through.
- **Notebooks 4 through 6 cannot serve as smoke checks today.** Notebook 4 fails
  for GFv1.1 models because pywatershed 2.0.4 cannot load a parameter file
  containing the 24 stream-temperature and segment-geometry parameters
  (`stream_tave_init` and family). Any `output_visualization`-adjacent path stays
  unverified end to end until that is addressed.
- **The four already-unified concerns were not differentially tested.** They may
  already carry silent regressions from their own unification. Out of scope here,
  but worth a separate pass.
- **`find_missing_gage_info` (426 changed lines) and `create_streamflow_poi_markers`
  (451) may not be reconcilable** into one implementation at reasonable cost. If
  so they become the documented irreconcilable cases.

## 11. Out of scope

- Fixing the pywatershed GFv1.1 parameter incompatibility.
- Sourcing `TableA2_FlowManagementIndex.csv` or otherwise restoring FMI data.
  Decision 5 stops the cache from being deleted going forward, but the two test
  models have already lost theirs and cannot be recovered.
- Migrating nhf notebooks onto the workspace runner (`resolve_nhm_runtime_paths`).
  nhf still resolves models by hardcoded `domain_data/<subdomain>` paths while
  nhm uses the runner. Unifying helpers does not unify model resolution.
- Retroactively differential-testing the four completed concerns.
- Any change to `nhf/make_pws_params.py`, `nhf/nhm_config.py`, or the HRRR
  download scripts, which have no nhm counterpart.
