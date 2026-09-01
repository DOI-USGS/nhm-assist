# tests/unification/test_carried_over.py
import inspect
import pathlib as pl

import pandas as pd
import pytest

import assist.common.assist_utilities as cu

NHF_ONLY = [
    "create_append_gages_to_param_file_v2",
    "fetch_FMI_npoigages_info",
    "fetch_non_ref_npoigages_info",
    "fetch_ref_npoigages_info",
    "fetch_waterdata_gage_info",
]
NHM_ONLY = ["make_HW_cal_level_files"]


@pytest.mark.parametrize("name", NHF_ONLY + NHM_ONLY)
def test_function_survived_unification(name):
    assert callable(getattr(cu, name)), f"{name} was lost"


def test_fmi_guard_is_preserved(tmp_path):
    """With neither the cache nor TableA2 present, return empty, do not raise."""
    model_dir = tmp_path / "model"
    (model_dir / "metadata").mkdir(parents=True)
    (tmp_path / "data_dependencies").mkdir()

    out = cu.fetch_FMI_npoigages_info(
        tmp_path, model_dir, pd.DataFrame({"poi_gage_id": ["12345678"]})
    )
    assert isinstance(out, pd.DataFrame)
    assert out.empty
    assert "flow_management_index" in out.columns
