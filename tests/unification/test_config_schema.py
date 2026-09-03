import ast
import pathlib as pl

import pytest
import yaml

from assist.common.assist_utilities import load_subdomain_config
from tests.unification.fabrics import COMPLETE_CONFIG as BASE
from tests.unification.harness import BASELINE_REV, REPO_ROOT, load_module_from_git


def _template_dict_file_values(template: pl.Path) -> dict[str, ast.expr]:
    """Return the literal values emitted by a notebook-0 ``dict_file``."""
    module = ast.parse(template.read_text(encoding="utf-8"))
    assignment = next(
        node
        for node in module.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "dict_file"
            for target in node.targets
        )
    )
    assert isinstance(assignment.value, ast.Dict)
    return {
        key.value: value
        for key, value in zip(assignment.value.keys, assignment.value.values)
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
    }


def _template_assignment_value(template: pl.Path, name: str) -> ast.expr:
    module = ast.parse(template.read_text(encoding="utf-8"))
    assignment = next(
        node
        for node in module.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == name
            for target in node.targets
        )
    )
    return assignment.value


def _assert_str_of_name(value: ast.expr, expected_name: str) -> None:
    assert isinstance(value, ast.Call)
    assert isinstance(value.func, ast.Name)
    assert value.func.id == "str"
    assert len(value.args) == 1
    assert isinstance(value.args[0], ast.Name)
    assert value.args[0].id == expected_name


def test_nhm_workspace_template_emits_canonical_waterdata_config():
    values = _template_dict_file_values(
        REPO_ROOT / "src/workflow_templates/nhm/0_workspace_setup.py"
    )

    assert "waterdata_gage_nobs_min" in values
    assert "waterdata_gages_file" in values
    assert "nwis_gage_nobs_min" not in values
    assert "nwis_gages_file" not in values
    assert isinstance(values["waterdata_gage_nobs_min"], ast.Name)
    assert values["waterdata_gage_nobs_min"].id == "waterdata_gage_nobs_min"
    _assert_str_of_name(values["waterdata_gages_file"], "waterdata_gages_file")


def test_nhf_workspace_template_serializes_its_waterdata_gages_variable():
    template = REPO_ROOT / "src/workflow_templates/nhf/0_workspace_setup.py"
    variable_value = _template_assignment_value(template, "waterdata_gages_file")
    assert isinstance(variable_value, ast.BinOp)
    assert isinstance(variable_value.left, ast.Name)
    assert variable_value.left.id == "model_dir"
    assert isinstance(variable_value.op, ast.Div)
    assert isinstance(variable_value.right, ast.Constant)
    assert variable_value.right.value == "metadata/WaterDataGages.csv"

    values = _template_dict_file_values(
        template
    )

    _assert_str_of_name(values["waterdata_gages_file"], "waterdata_gages_file")


def _write(tmp_path: pl.Path, extra: dict) -> pl.Path:
    (tmp_path / "subdomain_config.yaml").write_text(
        yaml.safe_dump({**BASE, **extra}), encoding="utf-8"
    )
    return tmp_path


def test_reads_the_nhm_nwis_schema(tmp_path):
    root = _write(tmp_path, {"nwis_gages_file": "/tmp/m/NWISgages.csv",
                             "nwis_gage_nobs_min": 365})
    cfg = load_subdomain_config(root)
    assert cfg["waterdata_gages_file"] == pl.Path("/tmp/m/NWISgages.csv")
    assert cfg["waterdata_gage_nobs_min"] == 365


def test_reads_the_nhf_waterdata_schema(tmp_path):
    root = _write(tmp_path, {"waterdata_gages_file": "/tmp/m/WaterDataGages.csv",
                             "waterdata_gage_nobs_min": 400,
                             "resource_gages_file": "/tmp/m/resource_gages.csv"})
    cfg = load_subdomain_config(root)
    assert cfg["waterdata_gages_file"] == pl.Path("/tmp/m/WaterDataGages.csv")
    assert cfg["waterdata_gage_nobs_min"] == 400
    assert cfg["resource_gages_file"] == pl.Path("/tmp/m/resource_gages.csv")


