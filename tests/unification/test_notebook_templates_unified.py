"""One workflow-template set instead of a copy per workflow.

The seven numbered templates existed twice (nhm/ and nhf/) and drifted 507
lines apart. Dominance was decided per file: nhm's 0,1,2,3,5,6 and add_pois
(they carry the workspace project-context resolution and were the verified
running set), nhf's 4 (it adds hruid/nhru/nhm_id dimension normalization,
PrmsFile parameter loading, and the soil_moist_max==0 guard against
pywatershed's soilzone divide-by-zero). The dominant copy of each moved into
common/ via bare `git mv` committed alone, so plain `git blame` still credits
the original authors.

No template needed a fabric branch. The differences were the workflow root,
import paths, nhf debug cells, two nhf robustness improvements (POI-with-data
selection for the EFC plot, and an NHM_BATCH_MODE guard), and parameter-list
content -- all of which the shared set now carries.

The load-bearing subtlety is the root. `resolve_nhm_runtime_paths` always
reports the *repo* root, so a shared template that trusted it would silently
point nhf's and pest's notebooks at the nhm workspace's config and model
directory -- corrupting data rather than raising. `resolve_workflow_root`
derives the root from the notebook's own location instead.
"""
import ast
import inspect
import os
import pathlib

import pytest

from tests.unification.harness import REPO_ROOT

COMMON_DIR = REPO_ROOT / "src/workflow_templates/common"
SHARED_TEMPLATES = [
    "0_workspace_setup",
    "1_create_streamflow_observations",
    "2_model_hydrofabric_visualization",
    "3_model_parameter_visualization",
    "4_run_model_using_pywatershed",
    "5_hru_output_visualization_new",
    "6_streamflow_output_visualization_new",
    "add_pois_to_parameters",
]


def _template(name: str) -> str:
    return (COMMON_DIR / f"{name}.py").read_text(encoding="utf-8")


@pytest.mark.parametrize("name", SHARED_TEMPLATES)
def test_shared_template_exists_and_parses(name):
    assert (COMMON_DIR / f"{name}.py").is_file(), f"{name} missing from common/"
    ast.parse(_template(name))


def test_no_workflow_owns_a_duplicate_of_a_shared_template():
    """The whole point: a numbered template must exist in exactly one place."""
    from workflow_templates import make_notebooks

    for workflow in ("nhm", "nhf", "pest"):
        # raises ValueError on a collision between input dirs
        templates = make_notebooks.iter_workflow_templates(workflow)
        relatives = [rel for _, rel in templates]
        assert len(relatives) == len(set(relatives)), workflow


def test_collision_between_input_dirs_is_an_error(tmp_path, monkeypatch):
    """A workflow directory reintroducing a shared name must fail loudly, not
    silently shadow common/ -- that is how the duplication crept back."""
    from workflow_templates import make_notebooks

    a, b = tmp_path / "a", tmp_path / "b"
    for d in (a, b):
        d.mkdir()
        (d / "0_workspace_setup.py").write_text("# %%\n", encoding="utf-8")
    monkeypatch.setitem(make_notebooks.WORKFLOW_INPUT_DIRS, "probe", (a, b))

    with pytest.raises(ValueError, match="must be the only one"):
        make_notebooks.iter_workflow_templates("probe")


def test_every_workflow_renders_the_shared_set():
    from workflow_templates import make_notebooks

    for workflow in ("nhm", "nhf"):
        rendered = {
            rel.with_suffix("").name
            for _, rel in make_notebooks.iter_workflow_templates(workflow)
        }
        missing = [n for n in SHARED_TEMPLATES if n not in rendered]
        assert not missing, f"{workflow} does not render {missing}"


def test_nhf_keeps_its_own_templates():
    """Unification must not have swallowed nhf's 28 unique templates."""
    from workflow_templates import make_notebooks

    nhf = {
        rel.with_suffix("").name
        for _, rel in make_notebooks.iter_workflow_templates("nhf")
    }
    for name in (
        "2_model_hydrofabric_visualization_FMI",
        "Fetch_poi_supplimental_information",
        "gf_params_parse",
    ):
        assert name in nhf, name
    assert len(nhf) > len(SHARED_TEMPLATES)


@pytest.mark.parametrize("name", SHARED_TEMPLATES)
def test_no_template_hardcodes_a_workflow_root(name):
    """A shared template cannot know which workflow it is rendering for."""
    source = _template(name)
    code = "\n".join(
        line for line in source.splitlines()
        if line.strip() and not line.strip().startswith("#")
    )
    assert "resolve_workflow_root(" in code, f"{name} does not derive its root"
    assert "parents[2]" not in code, f"{name} still hardcodes the repo root"
    assert "nhf_assist" not in code, f"{name} still hardcodes the nhf root"


