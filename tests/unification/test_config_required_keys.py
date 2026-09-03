"""A malformed config must fail loudly in the loader, not silently downstream."""
import pathlib as pl

import pytest
import yaml

from assist.common.assist_utilities import (
    OPTIONAL_CONFIG_KEYS,
    REQUIRED_CONFIG_KEYS,
    load_subdomain_config,
)

from tests.unification.fabrics import COMPLETE_CONFIG


def _write(tmp_path: pl.Path, cfg: dict) -> pl.Path:
    (tmp_path / "subdomain_config.yaml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return tmp_path


def test_a_complete_config_loads():
    assert REQUIRED_CONFIG_KEYS
    assert "resource_gages_file" in OPTIONAL_CONFIG_KEYS


def test_complete_config_round_trips(tmp_path):
    cfg = load_subdomain_config(_write(tmp_path, COMPLETE_CONFIG))
    assert cfg["subdomain"] == "TestBasin"
    assert isinstance(cfg["out_dir"], pl.Path)


def test_missing_required_key_raises_naming_it(tmp_path):
    broken = {k: v for k, v in COMPLETE_CONFIG.items() if k != "out_dir"}
    with pytest.raises(KeyError, match="out_dir"):
        load_subdomain_config(_write(tmp_path, broken))


def test_error_names_every_missing_key_at_once(tmp_path):
    broken = {k: v for k, v in COMPLETE_CONFIG.items()
              if k not in ("out_dir", "nc_files_dir", "html_maps_dir")}
    with pytest.raises(KeyError) as exc:
        load_subdomain_config(_write(tmp_path, broken))
    message = str(exc.value)
    for key in ("out_dir", "nc_files_dir", "html_maps_dir"):
        assert key in message


def test_optional_key_absent_is_tolerated(tmp_path):
    cfg = load_subdomain_config(_write(tmp_path, COMPLETE_CONFIG))
    assert cfg["resource_gages_file"] is None


def test_waterdata_only_config_also_loads(tmp_path):
    cfg = dict(COMPLETE_CONFIG)
    del cfg["nwis_gages_file"], cfg["nwis_gage_nobs_min"]
    cfg["waterdata_gages_file"] = "/tmp/m/WaterDataGages.csv"
    cfg["waterdata_gage_nobs_min"] = 400
    loaded = load_subdomain_config(_write(tmp_path, cfg))
    assert loaded["nwis_gages_file"] == pl.Path("/tmp/m/WaterDataGages.csv")
    assert loaded["waterdata_gage_nobs_min"] == 400
