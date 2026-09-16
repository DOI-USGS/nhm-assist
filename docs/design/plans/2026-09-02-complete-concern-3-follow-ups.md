# Complete Concern 3 Follow-ups Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the actionable review follow-ups from the streamflow-data-retrieval unification while retaining compatibility with legacy NWIS-shaped YAML configurations.

**Architecture:** WaterData remains the only spelling emitted by current workflow templates and consumed by template call sites. `load_subdomain_config` continues to accept NWIS-shaped existing configuration files and exposes both spellings after loading. The static template callability sweep must use complete signature binding so it catches missing required arguments as well as retired keywords; generated notebooks are regenerated from the corrected templates and checked at the code-cell level.

**Tech Stack:** Python 3.11, pytest, AST/`inspect`, `nbformat`, Jupytext notebook generation, Pixi.

**Constraints:** Preserve the already staged changes. Run Python and pytest through `~/.pixi/bin/pixi run --frozen python -m pytest ...`; use `~/.pixi/bin/pixi run notebooks-create all` for generated notebooks. `tests/` and `docs/` are gitignored, so force-add new tests and confirm tracking. Stage changes but do not commit.

---

## File map

| File | Responsibility |
| --- | --- |
| `src/workflow_templates/nhm/0_workspace_setup.py` | Emits the canonical WaterData configuration schema for new NHM workspaces. |
| `src/workflow_templates/nhm/1_create_streamflow_observations.py` | Documents the actual WaterData cache and gage-file outputs. |
| `src/workflow_templates/nhf/0_workspace_setup.py` | Emits the actual metadata gage-cache path instead of a stale root-level path. |
| `src/assist/common/sf_data_retrieval.py` | Creates the gage-cache parent directory before writing its CSV. |
| `src/assist/common/assist_utilities.py` | Keeps the old root-level WaterData cache in cleanup. |
| `src/assist/common/hydrofabric.py` | Uses correct WaterData cache terminology in its documentation. |
| `src/workflow_templates/nhf/Fetch_poi_supplimental_information.py` | Supplies the required resource-gage path when calling `make_hf_map_elements`. |
| `src/workflow_templates/pest/poi_ranking.py` | Supplies the required resource-gage path when calling `make_hf_map_elements`. |
| `tests/unification/test_config_schema.py` | Proves legacy YAML still loads and new NHM template output is canonical. |
| `tests/unification/test_sf_terminology.py` | Guards the metadata output directory and current terminology. |
| `tests/unification/test_sf_shims.py` | Covers every real shim export and checks source plus generated notebook code cells for retired `create_nwis_sf_df`. |
| `tests/unification/test_nhm_notebook_signatures.py` | Checks complete function binding, including missing required arguments. |
| generated `*.ipynb` artifacts | Regenerated from their corresponding templates; never staged. |

## Task 1: Emit canonical WaterData configuration while retaining legacy input support

**Files:**
- Modify: `src/workflow_templates/nhm/0_workspace_setup.py:185-190,286-291,321-337`
- Modify: `src/workflow_templates/nhf/0_workspace_setup.py:298-307`
- Modify: `src/workflow_templates/nhm/1_create_streamflow_observations.py:152-155`
- Modify: `src/assist/common/hydrofabric.py:580-590`
- Modify: `tests/unification/test_config_schema.py`

- [ ] **Step 1: Write failing regression tests**

Add a source-level test that parses NHM notebook-0’s `dict_file` assignment and asserts it contains `waterdata_gage_nobs_min` and `waterdata_gages_file`, but neither retired NWIS key. Keep `test_reads_the_nhm_nwis_schema` unchanged: it is the compatibility contract for previously written YAML.

Add a test for NHF notebook-0 that asserts its emitted `waterdata_gages_file` value uses the already-defined `waterdata_gages_file` path variable, which resolves to `metadata/WaterDataGages.csv`.

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `~/.pixi/bin/pixi run --frozen python -m pytest tests/unification/test_config_schema.py -q`

Expected: failure because NHM notebook-0 still writes `nwis_*` keys and NHF serializes a different root-level path than its variable.

- [ ] **Step 3: Make the minimal template and prose changes**

In the NHM template, change only the generated-config schema and user-facing terminology:

```python
waterdata_gage_nobs_min = 365  # days
waterdata_gages_file = model_dir / "metadata/WaterDataGages.csv"

dict_file = {
    # ...
    "waterdata_gage_nobs_min": waterdata_gage_nobs_min,
    "waterdata_gages_file": str(waterdata_gages_file),
}
```

