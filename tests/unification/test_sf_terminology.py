"""WaterData naming (spec decision 7) with nhm's robustness intact."""
import inspect
import pathlib as pl


def test_create_sf_efc_df_takes_waterdata_df_not_nwis_df():
    import assist.common.sf_data_retrieval as common

    params = inspect.signature(common.create_sf_efc_df).parameters
    assert "waterdata_df" in params
    assert "NWIS_df" not in params


def test_create_waterdata_sf_df_uses_the_waterdata_fetcher_and_metadata_path():
    import assist.common.sf_data_retrieval as common

    source = inspect.getsource(common.create_waterdata_sf_df)
    assert "fetch_waterdata_gage_info" in source
    assert "fetch_nwis_gage_info" not in source
    assert 'metadata/WaterDataGages.csv' in source
    assert "waterdata_cache.nc" in source


def test_geos_safe_clip_survived_the_terminology_pass():
    """nhm-only hardening that adopting nhf's side would have deleted."""
    import assist.common.sf_data_retrieval as common

    for name in ("create_OR_sf_df", "create_ecy_sf_df"):
        source = inspect.getsource(getattr(common, name))
        assert "_safe_clip_mask(hru_gdf)" in source, f"{name} lost the GEOS-safe clip"


def test_retry_and_stagger_survived():
    import assist.common.sf_data_retrieval as common

    batch = inspect.getsource(common.fetch_daily_discharge_batch)
    assert "_should_retry_waterdata" in batch
    assert "max_retries" in batch
    wd = inspect.getsource(common.create_waterdata_sf_df)
    assert "_chunked" in wd


def test_common_has_no_workflow_package_imports():
    """common/ must not import from assist.nhm or assist.nhf."""
    source = pl.Path("src/assist/common/sf_data_retrieval.py").read_text(encoding="utf-8")
    assert "from assist.nhm" not in source
    assert "from assist.nhf" not in source


def test_the_nhm_notebook_caller_was_updated():
    source = open(
        "src/workflow_templates/nhm/1_create_streamflow_observations.py", encoding="utf-8"
    ).read()
    assert "waterdata_df=" in source
    assert "NWIS_df=" not in source
