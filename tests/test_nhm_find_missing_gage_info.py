from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from assist.common import assist_utilities as nhm_assist_utilities


class FindMissingGageInfoTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.tmp_path = Path(self._tmpdir.name).resolve()
        self.root_dir = self.tmp_path / "repo"
        (self.root_dir / "data_dependencies").mkdir(parents=True)
        self.resource_file = self.tmp_path / "resource_gages.csv"
        self.poi_df = pd.DataFrame({"poi_gage_id": ["12345678"]})

    def test_returns_empty_when_no_gage_ids_provided(self):
        result = nhm_assist_utilities.find_missing_gage_metadata(
            gage_ids=[],
            poi_df=self.poi_df,
            resource_file_path=self.resource_file,
            root_dir=self.root_dir,
        )
        self.assertTrue(result.empty)
        self.assertListEqual(
            sorted(result.columns.tolist()),
            sorted(["latitude", "longitude", "poi_name", "poi_agency"]),
        )

    def test_skips_gages_already_in_resource_file(self):
        self.resource_file.write_text(
            "poi_gage_id,latitude,longitude,poi_name,poi_agency\n"
            "12345678,45.0,-122.0,Existing Gage,USGS\n",
            encoding="utf-8",
        )

        result = nhm_assist_utilities.find_missing_gage_metadata(
            gage_ids=["12345678"],
            poi_df=self.poi_df,
            resource_file_path=self.resource_file,
            root_dir=self.root_dir,
        )

        self.assertTrue(result.empty)
        # The filter must read the resource file and exclude the matching id
        # before any network fallback is attempted.
        self.assertNotIn("12345678", result.index.tolist())

    def test_finds_all_gages_in_nldi(self):
        import geopandas as gpd
        nldi_gdf = gpd.GeoDataFrame(
            {
                "poi_gage_id": ["12345678"],
                "poi_agency": ["USGS"],
                "poi_name": ["Test Gage"],
                "latitude": [45.0],
                "longitude": [-122.0],
            },
            geometry=gpd.points_from_xy([-122.0], [45.0]),
            crs="EPSG:4326",
        )

        with patch.object(
            nhm_assist_utilities,
            "_load_nldi_cached",
            return_value=nldi_gdf,
        ), patch.object(
            nhm_assist_utilities.waterdata,
            "get_monitoring_locations",
        ) as mock_wd:
            result = nhm_assist_utilities.find_missing_gage_metadata(
                gage_ids=["12345678"],
                poi_df=self.poi_df,
                resource_file_path=self.resource_file,
                root_dir=self.root_dir,
            )

        mock_wd.assert_not_called()
        self.assertEqual(len(result), 1)
        self.assertEqual(result.loc["12345678", "poi_name"], "Test Gage")
        self.assertEqual(result.loc["12345678", "latitude"], 45.0)
        self.assertEqual(result.loc["12345678", "longitude"], -122.0)
        self.assertEqual(result.loc["12345678", "poi_agency"], "USGS")

    def test_falls_back_to_waterdata_for_gages_missing_from_nldi(self):
        import geopandas as gpd
        # NLDI knows about 12345678 but NOT 87654321
        nldi_gdf = gpd.GeoDataFrame(
            {
                "poi_gage_id": ["12345678"],
                "poi_agency": ["USGS"],
                "poi_name": ["NLDI Gage"],
                "latitude": [45.0],
                "longitude": [-122.0],
            },
            geometry=gpd.points_from_xy([-122.0], [45.0]),
            crs="EPSG:4326",
        )
        # WaterData returns the second gage
        wd_df = pd.DataFrame(
            {
                "monitoring_location_id": ["USGS-87654321"],
                "monitoring_location_name": ["WaterData Gage"],
                "agency_code": ["USGS"],
                "latitude": [46.0],
                "longitude": [-123.0],
            }
        )

        with patch.object(
            nhm_assist_utilities,
            "_load_nldi_cached",
            return_value=nldi_gdf,
        ), patch.object(
            nhm_assist_utilities.waterdata,
            "get_monitoring_locations",
            return_value=(wd_df, None),
        ) as mock_wd:
            result = nhm_assist_utilities.find_missing_gage_metadata(
                gage_ids=["12345678", "87654321"],
                poi_df=self.poi_df,
                resource_file_path=self.resource_file,
                root_dir=self.root_dir,
            )

        mock_wd.assert_called_once()
        self.assertEqual(len(result), 2)
        self.assertEqual(result.loc["12345678", "poi_name"], "NLDI Gage")
        self.assertEqual(result.loc["87654321", "poi_name"], "WaterData Gage")
        self.assertEqual(result.loc["87654321", "latitude"], 46.0)

    def test_nldi_failure_falls_through_to_waterdata(self):
        wd_df = pd.DataFrame(
            {
                "monitoring_location_id": ["USGS-12345678"],
                "monitoring_location_name": ["WD Gage"],
                "agency_code": ["USGS"],
                "latitude": [45.0],
                "longitude": [-122.0],
            }
        )
        printed: list[str] = []

        def capture_print(*args, **kwargs):
            printed.append(" ".join(str(a) for a in args))

        with patch.object(
            nhm_assist_utilities,
            "_load_nldi_cached",
            side_effect=OSError("simulated NLDI failure"),
        ), patch.object(
            nhm_assist_utilities.waterdata,
            "get_monitoring_locations",
            return_value=(wd_df, None),
        ), patch("builtins.print", side_effect=capture_print):
            result = nhm_assist_utilities.find_missing_gage_metadata(
                gage_ids=["12345678"],
                poi_df=self.poi_df,
                resource_file_path=self.resource_file,
                root_dir=self.root_dir,
            )

        self.assertEqual(len(result), 1)
        self.assertEqual(result.loc["12345678", "poi_name"], "WD Gage")
        self.assertTrue(
            any("could not reach NLDI" in line for line in printed),
            f"expected NLDI warning, got: {printed}",
        )

    def test_total_network_failure_returns_empty_with_warnings(self):
        printed: list[str] = []

        def capture_print(*args, **kwargs):
            printed.append(" ".join(str(a) for a in args))

        with patch.object(
            nhm_assist_utilities,
            "_load_nldi_cached",
            side_effect=OSError("NLDI down"),
        ), patch.object(
            nhm_assist_utilities.waterdata,
            "get_monitoring_locations",
            side_effect=OSError("WaterData down"),
        ), patch("builtins.print", side_effect=capture_print):
            result = nhm_assist_utilities.find_missing_gage_metadata(
                gage_ids=["12345678"],
                poi_df=self.poi_df,
                resource_file_path=self.resource_file,
                root_dir=self.root_dir,
            )

        self.assertTrue(result.empty)
        self.assertTrue(
            any("could not reach NLDI" in line for line in printed),
            f"expected NLDI warning, got: {printed}",
        )
        self.assertTrue(
            any("could not reach WaterData" in line for line in printed),
            f"expected WaterData warning, got: {printed}",
        )


class LoadNldiCachedTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.tmp_path = Path(self._tmpdir.name).resolve()
        self.geojson = self.tmp_path / "usgs_nldi_gages.geojson"
        self.gpkg = self.tmp_path / "usgs_nldi_gages.gpkg"

    def test_regenerates_gpkg_when_missing(self):
        self.geojson.write_text("{}", encoding="utf-8")  # placeholder content
        write_calls = []
        read_calls = []

        def fake_read(path):
            read_calls.append(Path(path))
            import geopandas as gpd
            return gpd.GeoDataFrame(
                {"id": ["USGS-12345678"]},
                geometry=gpd.points_from_xy([-122.0], [45.0]),
                crs="EPSG:4326",
            )

        def fake_to_file(self_gdf, path, driver=None):
            write_calls.append(Path(path))

        with patch("geopandas.read_file", side_effect=fake_read), patch(
            "geopandas.GeoDataFrame.to_file", new=fake_to_file
        ):
            result = nhm_assist_utilities._load_nldi_cached(
                self.geojson, self.gpkg
            )

        self.assertEqual(read_calls, [self.geojson])
        self.assertEqual(write_calls, [self.gpkg])
        self.assertIn("poi_gage_id", result.columns)
        self.assertIn("12345678", result["poi_gage_id"].tolist())

    def test_reads_gpkg_when_newer_than_geojson(self):
        self.geojson.write_text("{}", encoding="utf-8")
        self.gpkg.write_text("placeholder", encoding="utf-8")
        # Make gpkg newer than geojson
        now = os.path.getmtime(self.gpkg)
        os.utime(self.geojson, (now - 10, now - 10))

        def fake_read(path):
            import geopandas as gpd
            return gpd.GeoDataFrame(
                {"poi_gage_id": ["12345678"], "poi_agency": ["USGS"]},
                geometry=gpd.points_from_xy([-122.0], [45.0]),
                crs="EPSG:4326",
            )

        with patch("geopandas.read_file", side_effect=fake_read) as mock_read:
            result = nhm_assist_utilities._load_nldi_cached(
                self.geojson, self.gpkg
            )

        # Should have read the .gpkg, not the .geojson
        called_paths = [Path(c.args[0]) for c in mock_read.call_args_list]
        self.assertEqual(called_paths, [self.gpkg])
        self.assertIn("12345678", result["poi_gage_id"].tolist())


if __name__ == "__main__":
    unittest.main()
