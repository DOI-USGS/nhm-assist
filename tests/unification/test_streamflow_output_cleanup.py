import pathlib as pl

from assist.common.assist_utilities import delete_notebook_output_files


def test_cleanup_removes_legacy_and_canonical_waterdata_gage_caches(tmp_path):
    notebook_output_dir = tmp_path / "notebook_output_files"
    for subfolder in ("Folium_maps", "html_maps", "html_plots", "nc_files"):
        (notebook_output_dir / subfolder).mkdir(parents=True)

    model_dir = tmp_path / "model"
    (model_dir / "metadata").mkdir(parents=True)
    legacy_cache = model_dir / "WaterDataGages.csv"
    canonical_cache = model_dir / "metadata" / "WaterDataGages.csv"
    legacy_cache.write_text("legacy", encoding="utf-8")
    canonical_cache.write_text("canonical", encoding="utf-8")

    delete_notebook_output_files(
        notebook_output_dir=notebook_output_dir,
        model_dir=model_dir,
    )

    assert not legacy_cache.exists()
    assert not canonical_cache.exists()
    assert model_dir.is_dir()
    assert (model_dir / "metadata").is_dir()
