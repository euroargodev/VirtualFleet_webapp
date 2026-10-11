# DISCLAIMER - Those tests were written by Generative AI (namely by Claude code v2.1.235, model Sonnet 5)
# and reviewed later on by a human.
import datetime
import json

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from virtualfleet_webapp.logic.utils import (
    autobuild_variable_mapping_config_file,
    build_deployment_plan_geojson,
    build_geojson,
    build_mission_config,
    check_config_file,
    check_positive_number,
    find_var_by_standard_name,
    flatten_mission_config,
    get_velocity_extent,
    interpolate_along_line,
    list_speed_field_path,
    load_bathymetry,
    read_config_file,
    read_deployment_plan,
    read_index_prof,
    read_mission_config,
    resolve_deployment_points,
)


def _write_config(tmp_path, content):
    config_path = tmp_path / "config.json"
    config_path.write_text(content)
    return [{"datapath": str(config_path)}]


FULL_VARIABLES = {"U": "uo", "V": "vo"}
FULL_DIMENSIONS = {"time": "time", "depth": "depth", "lat": "latitude", "lon": "longitude"}


class TestCheckConfigFile:
    def test_valid_config_passes(self, tmp_path):
        content = json.dumps({"variables": FULL_VARIABLES, "dimensions": FULL_DIMENSIONS})
        assert check_config_file(_write_config(tmp_path, content)) is None

    def test_missing_variables_dict(self, tmp_path):
        content = json.dumps({"dimensions": FULL_DIMENSIONS})
        error = check_config_file(_write_config(tmp_path, content))
        assert "variables" in error

    def test_missing_dimensions_dict(self, tmp_path):
        content = json.dumps({"variables": FULL_VARIABLES})
        error = check_config_file(_write_config(tmp_path, content))
        assert "dimensions" in error

    def test_missing_required_variable_key(self, tmp_path):
        content = json.dumps({"variables": {"U": "uo"}, "dimensions": FULL_DIMENSIONS})
        error = check_config_file(_write_config(tmp_path, content))
        assert error is not None
        assert "V" in error

    def test_missing_required_dimension_key(self, tmp_path):
        content = json.dumps(
            {"variables": FULL_VARIABLES, "dimensions": {"time": "time", "lat": "latitude", "lon": "longitude"}}
        )
        error = check_config_file(_write_config(tmp_path, content))
        assert error is not None
        assert "depth" in error

    def test_no_file_uploaded_is_valid(self):
        assert check_config_file(None) is None


class TestListSpeedFieldPath:
    def test_folder_becomes_a_netcdf_glob_pattern(self, tmp_path):
        assert list_speed_field_path(str(tmp_path)) == str(tmp_path / "*.nc")

    def test_existing_file_is_returned_as_is(self, tmp_path):
        path = tmp_path / "field.nc"
        path.touch()
        assert list_speed_field_path(str(path)) == str(path)

    def test_glob_pattern_matching_files_is_returned_as_is(self, tmp_path):
        (tmp_path / "field_1.nc").touch()
        pattern = str(tmp_path / "field_*.nc")
        assert list_speed_field_path(pattern) == pattern

    def test_glob_pattern_matching_nothing_returns_none(self, tmp_path):
        assert list_speed_field_path(str(tmp_path / "nothing_*.nc")) is None

    def test_missing_path_returns_none(self, tmp_path):
        assert list_speed_field_path(str(tmp_path / "missing.nc")) is None


def _cf_velocity_dataset():
    """Small velocity field whose variables are only identifiable by their standard_name."""
    ds = xr.Dataset(
        {
            "uo": (("time", "depth", "latitude", "longitude"), np.zeros((1, 1, 2, 2))),
            "vo": (("time", "depth", "latitude", "longitude"), np.zeros((1, 1, 2, 2))),
        },
        coords={
            "time": pd.to_datetime(["2026-01-01"]),
            "depth": [0.5],
            "latitude": [10.0, 11.0],
            "longitude": [0.0, 1.0],
        },
    )
    ds["uo"].attrs["standard_name"] = "eastward_sea_water_velocity"
    ds["vo"].attrs["standard_name"] = "northward_sea_water_velocity"
    for name in ("time", "depth", "latitude", "longitude"):
        ds[name].attrs["standard_name"] = name
    return ds


class TestFindVarByStandardName:
    def test_finds_data_variables_and_coordinates(self):
        ds = _cf_velocity_dataset()
        assert find_var_by_standard_name(ds, "eastward_sea_water_velocity") == "uo"
        assert find_var_by_standard_name(ds, "latitude") == "latitude"

    def test_returns_none_when_absent(self):
        assert find_var_by_standard_name(_cf_velocity_dataset(), "sea_water_temperature") is None


