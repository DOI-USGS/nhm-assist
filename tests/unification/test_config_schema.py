import pathlib as pl

import pytest
import yaml

from assist.common.assist_utilities import load_subdomain_config
from tests.unification.harness import BASELINE_REV, REPO_ROOT, load_module_from_git

BASE = {
    "Folium_maps_dir": "/tmp/fm",
    "model_dir": "/tmp/m",
    "param_filename": "/tmp/m/myparam.param",
    "gages_file": "/tmp/m/gages.csv",
    "default_gages_file": "/tmp/m/default_gages.csv",
    "output_netcdf_filename": "/tmp/m/out.nc",
    "control_file_name": "control.default.bandit",
    "nhru_nmonths_params": ["jh_coef"],
}


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


def test_path_keys_absent_from_yaml_become_None(tmp_path):
    root = _write(tmp_path, {"nwis_gages_file": "/tmp/m/NWISgages.csv",
                             "nwis_gage_nobs_min": 365})
    cfg = load_subdomain_config(root)
    assert cfg["out_dir"] is None
    assert cfg["nc_files_dir"] is None


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
def test_matches_the_baseline_nhm_loader_on_the_real_config():
    """The new loader's output must be a superset of the baseline nhm
    loader's output on the repo's own config, with every shared key equal.
    """
    baseline = load_module_from_git(
        BASELINE_REV, NHM_BASELINE_PATH, "baseline_nhm_config_schema"
    )
    old = baseline.load_subdomain_config(REPO_ROOT)
    new = load_subdomain_config(REPO_ROOT)

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
