import pathlib as pl

from assist.common.assist_utilities import delete_notebook_output_files


def _make_model(tmp_path: pl.Path) -> tuple[pl.Path, pl.Path]:
    out = tmp_path / "notebook_output_files"
    for sub in ("Folium_maps", "html_maps", "html_plots", "nc_files"):
        (out / sub).mkdir(parents=True)
        (out / sub / "stale.txt").write_text("x", encoding="utf-8")
    model = tmp_path / "model"
    (model / "metadata").mkdir(parents=True)
    (model / "default_gages.csv").write_text("a", encoding="utf-8")
    (model / "append_gages_to_param_file.csv").write_text("b", encoding="utf-8")
    (model / "metadata" / "WaterDataGages.csv").write_text("c", encoding="utf-8")
    (model / "metadata" / "fmi_gages_info.csv").write_text("PRECIOUS", encoding="utf-8")
    return out, model


def test_fmi_cache_is_never_deleted(tmp_path):
    out, model = _make_model(tmp_path)
    delete_notebook_output_files(notebook_output_dir=out, model_dir=model)
    fmi = model / "metadata" / "fmi_gages_info.csv"
    assert fmi.exists(), "fmi_gages_info.csv cannot be regenerated and must survive"
    assert fmi.read_text(encoding="utf-8") == "PRECIOUS"


def test_regenerable_files_are_deleted(tmp_path):
    out, model = _make_model(tmp_path)
    delete_notebook_output_files(notebook_output_dir=out, model_dir=model)
    assert not (model / "default_gages.csv").exists()
    assert not (model / "append_gages_to_param_file.csv").exists()
    assert not (model / "metadata" / "WaterDataGages.csv").exists()
    for sub in ("Folium_maps", "html_maps", "html_plots", "nc_files"):
        assert list((out / sub).iterdir()) == []


def test_missing_output_subfolder_does_not_raise(tmp_path):
    out, model = _make_model(tmp_path)
    for item in (out / "nc_files").iterdir():
        item.unlink()
    (out / "nc_files").rmdir()
    delete_notebook_output_files(notebook_output_dir=out, model_dir=model)