Use `waterdata_cache.nc` and `metadata/WaterDataGages.csv` in the NHM notebook-1 markdown. Update the stale hydrofabric docstring from `nwis_cache.nc` to `waterdata_cache.nc`. In NHF notebook-0, serialize `str(waterdata_gages_file)`.

Do **not** alter `CONFIG_KEY_ALIASES`, existing NWIS-schema loader tests, or legacy cleanup names: those preserve existing user configurations and old cache cleanup.

- [ ] **Step 4: Run the focused tests to verify they pass**

Run: `~/.pixi/bin/pixi run --frozen python -m pytest tests/unification/test_config_schema.py tests/unification/test_config_required_keys.py -q`

Expected: all pass, including tests proving both old and new YAML schemas load.

## Task 2: Make the WaterData cache output self-sufficient and clean up its legacy location

**Files:**
- Modify: `src/assist/common/sf_data_retrieval.py:1000-1006`
- Modify: `src/assist/common/assist_utilities.py:224-242`
- Modify: `tests/unification/test_sf_terminology.py`
- Create: `tests/unification/test_streamflow_output_cleanup.py`

- [ ] **Step 1: Write failing tests**

Extend the terminology regression test to require that `create_waterdata_sf_df` creates `waterdata_gages_file.parent` before calling `to_csv`. Add a cleanup test that creates both `model_dir / "WaterDataGages.csv"` and `model_dir / "metadata" / "WaterDataGages.csv"`, invokes `delete_notebook_output_files`, and asserts both old and canonical cache locations are removed.

- [ ] **Step 2: Run tests to verify failure**

Run: `~/.pixi/bin/pixi run --frozen python -m pytest tests/unification/test_sf_terminology.py tests/unification/test_streamflow_output_cleanup.py -q`

Expected: the output-directory assertion and root-level cache cleanup test fail.

- [ ] **Step 3: Implement the minimal safety fixes**

Immediately before the writer’s existing CSV call, add:

```python
waterdata_gages_file.parent.mkdir(parents=True, exist_ok=True)
out_gage_info.to_csv(waterdata_gages_file, index=False)
```

Add `"WaterDataGages.csv"` to the model-root `files` cleanup list. Leave the legacy `"NWISgages.csv"` and canonical metadata cleanup entries intact.

- [ ] **Step 4: Run tests to verify pass**

Run: `~/.pixi/bin/pixi run --frozen python -m pytest tests/unification/test_sf_terminology.py tests/unification/test_streamflow_output_cleanup.py -q`

Expected: all pass.

## Task 3: Make template callability reject missing required parameters

**Files:**
- Modify: `tests/unification/test_nhm_notebook_signatures.py:255-280`
- Modify: `src/workflow_templates/nhm/2_model_hydrofabric_visualization.py:80-92`
- Modify: `src/workflow_templates/nhm/3_model_parameter_visualization.py:85-97`
- Modify: `src/workflow_templates/nhm/5_hru_output_visualization_new.py:95-107`
- Modify: `src/workflow_templates/nhm/6_streamflow_output_visualization_new.py:86-98`
- Modify: `src/workflow_templates/nhm/add_pois_to_parameters.py:95-107`
- Modify: `src/workflow_templates/nhf/Fetch_poi_supplimental_information.py:70-82`
- Modify: `src/workflow_templates/pest/poi_ranking.py:83-95`

- [ ] **Step 1: Strengthen the existing failing callability test**

Replace `sig.bind_partial(...)` with `sig.bind(...)` in the existing AST sweep. Update its explanatory text to say it validates both accepted keywords and required arguments. Preserve its skips for `*args` and `**kwargs`, which cannot be checked statically.

- [ ] **Step 2: Run it to verify the expected failures**

Run: `~/.pixi/bin/pixi run --frozen python -m pytest tests/unification/test_nhm_notebook_signatures.py -q`

Expected initially: the binding sweep reports five missing `resource_gages_file` arguments in the NHM templates. The NHF supplemental template has no `make_hf_map_elements` import, and PEST imports that function through an absent `nhm_helpers` package, so neither call is resolvable by the sweep yet. Do not treat the five-only result as a pass or silently edit only five templates.

- [ ] **Step 3: Add a failing import-reachability regression**

Add AST-level checks to the same test module that prove the NHF supplemental template imports `make_hf_map_elements` from `assist.nhf.nhm_hydrofabric_v2`, and that PEST ranking imports the two names it actually uses (`load_subdomain_config` and `make_hf_map_elements`) from `assist.common.*` with no remaining `nhm_helpers` import. Run the test and observe the expected failure before source edits.

