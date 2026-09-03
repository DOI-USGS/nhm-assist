"""Which hydrofabric implementation can read which fabric?

This matrix is the evidence for the plan's central claim: nhf's implementations
tolerate both fabrics and nhm's do not. If it ever stops holding, the
unification direction for this concern needs revisiting.
"""
import pytest

from tests.unification.fabrics import FABRICS, gpkg_columns

NHRU_V1_ONLY = {"nhm_id", "model_hru_idx"}
NSEG_V1 = {"nhm_seg", "model_seg_idx"}
NSEG_V2 = {"nhm_seg_id", "segment_id"}


def _skip_if_missing(key):
    if not FABRICS[key].exists():
        pytest.skip(f"{key} model not present at {FABRICS[key]}")


def test_gfv1_1_nsegment_has_nhm_seg_and_not_nhm_seg_id():
    _skip_if_missing("gfv1_1")
    cols = gpkg_columns(FABRICS["gfv1_1"], "nsegment")
    assert "nhm_seg" in cols
    assert "nhm_seg_id" not in cols


def test_gfv2_nsegment_has_nhm_seg_id_and_not_nhm_seg():
    _skip_if_missing("gfv2")
    cols = gpkg_columns(FABRICS["gfv2"], "nsegment")
    assert "nhm_seg_id" in cols
    assert "nhm_seg" not in cols, (
        "if GFv2 gained a plain nhm_seg column, nhf's rename is now a no-op "
        "and this plan's reasoning should be rechecked"
    )


def test_gfv1_1_nhru_lacks_the_v2_id_columns():
    _skip_if_missing("gfv1_1")
    cols = gpkg_columns(FABRICS["gfv1_1"], "nhru")
    assert "nhm_id" in cols
    assert "hru_id" not in cols
    assert "hru_segment" not in cols


def test_gfv2_nhru_has_both_id_families():
    _skip_if_missing("gfv2")
    cols = gpkg_columns(FABRICS["gfv2"], "nhru")
    assert {"nhm_id", "hru_id", "hru_segment"} <= cols


def test_nhf_create_hru_gdf_has_a_fabric_fallback_and_nhm_does_not():
    """Source-level guard on the claim that drives this plan's direction."""
    from tests.unification.fabrics import NHF_HF, NHM_HF, baseline_function_source

    nhf_src = baseline_function_source(NHF_HF, "create_hru_gdf")
    nhm_src = baseline_function_source(NHM_HF, "create_hru_gdf")
    assert '"hru_id" not in hru_gdb.columns' in nhf_src
    assert '"hru_id" not in' not in nhm_src


def test_nhm_create_segment_gdf_assumes_nhm_seg_exists():
    """nhm indexes on nhm_seg with no fallback, so it cannot read a GFv2 model."""
    from tests.unification.fabrics import NHM_HF, baseline_function_source

    src = baseline_function_source(NHM_HF, "create_segment_gdf")
    assert '"nhm_seg"' in src
    assert "nhm_seg_id" not in src
