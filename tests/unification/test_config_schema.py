import pathlib as pl

import pytest
import yaml

from assist.common.assist_utilities import load_subdomain_config

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
