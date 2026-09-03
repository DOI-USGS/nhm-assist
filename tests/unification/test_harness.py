import pandas as pd
import pytest

from tests.unification.harness import (
    BASELINE_REV,
    assert_frames_equivalent,
    load_module_from_git,
    normalize_ids,
)


def test_loads_a_module_out_of_git():
    mod = load_module_from_git(
        BASELINE_REV, "src/assist/nhm/nhm_assist_utilities.py", "baseline_nhm_utils"
    )
    assert hasattr(mod, "find_missing_gage_info")


def test_normalize_ids_maps_alternate_names_to_canonical():
    df = pd.DataFrame({"hru_id": [1], "hru_segment": [2], "segment_id": [3]})
    out = normalize_ids(df)
    assert list(out.columns) == ["nhm_id", "hru_segment_nhm", "nhm_seg"]


def test_normalize_ids_leaves_canonical_names_alone():
    df = pd.DataFrame({"nhm_id": [1], "poi_gage_id": ["123"]})
    assert list(normalize_ids(df).columns) == ["nhm_id", "poi_gage_id"]


def test_assert_frames_equivalent_ignores_identifier_naming():
    left = pd.DataFrame({"nhm_id": [1, 2], "value": [10, 20]})
    right = pd.DataFrame({"hru_id": [1, 2], "value": [10, 20]})
    assert_frames_equivalent(left, right)


def test_assert_frames_equivalent_still_catches_real_differences():
    left = pd.DataFrame({"nhm_id": [1, 2], "value": [10, 20]})
    right = pd.DataFrame({"nhm_id": [1, 2], "value": [10, 99]})
    with pytest.raises(AssertionError):
        assert_frames_equivalent(left, right)
