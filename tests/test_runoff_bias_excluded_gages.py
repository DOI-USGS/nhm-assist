"""Runoff bias check: the project's excluded-gage list."""
import pandas as pd
import pytest

from assist.pest import runoff_bias_check as rbc


def _write(tmp_path, text):
    path = tmp_path / rbc.EXCLUDED_GAGES_FILENAME
    path.write_text(text, encoding="utf-8")
    return path


def test_path_comes_from_project_config(tmp_path):
    assert rbc.excluded_gages_path({"project_config_root": tmp_path}) == (
        tmp_path / rbc.EXCLUDED_GAGES_FILENAME
    )
    assert rbc.excluded_gages_path(None) is None


def test_missing_file_gives_an_empty_list(tmp_path):
    for path in (None, tmp_path / "nope.csv"):
        df = rbc.read_excluded_gages(path)
        assert df.empty and list(df.columns) == list(rbc.EXCLUDED_GAGES_COLUMNS)


def test_reads_ids_as_text_and_skips_comments(tmp_path):
    path = _write(tmp_path, (
        "# a comment line\n"
        "poi_gage_id,child_domain,reason,date\n"
        "14138950,SandyRiver,Quality of the observations,2026-11-23\n"
        " 01234567 , Other , short record ,\n"
    ))
    df = rbc.read_excluded_gages(path)
    assert df["poi_gage_id"].tolist() == ["14138950", "01234567"]
    assert df.loc[1, "reason"] == "short record"
    assert df.loc[1, "date"] == ""


def test_child_domain_and_date_are_optional(tmp_path):
    df = rbc.read_excluded_gages(_write(tmp_path, "poi_gage_id,reason\n14138950,bad\n"))
    assert df.loc[0, "child_domain"] == "" and df.loc[0, "reason"] == "bad"


def test_missing_required_column_is_an_error(tmp_path):
    with pytest.raises(ValueError, match="missing column"):
        rbc.read_excluded_gages(_write(tmp_path, "gage,reason\n1,x\n"))


def test_duplicate_gage_is_an_error(tmp_path):
    with pytest.raises(ValueError, match="more than once"):
        rbc.read_excluded_gages(_write(tmp_path, "poi_gage_id,reason\n1,x\n1,y\n"))


def test_calibration_report_names_the_exclusion():
    comp = pd.DataFrame({
        "poi_gage_id": ["A"] * 12 + ["B"] * 12,
        "gage_obs": 1.0, "hru_sum": 1.0, "diff": 0.0,
    })
    coverage = pd.DataFrame({"poi_gage_id": ["A", "B"], "status": ["ok", "ok"]})
    comp_cal, report = rbc.select_calibration_gages(
        comp, ["A", "B"], coverage, 12, excluded={"B": "Quality of the observations"}
    )
    assert comp_cal["poi_gage_id"].unique().tolist() == ["A"]
    status = report.set_index("poi_gage_id")["status"]
    assert status["A"] == "used"
    assert status["B"].startswith("excluded: on runoff_bias_excluded_gages.csv")
    assert "Quality of the observations" in status["B"]


def test_calibration_report_unchanged_without_exclusions():
    comp = pd.DataFrame({"poi_gage_id": ["A"] * 12, "gage_obs": 1.0, "hru_sum": 1.0, "diff": 0.0})
    coverage = pd.DataFrame({"poi_gage_id": ["A"], "status": ["ok"]})
    _, r1 = rbc.select_calibration_gages(comp, ["A"], coverage, 12)
    _, r2 = rbc.select_calibration_gages(comp, ["A"], coverage, 12, excluded={})
    pd.testing.assert_frame_equal(r1, r2)