- [ ] **Step 4: Repair import reachability and add the seven required arguments**

At each flagged `make_hf_map_elements(...)` call, add the canonical config value:

```python
resource_gages_file=config["resource_gages_file"],
```

For the five NHM templates, make only that argument change. In the NHF supplemental template, add `make_hf_map_elements` to its existing `from assist.nhf.nhm_hydrofabric_v2 import create_poi_df` import, then add the argument.

In PEST ranking, replace the two used legacy imports with:

```python
from assist.common.assist_utilities import load_subdomain_config
from assist.common.hydrofabric import make_hf_map_elements
```

Remove its four now-unused imports from `nhm_helpers` (`efc`, `make_par_map`, `make_plots_par_vals`, and the star import); AST analysis proves no imported name is used elsewhere in this template. Then add the required argument. This is necessary to make the template importable before its corrected call can execute; do not change its root-directory behavior or later notebook cells.

- [ ] **Step 5: Run the callability regression test**

Run: `~/.pixi/bin/pixi run --frozen python -m pytest tests/unification/test_nhm_notebook_signatures.py -q`

Expected: pass with zero binding or return-arity mismatches; the expanded sweep now reaches all seven repaired calls.

## Task 4: Keep generated notebook code and retirement sweeps synchronized

**Files:**
- Modify: `tests/unification/test_sf_shims.py`
- Modify: `tests/unification/test_sf_terminology.py`
- Regenerate: `notebooks/*.ipynb`, `nhf_assist/notebooks/*.ipynb`, and PEST generated notebooks via `notebooks-create all` (ignored artifacts; do not stage)

- [ ] **Step 1: Write failing notebook-aware checks**

Add a small `nbformat` helper that reads only code-cell sources from generated notebook directories. Extend the existing retirement checks so `create_nwis_sf_df` is absent from both source templates and generated code cells, and `NWIS_df=` is absent from both the NHM template and its generated notebook code cells. Saved outputs and historical strings must not count as code references.

Also update `EXPECTED_AT_LEAST` in `test_sf_shims.py` to cover the actually imported `fetch_daily_discharge_batch` while retaining the public `owrd_scraper` export.

- [ ] **Step 2: Run the focused checks to verify failure**

Run: `~/.pixi/bin/pixi run --frozen python -m pytest tests/unification/test_sf_shims.py tests/unification/test_sf_terminology.py -q`

Expected: failure against stale generated notebooks carrying `create_nwis_sf_df` and `NWIS_df=`.

- [ ] **Step 3: Regenerate notebook artifacts**

Run: `~/.pixi/bin/pixi run notebooks-create all`

The command overwrites only generated, ignored `.ipynb` artifacts from the corrected templates. Inspect the two formerly stale code cells afterward; do not add notebook outputs to Git.

- [ ] **Step 4: Re-run notebook-aware checks**

Run: `~/.pixi/bin/pixi run --frozen python -m pytest tests/unification/test_sf_shims.py tests/unification/test_sf_terminology.py -q`

Expected: pass; the sweep protects source templates and notebooks users actually execute.

## Task 5: Verify concern-3 behavior and provenance end to end

**Files:**
- Modify as necessary only from Tasks 1–4.
- Create: `.superpowers/sdd/2026-09-01-unify-sf-data-retrieval/conclusion-report.md`

- [ ] **Step 1: Confirm test tracking**

Force-add any new test files, then verify all changed or created tests with:

```bash
git ls-files --error-unmatch \
  tests/unification/test_config_schema.py \
  tests/unification/test_streamflow_output_cleanup.py \
  tests/unification/test_sf_terminology.py \
  tests/unification/test_sf_shims.py \
  tests/unification/test_nhm_notebook_signatures.py
```

- [ ] **Step 2: Execute focused and full verification**

Run:

```bash
~/.pixi/bin/pixi run --frozen python -m pytest tests/unification/test_config_schema.py \
  tests/unification/test_config_required_keys.py \
  tests/unification/test_streamflow_output_cleanup.py \
  tests/unification/test_sf_terminology.py \
  tests/unification/test_sf_shims.py \
  tests/unification/test_nhm_notebook_signatures.py -q
~/.pixi/bin/pixi run --frozen python -m pytest tests/ -q
```

Run the original full-verification import sweep:

