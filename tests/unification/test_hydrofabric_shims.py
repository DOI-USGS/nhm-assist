"""hydrofabric lives only at assist.common; the fabric shims are gone."""
import pathlib as pl

import pytest

import assist.common.assist_utilities as cu
import assist.common.hydrofabric as common

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
def test_common_exposes_the_whole_former_shim_surface(name):
    assert callable(getattr(common, name, None)), f"{name} missing from common"


def test_private_gage_lookup_is_gone():
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