class TestAutobuildVariableMappingConfigFile:
    def test_builds_the_mapping_from_standard_names(self, tmp_path):
        path = tmp_path / "field.nc"
        _cf_velocity_dataset().to_netcdf(path)

        assert autobuild_variable_mapping_config_file(str(path)) == {
            "variables": {"U": "uo", "V": "vo"},
            "dimensions": {"time": "time", "depth": "depth", "lat": "latitude", "lon": "longitude"},
        }

    def test_returns_none_when_a_standard_name_is_missing(self, tmp_path):
        ds = _cf_velocity_dataset()
        del ds["vo"].attrs["standard_name"]
        path = tmp_path / "field.nc"
        ds.to_netcdf(path)

        assert autobuild_variable_mapping_config_file(str(path)) is None

    def test_returns_none_when_the_file_cannot_be_opened(self, tmp_path):
        path = tmp_path / "not_a_netcdf.nc"
        path.write_text("garbage")

        assert autobuild_variable_mapping_config_file(str(path)) is None


class TestCheckPositiveNumber:
    def test_positive_value_passes(self):
        assert check_positive_number(5) is None

    def test_zero_fails(self):
        assert check_positive_number(0) is not None

    def test_negative_fails(self):
        assert check_positive_number(-1) is not None

    def test_none_fails(self):
        assert check_positive_number(None) is not None


class TestReadConfigFile:
    def test_reads_the_config_file_contents(self, tmp_path):
        config = {"variables": FULL_VARIABLES, "dimensions": FULL_DIMENSIONS}
        path = tmp_path / "config.json"
        path.write_text(json.dumps(config))

        assert read_config_file(str(path)) == config


class TestInterpolateAlongLine:
    def test_endpoints_are_included(self):
        points = interpolate_along_line([(0.0, 0.0), (10.0, 0.0)], 3)
        assert points[0] == {"lat": 0.0, "lon": 0.0}
        assert points[-1] == {"lat": 0.0, "lon": 10.0}

    def test_returns_n_evenly_spaced_points(self):
        points = interpolate_along_line([(0.0, 0.0), (4.0, 0.0)], 5)
        assert [p["lon"] for p in points] == [0.0, 1.0, 2.0, 3.0, 4.0]
        assert all(p["lat"] == 0.0 for p in points)


