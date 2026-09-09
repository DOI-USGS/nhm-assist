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
    mkdir_call = "waterdata_gages_file.parent.mkdir(parents=True, exist_ok=True)"
    to_csv_call = "out_gage_info.to_csv(waterdata_gages_file, index=False)"
    assert mkdir_call in source
    assert source.index(mkdir_call) < source.index(to_csv_call)


def test_geos_safe_clip_survived_the_terminology_pass():
    """nhm-only hardening that adopting nhf's side would have deleted.

    Strengthened after the New England subdomain still failed here: repairing
    only the mask is not enough, because clip() intersects the mask union
    against the *target's* raw geometry, and HUC2.shp ships invalid polygons.
    `_safe_clip` repairs both sides.
    """
    import assist.common.sf_data_retrieval as common

    for name in ("create_OR_sf_df", "create_ecy_sf_df"):
        source = inspect.getsource(getattr(common, name))
        assert "_safe_clip(huc2_gdf, hru_gdf)" in source, (
            f"{name} lost the GEOS-safe clip"
        )


def test_safe_clip_repairs_both_operands():
    """The bug: HUC2 01 and 02 self-intersect near -72.016, 41.315, so every
    subdomain overlapping them raised GEOSException while domains elsewhere
    passed regardless of their own invalid rings."""
    import geopandas as gpd
    from shapely.geometry import Polygon

    import assist.common.sf_data_retrieval as common

    bowtie = Polygon([(0, 0), (2, 2), (2, 0), (0, 2)])  # self-intersecting
    square = Polygon([(0, 0), (0, 2), (2, 2), (2, 0)])

    target = gpd.GeoDataFrame({"id": [1]}, geometry=[bowtie], crs=4326)
    mask = gpd.GeoDataFrame({"id": [1]}, geometry=[bowtie], crs=4326)

    # an invalid target is what the mask-only helper could not save
    assert not target.geometry.is_valid.all()
    clipped = common._safe_clip(target, mask)
    assert len(clipped) >= 0  # the point is that it does not raise

    # and a valid pair still clips normally
    ok = common._safe_clip(
        gpd.GeoDataFrame({"id": [1]}, geometry=[square], crs=4326), mask
    )
    assert len(ok) == 1


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
        "src/workflow_templates/common/1_create_streamflow_observations.py", encoding="utf-8"
    ).read()
    assert "waterdata_df=" in source
    assert "NWIS_df=" not in source