def test_resource_gages_file_is_optional(tmp_path):
    root = _write(tmp_path, {"nwis_gages_file": "/tmp/m/NWISgages.csv",
                             "nwis_gage_nobs_min": 365})
    assert load_subdomain_config(root)["resource_gages_file"] is None


def test_missing_config_raises_actionable_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="0_workspace_setup"):
        load_subdomain_config(tmp_path)


# Regression guard: both baselines wrapped 14 keys in pl.Path(). A key left as a
# raw str breaks every consumer that does `config[key] / "something"`.
PATH_KEYS = [
    "Folium_maps_dir", "model_dir", "param_filename", "gages_file",
    "default_gages_file", "output_netcdf_filename", "waterdata_gages_file",
    "NHM_dir", "out_dir", "notebook_output_dir", "html_maps_dir",
    "html_plots_dir", "nc_files_dir",
]


def test_every_path_key_becomes_a_Path(tmp_path):
    extra = {k: f"/tmp/m/{k}" for k in PATH_KEYS if k not in BASE}
    root = _write(tmp_path, {**extra, "nwis_gages_file": "/tmp/m/NWISgages.csv",
                             "nwis_gage_nobs_min": 365})
    cfg = load_subdomain_config(root)
    for key in PATH_KEYS:
        assert isinstance(cfg[key], pl.Path), f"{key} is {type(cfg[key]).__name__}, not Path"


# Differential regression guard for C1 (legacy nwis_* keys silently dropped)
# and C2 (start_date/end_date no longer normalized to %m/%d/%Y). Neither of
# the synthetic-fixture tests above exercises the repo's real, nhm-shaped
# config or compares against the baseline loader, which is exactly why both
# regressions shipped. Uses the repository's actual ./subdomain_config.yaml
# (nhm schema: nwis_* keys, no resource_gages_file) as the input, and the
# pre-unification nhm loader (BASELINE_REV) as the oracle.
NHM_BASELINE_PATH = "src/assist/nhm/nhm_assist_utilities.py"


@pytest.mark.skipif(
    not (REPO_ROOT / "subdomain_config.yaml").exists(),
    reason="repository's real ./subdomain_config.yaml is not present",
)
def test_matches_the_baseline_nhm_loader_on_a_legacy_config(tmp_path):
    """The new loader's output must be a superset of the baseline nhm
    loader's output, with every shared key equal.

    This runs on a legacy (``nwis_*``) config rather than the repo's live
    ``subdomain_config.yaml``: notebook 0 now writes the canonical WaterData
    schema, which the baseline loader raises ``KeyError`` on by design. A
    legacy config is the only input both loaders can read, so it is the only
    input on which parity is a meaningful claim -- and backward compatibility
    with exactly this shape is what the alias back-fill exists to provide.
    """
    baseline = load_module_from_git(
        BASELINE_REV, NHM_BASELINE_PATH, "baseline_nhm_config_schema"
    )
    (tmp_path / "subdomain_config.yaml").write_text(
        yaml.safe_dump(BASE), encoding="utf-8"
    )
    old = baseline.load_subdomain_config(tmp_path)
    new = load_subdomain_config(tmp_path)

    missing = [key for key in old if key not in new]
    assert not missing, (
        f"keys present in the baseline loader but missing from the new "
        f"loader: {missing}"
    )

    mismatched = {
        key: (old[key], new[key]) for key in old if new[key] != old[key]
    }
    assert not mismatched, (
        f"keys differ between the baseline loader and the new loader: "
        f"{mismatched}"
    )


def test_new_loader_reads_the_repos_live_config():
    """Convention-agnostic smoke test: whatever schema the live config is in,
    the unified loader must read it. Replaces the baseline-parity check that
    used to run here, which the WaterData default made impossible."""
    config = load_subdomain_config(REPO_ROOT)
    for key in ("subdomain", "model_dir", "start_date", "end_date"):
        assert key in config, f"{key} missing from the live config"
    # both spellings resolve no matter which one the yaml was written in
    assert config["waterdata_gages_file"] == config["nwis_gages_file"]
    assert config["waterdata_gage_nobs_min"] == config["nwis_gage_nobs_min"]
