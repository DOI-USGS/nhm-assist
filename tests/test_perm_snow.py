"""perm_snow HRU list: reading, model selection, starting values, masks."""

import json

import numpy as np
import pandas as pd
import pytest

from assist.pest.perm_snow import (
    PERM_SNOW_FILENAME,
    hru_of_parameter,
    perm_snow_list_path,
    read_perm_snow_list,
    select_perm_snow_hrus,
    set_perm_snow_start_values,
    swe_obs_mask,
    update_parameters_json,
)


def _write(tmp_path, text):
    path = tmp_path / PERM_SNOW_FILENAME
    path.write_text(text, encoding="utf-8")
    return path


def test_list_path_comes_from_project_config(tmp_path):
    assert perm_snow_list_path({"project_config_root": tmp_path}) == (
        tmp_path / PERM_SNOW_FILENAME
    )
    assert perm_snow_list_path(None) is None


def test_missing_file_selects_nothing(tmp_path):
    sel = select_perm_snow_hrus(tmp_path / PERM_SNOW_FILENAME, [1, 2])
    assert not sel
    assert sel.selected == [] and sel.not_in_model == []
    assert not select_perm_snow_hrus(None, [1, 2])


def test_master_list_is_split_by_model_membership(tmp_path):
    path = _write(
        tmp_path,
        "hru_id,child_domain\n7305,SandyRiver\n7346,SandyRiver\n9999,OtherBasin\n",
    )
    sel = select_perm_snow_hrus(path, [7305, 7346, 1])
    assert sel.selected == [7305, 7346]
    assert sel.not_in_model == [9999]
    assert sel.child_domain[9999] == "OtherBasin"


def test_hru_listed_from_two_domains_is_kept_once(tmp_path):
    path = _write(tmp_path, "hru_id,child_domain\n7305,SandyRiver\n7305,Parent\n")
    df = read_perm_snow_list(path)
    assert df["hru_id"].tolist() == [7305]
    assert df["child_domain"].iloc[0] == "Parent, SandyRiver"


def test_bad_columns_and_ids_fail_loudly(tmp_path):
    with pytest.raises(ValueError, match="child_domain"):
        read_perm_snow_list(_write(tmp_path, "hru_id\n7305\n"))
    with pytest.raises(ValueError, match="not integers"):
        read_perm_snow_list(_write(tmp_path, "hru_id,child_domain\n73.5,Sandy\n"))


def test_start_values_set_only_at_listed_hrus_and_reported():
    nhm_id = np.array([10, 20, 30])
    tmax = np.tile(np.array([-1.0, 4.5, 0.2]), (12, 1))
    tmin = np.full((12, 3), -2.0)
    tmax.setflags(write=False)  # pywatershed hands out read-only arrays
    pars = {"nhm_id": nhm_id, "tmax_cbh_adj": tmax, "tmin_cbh_adj": tmin}
    changed = set_perm_snow_start_values(pars, [10, 20, 99])
    assert np.allclose(pars["tmax_cbh_adj"][:, :2], 4.5)
    assert np.allclose(pars["tmax_cbh_adj"][:, 2], 0.2)
    assert np.allclose(pars["tmin_cbh_adj"][:, :2], 0.0)
    assert np.allclose(pars["tmin_cbh_adj"][:, 2], -2.0)
    # HRU 20 already had tmax 4.5, so only its tmin is reported for it.
    got = set(zip(changed.parameter, changed.hru_id))
    assert got == {("tmax_cbh_adj", 10), ("tmin_cbh_adj", 10), ("tmin_cbh_adj", 20)}


def test_parameters_json_updated_in_month_by_hru_layout(tmp_path):
    path = tmp_path / "parameters.json"
    data = {
        "nhm_id": [10, 20],
        "tmax_cbh_adj": np.full((12, 2), -1.0).tolist(),
        "tmin_cbh_adj": np.full((12, 2), -3.0).tolist(),
        "other": [1, 2],
    }
    path.write_text(json.dumps(data))
    update_parameters_json(path, [20])
    out = json.loads(path.read_text())
    assert np.allclose(np.array(out["tmax_cbh_adj"])[:, 1], 4.5)
    assert np.allclose(np.array(out["tmax_cbh_adj"])[:, 0], -1.0)
    assert np.allclose(np.array(out["tmin_cbh_adj"])[:, 1], 0.0)
    assert out["other"] == [1, 2]


def test_hru_of_parameter_parses_pest_names():
    names = pd.Series(
        ["tmax_cbh_adj:hru_7305:mon_1", "soil_moist_max:hru_12", "mann_n:seg_4"]
    )
    assert hru_of_parameter(names).tolist()[:2] == [7305, 12]
    assert pd.isna(hru_of_parameter(names).iloc[2])


def test_swe_obs_mask_selects_swe_at_listed_hrus_only():
    obs = pd.DataFrame(
        {
            "obsnme": [
                "swe_monthly:2010_10_31:7305",
                "swe_monthly:2010_10_31:11834",
                "actet_mean_mon:11:7305",
            ],
            "obgnme": ["swe_monthly", "swe_monthly", "actet_mean_mon"],
        }
    )
    assert swe_obs_mask(obs, [7305]).tolist() == [True, False, False]
