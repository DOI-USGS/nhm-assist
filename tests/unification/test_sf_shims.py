"""sf_data_retrieval lives only at assist.common; the fabric shims are gone."""
import pathlib as pl

import pytest

import assist.common.sf_data_retrieval as common

EXPECTED_AT_LEAST = [
    "create_ecy_sf_df",
    "create_OR_sf_df",
    "create_sf_efc_df",
    "create_waterdata_sf_df",
    "owrd_scraper",
]


@pytest.mark.parametrize("name", EXPECTED_AT_LEAST)
def test_common_exposes_the_whole_former_shim_surface(name):
    assert callable(getattr(common, name, None)), f"{name} missing from common"


def test_dead_v2_file_is_gone():
    assert not pl.Path("src/assist/nhf/sf_data_retrieval_v2.py").exists()


def test_hardening_helpers_survived_in_common():
    assert callable(common._safe_clip_mask)
    assert callable(common._should_retry_waterdata)


def test_private_helpers_are_not_exported():
    assert not any(n.startswith("_") for n in getattr(common, "__all__", []))


def test_create_nwis_sf_df_is_gone_everywhere():
    offenders = []
    for path in pl.Path("src").rglob("*.py"):
        if ".ipynb_checkpoints" in str(path):
            continue
        if "create_nwis_sf_df" in path.read_text(encoding="utf-8", errors="ignore"):
            offenders.append(str(path))
    assert offenders == [], f"still referenced in {offenders}"