```bash
~/.pixi/bin/pixi run --frozen python -c "
import importlib
for module_name in (
    'assist.common.hydrofabric', 'assist.nhm.nhm_hydrofabric',
    'assist.nhf.nhm_hydrofabric_v2', 'assist.common.assist_utilities',
    'assist.nhm.nhm_assist_utilities', 'assist.nhf.nhm_assist_utilities_v2',
    'assist.nhf.map_template_v2', 'assist.nhm.map_template',
    'assist.nhf.sf_data_retrieval_v2_1', 'assist.nhm.sf_data_retrieval',
):
    importlib.import_module(module_name)
    print('OK', module_name)
"
```

Then run the caller-name/shim-identity census:

```bash
~/.pixi/bin/pixi run --frozen python - <<'PY'
import ast
import pathlib as pl
import assist.common.hydrofabric as common
import assist.nhf.nhm_hydrofabric_v2 as nhf
import assist.nhm.nhm_hydrofabric as nhm

targets = {'assist.nhm.nhm_hydrofabric', 'assist.nhf.nhm_hydrofabric_v2'}
names = set()
for path in pl.Path('src').rglob('*.py'):
    if '.ipynb_checkpoints' in str(path):
        continue
    try:
        tree = ast.parse(path.read_text(encoding='utf-8', errors='ignore'))
    except SyntaxError:
        continue
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in targets:
            names.update(alias.name for alias in node.names)

bad = [
    f'{label}.{name}'
    for name in sorted(names)
    for label, module in (('nhm', nhm), ('nhf', nhf))
    if getattr(module, name, None) is not getattr(common, name, object())
]
print(f'{len(names)} names x 2 shims ->', 'ALL RESOLVE' if not bad else f'FAILURES: {bad}')
PY
```

Expected: ten `OK` import lines and `ALL RESOLVE`. Finally verify the provenance claim with `git diff --name-status --find-renames 2997253^ 2997253`; it must include the intentional `R100` move into `common/`.

- [ ] **Step 3: Run the NHM notebook smoke path, if external data access is available**

Use the repository-root generated NHM notebooks and the repository-root example configuration; the template resolves this non-workspace mode from the current working directory. First regenerate the notebooks, then preserve and restore the config deterministically:

```bash
cd /Users/lludden/Documents/GitHub/nhm-assist-gitlab
~/.pixi/bin/pixi run notebooks-create nhm
smoke_backup_dir=$(mktemp -d /private/tmp/nhm-concern3-config.XXXXXX)
cp -p subdomain_config.yaml "$smoke_backup_dir/subdomain_config.yaml"
NHM_BATCH_MODE=1 ~/.pixi/bin/pixi run --frozen python -m jupyter nbconvert \
  --to notebook --execute --inplace --ExecutePreprocessor.timeout=3600 \
  notebooks/0_workspace_setup.ipynb
NHM_BATCH_MODE=1 ~/.pixi/bin/pixi run --frozen python -m jupyter nbconvert \
  --to notebook --execute --inplace --ExecutePreprocessor.timeout=3600 \
  notebooks/1_create_streamflow_observations.ipynb
cp -p "$smoke_backup_dir/subdomain_config.yaml" subdomain_config.yaml
```

Notebook 0 regenerates `subdomain_config.yaml` for `domain_data/Walla_Walla`; notebook 1 then exercises its WaterData cache and metadata paths. The two generated notebooks remain ignored. Report an unavailable network or data-service failure as environmental evidence, not a code pass; always restore the backed-up configuration before reporting the result.

- [ ] **Step 4: Stage and report, without a commit**

Stage source files normally and new/changed ignored tests with `git add -f`. Do not stage generated notebooks or commit anything. Write the conclusion report with exact test output, notebook generation/smoke results, changed files, test-tracking evidence, and deferred minor findings.

## Deferred minor findings

This plan resolves the review’s actionable compatibility, cache-path, generated-notebook, and callability defects. It does not silently alter the following independent behaviors:

- Retiring `_load_nldi_cached` and `_translate_waterdata_columns` requires a fresh whole-repository and public-API reachability decision, not the `src/`-only scan that previously proved too narrow.
- Changing the `ecy_scrape` `None` handling is a data-processing behavior change and needs a dedicated regression fixture.
- Removing the public-but-currently-unimported `owrd_scraper`, duplicate imports, and a misleading comment are non-blocking cleanup decisions. The shim test is corrected to cover `fetch_daily_discharge_batch` while retaining `owrd_scraper` as the established public surface.
