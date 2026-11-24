"""Per-basin target choices: reading the YAML, choosing runoff members, rebuilding the ensemble."""
import numpy as np
import pandas as pd
import pytest
import xarray as xr

from assist.pest.basin_target_choices import (
    BASIN_CHOICES_FILENAME,
    RUNOFF_MEMBERS,
    available_runoff_members,
    basin_choices_path,
    rebuild_runoff_ensemble,
    runoff_choice,
)

SANDY = """
SandyRiver:
  runoff:
    drop_members: [gldas_noah_v21_monthly]
    reason: >-
      It was discovered during calibration that this
      creates a better value for the mean.
    date: "2026-11-23"
"""


def _write(tmp_path, text):
    path = tmp_path / BASIN_CHOICES_FILENAME
    path.write_text(text, encoding="utf-8")
    return path


def _ds(seed=0, nt=6, nh=4):
    """A delivered-style runoff dataset built from three members."""
    rng = np.random.default_rng(seed)
    time = pd.date_range("2000-01-01", periods=nt, freq="MS")
    coords = {"time": time, "hru_id": np.arange(1, nh + 1)}
    m = {k: rng.uniform(1, 10, (nt, nh)).astype("float32") for k in RUNOFF_MEMBERS}
    m["gldas_noah_v21_monthly"][0, 0] = np.nan  # one missing member value
    st = np.stack([m[k] for k in RUNOFF_MEMBERS])
    ds = xr.Dataset({k: (("time", "hru_id"), v) for k, v in m.items()}, coords=coords)
    ds["ensemble_mean"] = (("time", "hru_id"), np.nanmean(st, 0).astype("float32"), {"units": "cfs"})
    ds["lower_bound"] = (("time", "hru_id"), np.nanmin(st, 0).astype("float32"))
    ds["upper_bound"] = (("time", "hru_id"), np.nanmax(st, 0).astype("float32"))
    ds["ensemble_std"] = (("time", "hru_id"), np.nanstd(st, 0).astype("float32"))
    ds["n_sources"] = (("time", "hru_id"), np.isfinite(st).sum(0).astype("int8"))
    return ds


def test_path_comes_from_project_config(tmp_path):
    assert basin_choices_path({"project_config_root": tmp_path}) == tmp_path / BASIN_CHOICES_FILENAME
    assert basin_choices_path(None) is None


def test_no_file_or_no_entry_keeps_every_member(tmp_path):
    assert runoff_choice(None, "SandyRiver").members == list(RUNOFF_MEMBERS)
    assert runoff_choice(tmp_path / "missing.yaml", "SandyRiver").changed is False
    path = _write(tmp_path, SANDY)
    other = runoff_choice(path, "OtherBasin")
    assert other.members == list(RUNOFF_MEMBERS) and not other.changed


def test_sandyriver_drops_gldas_and_keeps_the_reason(tmp_path):
    c = runoff_choice(_write(tmp_path, SANDY), "SandyRiver")
    assert c.members == ["era5_land", "mwbm_climgrid"]
    assert c.dropped == ["gldas_noah_v21_monthly"]
    assert c.reason == ("It was discovered during calibration that this creates a "
                        "better value for the mean.")
    assert c.date == "2026-11-23"


def test_unknown_member_is_an_error_not_silently_kept(tmp_path):
    path = _write(tmp_path, "SandyRiver:\n  runoff:\n    drop_members: [gldas]\n")
    with pytest.raises(ValueError, match="not runoff members"):
        runoff_choice(path, "SandyRiver")


def test_dropping_every_member_is_an_error(tmp_path):
    path = _write(tmp_path, "B:\n  runoff:\n    drop_members: [%s]\n" % ", ".join(RUNOFF_MEMBERS))
    with pytest.raises(ValueError, match="every runoff member"):
        runoff_choice(path, "B")


def test_rebuild_with_all_members_reproduces_the_delivered_file():
    ds = _ds()
    c = runoff_choice(None, "x", available=available_runoff_members(ds))
    assert rebuild_runoff_ensemble(ds, c) is ds  # nothing dropped: unchanged


def test_rebuild_without_gldas_matches_a_two_member_ensemble(tmp_path):
    ds = _ds()
    c = runoff_choice(_write(tmp_path, SANDY), "SandyRiver")
    out = rebuild_runoff_ensemble(ds, c)
    st = np.stack([ds["era5_land"].values, ds["mwbm_climgrid"].values])
    np.testing.assert_allclose(out["ensemble_mean"], st.mean(0), rtol=1e-6)
    np.testing.assert_allclose(out["lower_bound"], st.min(0))
    np.testing.assert_allclose(out["upper_bound"], st.max(0))
    np.testing.assert_allclose(out["ensemble_std"], st.std(0, ddof=0), rtol=1e-5)
    assert (out["n_sources"] == 2).all()
    # dtype, dims and attributes are kept, and the choice is stamped on
    assert out["ensemble_mean"].dtype == ds["ensemble_mean"].dtype
    assert out["ensemble_mean"].dims == ds["ensemble_mean"].dims
    assert out["ensemble_mean"].attrs["units"] == "cfs"
    assert out["ensemble_mean"].attrs["members_used"] == "era5_land,mwbm_climgrid"
    assert out.attrs["members_dropped"] == "gldas_noah_v21_monthly"
    # the members themselves stay in the file, and the input is not modified
    assert "gldas_noah_v21_monthly" in out
    assert "members_used" not in ds["ensemble_mean"].attrs


def test_rebuild_std_is_nan_with_fewer_than_two_members():
    ds = _ds()
    ds["mwbm_climgrid"][0, 1] = np.nan
    c = runoff_choice(None, "x")
    c.members, c.dropped = ["era5_land", "mwbm_climgrid"], ["gldas_noah_v21_monthly"]
    out = rebuild_runoff_ensemble(ds, c)
    assert int(out["n_sources"][0, 1]) == 1
    assert np.isnan(out["ensemble_std"][0, 1])
    assert float(out["ensemble_mean"][0, 1]) == pytest.approx(float(ds["era5_land"][0, 1]))