@pytest.mark.parametrize("name", SHARED_TEMPLATES)
def test_shared_templates_import_only_unified_helpers(name):
    """Imports must go to assist.common, with no exceptions.

    `streamflow_postprocess` used to be one: nhm-only, no nhf counterpart, so
    it was never part of the nine-pair unification. Sharing the templates made
    that untenable -- notebook 4 was a shared template reaching into a
    per-fabric package -- so it moved to assist.common too and this check is
    now absolute.
    """
    allowed: set[str] = set()
    offenders = []
    for node in ast.walk(ast.parse(_template(name))):
        if isinstance(node, ast.ImportFrom) and node.module:
            module = node.module
        elif isinstance(node, ast.Import):
            module = node.names[0].name
        else:
            continue
        if module.startswith(("assist.nhm.", "assist.nhf.")) and module not in allowed:
            offenders.append(f"line {node.lineno}: {module}")
    assert not offenders, f"{name} imports per-fabric modules: {offenders}"


class TestResolveWorkflowRoot:
    """The resolver that replaced every hardcoded root."""

    def test_each_workflow_maps_to_its_own_root(self):
        """Generated notebooks live at <project>/notebooks/<workflow>, so the
        workflow is read off the directory name. Only nhf's data root differs
        from the repo root."""
        from assist.workspace.bridge import resolve_repo_root, resolve_workflow_root

        repo = resolve_repo_root()
        expected = {"nhm": repo, "nhf": repo / "nhf_assist", "pest": repo}
        for workflow, root in expected.items():
            assert resolve_workflow_root(workflow) == root, workflow
            probe = pathlib.Path("/tmp/ws/proj/notebooks") / workflow
            assert resolve_workflow_root(cwd=probe) == root, workflow

    def test_the_legacy_in_repo_layout_still_resolves(self):
        """main removed the in-repo notebooks/ dirs, but a workspace left over
        from before the change must still resolve to the right root."""
        from assist.workspace.bridge import resolve_repo_root, resolve_workflow_root

        repo = resolve_repo_root()
        assert resolve_workflow_root(cwd=repo / "notebooks") == repo
        assert (
            resolve_workflow_root(cwd=repo / "nhf_assist" / "notebooks")
            == repo / "nhf_assist"
        )

    def test_nhf_root_is_not_the_repo_root(self):
        """The bug this exists to prevent: resolve_nhm_runtime_paths reports the
        repo root from nhf's notebook dir, which would send nhf's notebooks to
        the nhm workspace's config and model directory."""
        from assist.workspace.bridge import resolve_repo_root, resolve_workflow_root
        from assist.workspace.service import resolve_nhm_runtime_paths

        repo = resolve_repo_root()
        nhf_notebooks = repo / "nhf_assist" / "notebooks"

        assert resolve_workflow_root(cwd=nhf_notebooks) == repo / "nhf_assist"

        confused = resolve_nhm_runtime_paths(
            "Walla_Walla", cwd=str(nhf_notebooks), env=os.environ
        )
        assert confused["config_root"] == repo, (
            "resolve_nhm_runtime_paths became workflow-aware; the shared "
            "templates could use it directly and this note is stale"
        )

    def test_falls_back_to_the_repo_root_outside_a_notebooks_dir(self):
        from assist.workspace.bridge import resolve_repo_root, resolve_workflow_root

        repo = resolve_repo_root()
        assert resolve_workflow_root(cwd=repo) == repo
        assert resolve_workflow_root(cwd=repo / "src") == repo

    def test_an_unrecognisable_cwd_falls_back_to_the_repo_root(self, tmp_path):
        """Nothing in the path names a workflow, so the repo root is the only
        safe answer -- which is what every non-nhf workflow uses anyway."""
        from assist.workspace.bridge import (
            infer_workflow,
            resolve_repo_root,
            resolve_workflow_root,
        )

        odd = tmp_path / "somewhere" / "else"
        odd.mkdir(parents=True)
        assert infer_workflow(odd) is None
        assert resolve_workflow_root(cwd=odd) == resolve_repo_root()


def test_streamflow_postprocess_moved_with_a_working_shim():
    """It had no nhf counterpart, so it was never part of the nine-pair
    unification; it moved anyway once a shared template imported it."""
    import assist.common.streamflow_postprocess as impl
    import assist.nhm.streamflow_postprocess as shim

    assert shim.subset_seg_outflow_to_poi_gages is impl.subset_seg_outflow_to_poi_gages

    shim_source = (
        REPO_ROOT / "src/assist/nhm/streamflow_postprocess.py"
    ).read_text(encoding="utf-8")
    functions = [
        node.name
        for node in ast.parse(shim_source).body
        if isinstance(node, ast.FunctionDef)
    ]
    assert not functions, f"the shim still defines {functions}"
