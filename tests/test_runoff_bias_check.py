import unittest

import numpy as np
import pandas as pd
import xarray as xr

from assist.pest import runoff_bias_check as rbc

# Network (1-based segments): seg 3 -> 2 -> 1 (outlet). Gages: A on seg 2, B on seg 1.
# HRUs (nhm_id 101..104) drain to segments 3, 2, 1, 1.
PARAMS = {
    "tosegment": np.array([0, 1, 2]),
    "hru_segment": np.array([3, 2, 1, 1]),
    "poi_gage_segment": np.array([2, 1]),
    "poi_gage_id": np.array(["A", "B"]),
    "nhm_id": np.array([101, 102, 103, 104]),
}


def _runoff(hru_ids, value=10.0, months=3):
    t = pd.date_range("2000-01-01", periods=months, freq="MS")
    return xr.DataArray(
        np.full((months, len(hru_ids)), value),
        coords={"time": t, "hru_id": hru_ids},
        dims=("time", "hru_id"),
    )


class RunoffBiasCheckTests(unittest.TestCase):
    def test_sum_is_over_all_upstream_hrus_nested(self):
        sums, cov = rbc.hru_sum_by_gage(_runoff([101, 102, 103, 104]), ["A", "B"], PARAMS)
        self.assertTrue((sums["A"] == 20.0).all())  # HRUs 101, 102
        self.assertTrue((sums["B"] == 40.0).all())  # all four, includes A's HRUs
        self.assertEqual(list(cov["status"]), ["ok", "ok"])

    def test_partial_hru_coverage_is_skipped_by_default_and_kept_when_lowered(self):
        runoff = _runoff([102, 103, 104])  # 101 missing, upstream of both gages
        sums, cov = rbc.hru_sum_by_gage(runoff, ["A", "B"], PARAMS)
        self.assertTrue(sums.empty)
        self.assertTrue(cov["status"].str.startswith("skipped").all())
        sums, cov = rbc.hru_sum_by_gage(runoff, ["A"], PARAMS, min_hru_coverage=0.5)
        self.assertTrue((sums["A"] == 10.0).all())
        self.assertEqual(cov.loc[0, "status"], "ok (partial HRU coverage)")

    def test_unknown_gage_is_reported(self):
        _, cov = rbc.hru_sum_by_gage(_runoff([101]), ["Z"], PARAMS)
        self.assertIn("not in parameter file", cov.loc[0, "status"])

    def test_nan_hru_month_gives_nan_sum(self):
        r = _runoff([101, 102])
        r[1, 0] = np.nan
        sums, _ = rbc.hru_sum_by_gage(r, ["A"], PARAMS)
        self.assertTrue(np.isnan(sums["A"].iloc[1]))

    def test_gage_monthly_requires_enough_valid_days(self):
        t = pd.date_range("2000-01-01", "2000-02-29", freq="D")
        v = np.full(len(t), 5.0)
        v[:20] = np.nan  # January: 11 of 31 days valid
        da = xr.DataArray(v[None, :], coords={"poi_gage_id": ["A"], "time": t},
                          dims=("poi_gage_id", "time"))
        m = rbc.gage_monthly_cfs(da, 0.8)
        self.assertTrue(np.isnan(m.loc["2000-01-01", "A"]))
        self.assertEqual(m.loc["2000-02-01", "A"], 5.0)

    def test_comparison_and_bias(self):
        idx = pd.date_range("2000-01-01", periods=3, freq="MS")
        obs = pd.DataFrame({"A": [20.0, 20.0, np.nan]}, index=idx)
        hru = pd.DataFrame({"A": [10.0, 10.0, 10.0]}, index=idx)
        comp = rbc.build_comparison(obs, hru)
        self.assertEqual(len(comp), 2)  # NaN month dropped
        self.assertTrue((comp["diff"] == -10.0).all())
        o = rbc.overall_bias(comp).loc["A"]
        self.assertAlmostEqual(o["pbias_pct"], -50.0)
        self.assertAlmostEqual(o["implied_factor"], 2.0)
        self.assertEqual(len(rbc.monthly_bias(comp)), 2)
        comp2 = rbc.build_comparison(obs, hru, runoff_factor=2.0)
        self.assertAlmostEqual(rbc.overall_bias(comp2).loc["A", "pbias_pct"], 0.0)


    def test_status_flags_gages_without_overlap_and_all_dropped(self):
        idx = pd.date_range("2000-01-01", periods=2, freq="MS")
        obs = pd.DataFrame({"A": [np.nan, np.nan], "B": [1.0, 1.0]}, index=idx)
        hru = pd.DataFrame({"A": [10.0, 10.0], "B": [10.0, 10.0]}, index=idx)
        cov = pd.DataFrame({"poi_gage_id": ["A", "B"], "status": ["ok", "ok"]})
        comp = rbc.build_comparison(obs, hru)
        out = rbc.add_comparison_status(cov, comp)
        self.assertTrue(out.loc[0, "status"].startswith("dropped"))
        self.assertEqual(out.loc[1, "status"], "ok")
        empty = rbc.build_comparison(obs[["A"]], hru[["A"]])
        self.assertTrue(empty.empty)
        out = rbc.add_comparison_status(cov.iloc[:1], empty)
        self.assertTrue(out.loc[0, "status"].startswith("dropped"))
        self.assertTrue(rbc.overall_bias(empty).empty)

    def test_bounds_sum_scales_with_factor_and_settings_summary(self):
        lo, _ = rbc.hru_sum_by_gage(_runoff([101, 102], 5.0), ["A"], PARAMS)
        self.assertTrue((lo["A"] == 10.0).all())
        s = rbc.settings_summary(RUNOFF_FACTOR=1.0, SHOW_BOUNDS=True)
        self.assertEqual(list(s["setting"]), ["RUNOFF_FACTOR", "SHOW_BOUNDS"])


if __name__ == "__main__":
    unittest.main()
