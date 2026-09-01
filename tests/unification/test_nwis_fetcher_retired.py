"""fetch_nwis_gage_info is retired; fetch_waterdata_gage_info is canonical."""
import pathlib as pl

import assist.common.assist_utilities as cu
import assist.nhf.nhm_assist_utilities_v2 as nhf
import assist.nhm.nhm_assist_utilities as nhm


def test_the_nwis_fetcher_is_gone():
    assert not hasattr(cu, "fetch_nwis_gage_info")
    assert not hasattr(nhm, "fetch_nwis_gage_info")
    assert not hasattr(nhf, "fetch_nwis_gage_info")


def test_the_waterdata_fetcher_remains():
    assert callable(cu.fetch_waterdata_gage_info)


def test_no_source_file_still_references_it():
    offenders = []
    for path in pl.Path("src").rglob("*.py"):
        if ".ipynb_checkpoints" in str(path):
            continue
        if "fetch_nwis_gage_info" in path.read_text(encoding="utf-8", errors="ignore"):
            offenders.append(str(path))
    assert offenders == [], f"still referenced in {offenders}"
