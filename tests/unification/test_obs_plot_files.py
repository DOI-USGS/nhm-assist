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


# The one deliberate departure from nhf's baseline: plotly express reads the
# global default template and walks its parent/child state while building a
# figure, which is not thread-safe. Eight concurrent px.line calls
# intermittently raise ValueError("Invalid value") out of
# apply_default_cascade, which killed a cold-start nhm notebook 1 run after
# writing only 8 of its obs-plot files. Serialising figure construction fixes
# it; the surrounding parallelism (data slicing, file writes) is untouched.
INTENDED_EDITS = [
    (
        """    from concurrent.futures import ThreadPoolExecutor, as_completed
    from tqdm.auto import tqdm
""",
        """    from concurrent.futures import ThreadPoolExecutor, as_completed
    from threading import Lock

    from tqdm.auto import tqdm

    _figure_lock = Lock()
""",
    ),
    (
        """        fig = px.line(
            ds_sub_df,
            x="time",
            y="discharge",
            markers=False,
            labels={
                "discharge": "Discharge",
                "time": "Date",
            },
        )
""",
        """        with _figure_lock:
            fig = px.line(
                ds_sub_df,
                x="time",
                y="discharge",
                markers=False,
                labels={
                    "discharge": "Discharge",
                    "time": "Date",
                },
            )
""",
    ),
]


def test_copy_is_nhf_baseline_plus_only_the_thread_safety_fix():
    """Guard against a transcription slip during the verbatim copy, allowing
    only the substitutions in INTENDED_EDITS."""
    import ast

    from tests.unification.harness import BASELINE_REV, load_module_from_git

    nhf = load_module_from_git(
        BASELINE_REV,
        "src/assist/nhf/nhm_assist_utilities_v2.py",
        "baseline_nhf_for_obs_plots",
    )
    expected_source = inspect.getsource(nhf.make_obs_plot_files)
    for old_text, new_text in INTENDED_EDITS:
        assert old_text in expected_source, (
            f"nhf's baseline no longer contains {old_text[:60]!r}, so this "
            "intended-edit entry is stale and the test needs updating"
        )
        expected_source = expected_source.replace(old_text, new_text)

    mine = ast.dump(ast.parse(inspect.getsource(make_obs_plot_files)))
    theirs = ast.dump(ast.parse(expected_source))
    assert mine == theirs


def test_figure_construction_is_serialised():
    """The reason for the edit above: concurrent px.line is not thread-safe."""
    source = inspect.getsource(make_obs_plot_files)
    assert "_figure_lock = Lock()" in source
    assert "with _figure_lock:" in source
    lock_at = source.index("with _figure_lock:")
    px_at = source.index("px.line(")
    assert lock_at < px_at, "the lock must cover the px.line call"
