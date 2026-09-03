"""Both sf_data_retrieval shims re-export common/, and the dead _v2 file is gone."""
import pathlib as pl

import pytest

import assist.common.sf_data_retrieval as common
import assist.nhf.sf_data_retrieval_v2_1 as nhf
import assist.nhm.sf_data_retrieval as nhm

EXPECTED_AT_LEAST = [
    "create_ecy_sf_df",
    "create_OR_sf_df",
    "create_sf_efc_df",
    "create_waterdata_sf_df",
    "owrd_scraper",
]


@pytest.mark.parametrize("name", EXPECTED_AT_LEAST)
def test_both_shims_export_the_same_object(name):
    assert getattr(nhm, name) is getattr(common, name), f"nhm/{name}"
    assert getattr(nhf, name) is getattr(common, name), f"nhf/{name}"


@pytest.mark.parametrize("module", [nhm, nhf])
def test_shim_defines_no_logic(module):
    source = pl.Path(module.__file__).read_text(encoding="utf-8")
    assert "def " not in source
    assert "from assist.common.sf_data_retrieval import" in source


def test_shims_are_byte_identical():
    a = pl.Path(nhm.__file__).read_text(encoding="utf-8")
    b = pl.Path(nhf.__file__).read_text(encoding="utf-8")
    assert a == b


def test_dead_v2_file_is_gone():
    assert not pl.Path("src/assist/nhf/sf_data_retrieval_v2.py").exists()


def test_hardening_helpers_survived_in_common():
    """nhm-only robustness work that taking nhf's side would have deleted."""
    assert callable(common._safe_clip_mask)
    assert callable(common._should_retry_waterdata)


def test_private_helpers_are_not_exported():
    for module in (nhm, nhf):
        for private in ("_safe_clip_mask", "_should_retry_waterdata"):
            assert private not in (module.__all__ or [])


def test_the_hydat_template_import_is_repaired():
    """It imported create_nwis_sf_df, which no module defined — a pre-existing ImportError."""
    source = pl.Path(
        "src/workflow_templates/nhf/make_hydat_gage_resource.py"
    ).read_text(encoding="utf-8")
    assert "create_nwis_sf_df" not in source


def test_create_nwis_sf_df_is_gone_everywhere():
    offenders = []
    for path in pl.Path("src").rglob("*.py"):
        if ".ipynb_checkpoints" in str(path):
            continue
        if "create_nwis_sf_df" in path.read_text(encoding="utf-8", errors="ignore"):
            offenders.append(str(path))
    assert offenders == [], f"still referenced in {offenders}"