class TestResolveDeploymentPoints:
    def test_raises_when_nothing_drawn(self):
        with pytest.raises(ValueError, match="Place markers"):
            resolve_deployment_points([], [], [], num_floats=5)

    def test_points_only_returns_points_unchanged(self):
        points = [{"lat": 1.0, "lon": 2.0}, {"lat": 3.0, "lon": 4.0}]
        result = resolve_deployment_points(points, [], [], num_floats=0)
        assert result == points

    def test_line_requires_at_least_two_floats(self):
        line = [(0.0, 0.0), (1.0, 0.0)]
        with pytest.raises(ValueError, match="at least 2 for a line deployment"):
            resolve_deployment_points([], [line], [], num_floats=1)

    def test_line_interpolates_requested_number_of_floats(self):
        line = [(0.0, 0.0), (1.0, 0.0)]
        result = resolve_deployment_points([], [line], [], num_floats=4)
        assert len(result) == 4

    def test_line_ignores_extra_lines_and_uses_the_first(self):
        first = [(0.0, 0.0), (1.0, 0.0)]
        second = [(9.0, 9.0), (10.0, 10.0)]
        result = resolve_deployment_points([], [first, second], [], num_floats=2)
        assert result == interpolate_along_line(first, 2)

    def test_shape_requires_at_least_one_float(self):
        rectangle = [[(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]]
        with pytest.raises(ValueError, match="at least 1 for a polygon deployment"):
            resolve_deployment_points([], [], [rectangle], num_floats=0)

    def test_shape_accepts_a_single_float(self):
        rectangle = [[(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]]
        assert len(resolve_deployment_points([], [], [rectangle], num_floats=1)) == 1

    def test_shape_grids_points_inside_the_rectangle(self):
        rectangle = [[(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]]
        result = resolve_deployment_points([], [], [rectangle], num_floats=4)
        assert len(result) == 4
        assert all(0.0 <= p["lon"] <= 1.0 and 0.0 <= p["lat"] <= 1.0 for p in result)


DIMS = {"time": "time", "depth": "depth", "lat": "latitude", "lon": "longitude"}


def _velocity_dataset(times):
    return xr.Dataset(
        coords={
            "time": pd.to_datetime(times),
            "latitude": [10.0, 20.0, 30.0],
            "longitude": [-5.0, 0.0, 5.0],
        }
    )


class TestGetVelocityExtent:
    def test_returns_the_spatial_and_temporal_bounds_of_a_dataset(self):
        ds = _velocity_dataset(["2026-01-01", "2026-01-05", "2026-01-11"])

        extent = get_velocity_extent(ds, DIMS)

        assert extent["lat_min"] == 10.0
        assert extent["lat_max"] == 30.0
        assert extent["lon_min"] == -5.0
        assert extent["lon_max"] == 5.0
        assert extent["time_min"] == np.datetime64("2026-01-01")
        assert extent["time_max"] == np.datetime64("2026-01-11")
        assert extent["time_span"] == pd.Timedelta(days=10)

    def test_time_extent_spans_all_files_of_a_file_pattern(self, tmp_path):
        _velocity_dataset(["2026-01-01", "2026-01-02"]).to_netcdf(tmp_path / "field_1.nc")
        _velocity_dataset(["2026-01-03", "2026-01-04"]).to_netcdf(tmp_path / "field_2.nc")

        extent = get_velocity_extent({"U": str(tmp_path / "field_*.nc")}, DIMS)

        assert extent["lat_min"] == 10.0
        assert extent["lon_max"] == 5.0
        assert extent["time_min"] == np.datetime64("2026-01-01")
        assert extent["time_max"] == np.datetime64("2026-01-04")
        assert extent["time_span"] == pd.Timedelta(days=3)


class TestBuildGeojson:
    def test_produces_a_feature_collection_with_one_point_feature_per_input_point(self):
        points = [{"lat": 1.5, "lon": 2.5}, {"lat": -3.0, "lon": 4.0}]
        geojson = build_geojson(points, datetime.date(2026, 1, 15))

        assert geojson["type"] == "FeatureCollection"
        assert len(geojson["features"]) == 2

        feature = geojson["features"][0]
        assert feature["type"] == "Feature"
        assert feature["geometry"] == {"type": "Point", "coordinates": [2.5, 1.5]}
        assert feature["properties"]["timestamp"] == "2026-01-15"
        assert feature["properties"]["depth"] == 1.0

    def test_empty_points_produces_empty_feature_list(self):
        geojson = build_geojson([], datetime.date(2026, 1, 15))
        assert geojson["features"] == []


class TestReadDeploymentPlan:
    def test_reads_a_geojson_plan_into_columnar_arrays(self, tmp_path):
        points = [{"lat": 1.5, "lon": 2.5}, {"lat": -3.0, "lon": 4.0}]
        geojson = build_geojson(points, datetime.date(2026, 1, 15))
        path = tmp_path / "plan.geojson"
        path.write_text(json.dumps(geojson))

        plan = read_deployment_plan(str(path))

        assert list(plan["lat"]) == [1.5, -3.0]
        assert list(plan["lon"]) == [2.5, 4.0]
        assert list(plan["time"]) == [np.datetime64("2026-01-15")] * 2

    def test_empty_features_produce_empty_arrays(self, tmp_path):
        geojson = build_geojson([], datetime.date(2026, 1, 15))
        path = tmp_path / "plan.geojson"
        path.write_text(json.dumps(geojson))

        plan = read_deployment_plan(str(path))

        assert len(plan["lat"]) == 0
        assert len(plan["lon"]) == 0
        assert len(plan["time"]) == 0


class TestBuildDeploymentPlanGeojson:
    def test_produces_a_feature_per_point_with_day_precision_timestamp(self):
        plan = {
            "lat": np.array([1.5, -3.0]),
            "lon": np.array([2.5, 4.0]),
            "time": np.array([np.datetime64("2026-01-15")] * 2),
        }

        geojson = build_deployment_plan_geojson(plan)

        assert geojson["type"] == "FeatureCollection"
        assert len(geojson["features"]) == 2
        feature = geojson["features"][0]
        assert feature["geometry"] == {"type": "Point", "coordinates": [2.5, 1.5]}
        assert feature["properties"]["timestamp"] == "2026-01-15"

    def test_timestamp_keeps_day_precision_even_with_nanosecond_input(self):
        plan = {
            "lat": np.array([1.5]),
            "lon": np.array([2.5]),
            "time": np.array([np.datetime64("2026-01-15T00:00:00.000000000")]),
        }

        geojson = build_deployment_plan_geojson(plan)

        assert geojson["features"][0]["properties"]["timestamp"] == "2026-01-15"

    def test_round_trips_through_read_deployment_plan_with_day_precision(self, tmp_path):
        points = [{"lat": 1.5, "lon": 2.5}]
        original = build_geojson(points, datetime.date(2026, 1, 15))
        path = tmp_path / "plan.geojson"
        path.write_text(json.dumps(original))

        plan = read_deployment_plan(str(path))
        rebuilt = build_deployment_plan_geojson(plan)

        assert rebuilt["features"][0]["properties"]["timestamp"] == "2026-01-15"

    def test_empty_plan_produces_empty_feature_list(self):
        plan = {"lat": np.array([]), "lon": np.array([]), "time": np.array([], dtype="datetime64[D]")}
        assert build_deployment_plan_geojson(plan)["features"] == []


class TestBuildMissionConfig:
    def test_produces_the_expected_document_shape(self):
        config = build_mission_config(
            cycle_duration=240,
            life_expectancy=200,
            parking_depth=1000,
            profile_depth=2000,
            vertical_speed=0.09,
        )

        # assert config["version"] == "2.0"
        # assert config["name"] == "default"
        # assert "created" in config
        # assert config["$schema"].startswith("https://")
        assert len(config["parameters"]) == 5

    def test_parameter_values_and_types(self):
        config = build_mission_config(
            cycle_duration=240, life_expectancy=200, parking_depth=1000, profile_depth=2000, vertical_speed=0.09
        )
        values = {p["name"]: p["value"] for p in config["parameters"]}

        assert values["cycle_duration"] == 240.0
        assert values["life_expectancy"] == 200
        assert isinstance(values["life_expectancy"], int)
        assert values["parking_depth"] == 1000.0
        assert values["profile_depth"] == 2000.0
        assert values["vertical_speed"] == 0.09


class TestReadMissionConfig:
    def test_reads_a_list_of_configs(self, tmp_path):
        configs = [
            build_mission_config(
                cycle_duration=240, life_expectancy=200, parking_depth=depth, profile_depth=2000, vertical_speed=0.09
            )
            for i, depth in enumerate([100, 200, 500])
        ]
        path = tmp_path / "mission.json"
        path.write_text(json.dumps(configs))

        assert read_mission_config(str(path)) == configs

    def test_raises_when_file_is_not_a_json_array(self, tmp_path):
        path = tmp_path / "mission.json"
        path.write_text(json.dumps({"not": "a list"}))

        with pytest.raises(ValueError, match="must contain a JSON array"):
            read_mission_config(str(path))


class TestFlattenMissionConfig:
    def test_flattens_a_single_config_document(self):
        config = build_mission_config(
            cycle_duration=240,
            life_expectancy=200,
            parking_depth=1000,
            profile_depth=2000,
            vertical_speed=0.09,
        )

        flat = flatten_mission_config(config)

        assert flat == {
            "cycle_duration": 240.0,
            "life_expectancy": 200,
            "parking_depth": 1000.0,
            "profile_depth": 2000.0,
            "vertical_speed": 0.09,
        }

    def test_flattens_a_list_of_config_documents(self):
        configs = [
            build_mission_config(
                cycle_duration=240, life_expectancy=200, parking_depth=depth, profile_depth=2000, vertical_speed=0.09
            )
            for i, depth in enumerate([100, 200, 500])
        ]

        flat = flatten_mission_config(configs)

        assert [f["parking_depth"] for f in flat] == [100.0, 200.0, 500.0]
        assert all(f["cycle_duration"] == 240.0 for f in flat)


class TestReadIndexProf:
    def test_extracts_wmo_cycle_number_and_parses_dates(self, tmp_path):
        path = tmp_path / "index.txt"
        path.write_text(
            "# Title : Profile directory file of a VirtualFleet simulation\n"
            "# Format version : 2.0\n"
            "file,date,latitude,longitude,ocean,profiler_type,institution,date_update\n"
            "vf/9000000/profiles/R9000000_01.nc,20260110230000,42.742,7.269,A,999,VF,20260907132052\n"
            "vf/9000001/profiles/R9000001_12.nc,20260120230000,42.551,7.356,A,999,VF,20260907132052\n"
        )

        df = read_index_prof(str(path))

        assert list(df.columns) == ["wmo", "cycle_number", "date", "latitude", "longitude"]
        assert list(df["wmo"]) == [9000000, 9000001]
        assert list(df["cycle_number"]) == [1, 12]
        assert df["date"].iloc[0] == pd.Timestamp("2026-01-10 23:00:00")
        assert list(df["latitude"]) == [42.742, 42.551]


class TestLoadBathymetry:
    def test_returns_one_reader_per_depth_sorted_from_surface_to_bottom(self):
        depths, shp_dict = load_bathymetry(lat_min=36, lat_max=43, lon_min=2, lon_max=10)

        assert list(depths) == [
            "-0",
            "-200",
            "-1000",
            "-2000",
            "-3000",
            "-4000",
            "-5000",
            "-6000",
            "-7000",
            "-8000",
            "-9000",
            "-10000",
        ]
        assert set(shp_dict) == set(depths)

    def test_surface_layer_has_geometries_in_the_mediterranean(self):
        _, shp_dict = load_bathymetry(lat_min=36, lat_max=43, lon_min=2, lon_max=10)
        assert next(shp_dict["-0"].geometries(), None) is not None
