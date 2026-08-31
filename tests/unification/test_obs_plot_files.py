import inspect

import numpy as np
import pandas as pd
import xarray as xr

from assist.common.assist_utilities import make_obs_plot_files


def test_signature_keeps_the_max_workers_knob():
    params = inspect.signature(make_obs_plot_files).parameters
    assert params["max_workers"].default == 8
    for required in ("start_date", "end_date", "gages_df", "xr_streamflow",
                     "Folium_maps_dir"):
        assert required in params


def _tiny_streamflow(gage_ids):
    time = pd.date_range("2020-01-01", periods=10, freq="D")
    data = np.arange(len(time) * len(gage_ids), dtype=float).reshape(
        len(time), len(gage_ids)
    )
    return xr.Dataset(
        {"discharge": (("time", "poi_gage_id"), data)},
        coords={"time": time, "poi_gage_id": list(gage_ids)},
    )


def test_writes_one_plot_file_per_gage(tmp_path):
    gage_ids = ["12345678", "87654321"]
    gages_df = pd.DataFrame(index=pd.Index(gage_ids, name="poi_gage_id"))
    make_obs_plot_files(
        start_date="01/01/2020",
        end_date="01/10/2020",
        gages_df=gages_df,
        xr_streamflow=_tiny_streamflow(gage_ids),
        Folium_maps_dir=tmp_path,
        max_workers=2,
    )
    for gage in gage_ids:
        assert (tmp_path / f"{gage}_streamflow_obs.txt").exists()


def test_existing_plot_files_are_not_regenerated(tmp_path):
    gage_ids = ["12345678"]
    marker = tmp_path / "12345678_streamflow_obs.txt"
    marker.write_text("ORIGINAL", encoding="utf-8")
    gages_df = pd.DataFrame(index=pd.Index(gage_ids, name="poi_gage_id"))
    make_obs_plot_files(
        start_date="01/01/2020",
        end_date="01/10/2020",
        gages_df=gages_df,
        xr_streamflow=_tiny_streamflow(gage_ids),
        Folium_maps_dir=tmp_path,
        max_workers=2,
    )
    assert marker.read_text(encoding="utf-8") == "ORIGINAL"


def test_copy_is_ast_identical_to_the_nhf_baseline():
    """Guard against a transcription slip during the verbatim copy."""
    import ast

    from tests.unification.harness import BASELINE_REV, load_module_from_git

    nhf = load_module_from_git(
        BASELINE_REV,
        "src/assist/nhf/nhm_assist_utilities_v2.py",
        "baseline_nhf_for_obs_plots",
    )
    mine = ast.dump(ast.parse(inspect.getsource(make_obs_plot_files)))
    theirs = ast.dump(ast.parse(inspect.getsource(nhf.make_obs_plot_files)))
    assert mine == theirs
