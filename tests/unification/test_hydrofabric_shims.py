"""Both hydrofabric shims re-export common/, and the private gage lookup is gone."""
import ast
import pathlib as pl

import pytest

import assist.common.assist_utilities as cu
import assist.common.hydrofabric as common
import assist.nhf.nhm_hydrofabric_v2 as nhf
import assist.nhm.nhm_hydrofabric as nhm

EXPECTED_AT_LEAST = [
    "create_default_gages_file",
    "create_hru_gdf",
    "create_poi_df",
    "create_segment_gdf",
    "evaluate_and_fix_nhru_geometry",
    "make_hf_map_elements",
    "read_gages_file",
]


@pytest.mark.parametrize("name", EXPECTED_AT_LEAST)
def test_both_shims_export_the_same_object(name):
    assert getattr(nhm, name) is getattr(common, name), f"nhm/{name}"
    assert getattr(nhf, name) is getattr(common, name), f"nhf/{name}"


@pytest.mark.parametrize("module", [nhm, nhf])
def test_shim_defines_no_logic(module):
    source = pl.Path(module.__file__).read_text(encoding="utf-8")
    assert "def " not in source
    assert "from assist.common.hydrofabric import" in source


def test_private_gage_lookup_is_gone():
    """Its only caller was nhm_hydrofabric, which is now a shim."""
    assert not hasattr(cu, "find_missing_gage_metadata")
    assert not hasattr(cu, "_find_missing_gage_metadata")


def test_no_source_file_still_references_it():
    hits = []
    for path in pl.Path("src").rglob("*.py"):
        if ".ipynb_checkpoints" in str(path):
            continue
        if "find_missing_gage_metadata" in path.read_text(encoding="utf-8", errors="ignore"):
            hits.append(str(path))
    assert hits == [], f"still referenced in {hits}"


def test_canonical_gage_lookup_still_present():
    assert callable(cu.find_missing_gage_info)


def test_shims_are_byte_identical():
    a = pl.Path(nhm.__file__).read_text(encoding="utf-8")
    b = pl.Path(nhf.__file__).read_text(encoding="utf-8")
    assert a == b
