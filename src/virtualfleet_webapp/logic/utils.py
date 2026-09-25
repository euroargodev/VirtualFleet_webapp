import glob
import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr
from shiny import ui


# Generic functions
def section_title(number, text, tooltip=None): 
    """Numbered circle badge + header used at the top of each sidebar section."""
    children = [
        ui.span({"class": "section-badge"}, str(number)),
        ui.h5(text, style="margin: 0;"),
    ]
    if tooltip:
        children.append(ui.HTML('<i class="fa-regular fa-circle-question"></i>'))

    heading = ui.div({"class": "section-title"}, *children)

    if tooltip:
        return ui.tooltip(heading, tooltip, placement="right")
    return heading


# Speed field
def check_config_file(value):
    """Validate an uploaded variable mapping config file.

    Expects a JSON file defining two objects, for e.g.:
        {
            "variables": {"U": "uo", "V": "vo"},
            "dimensions": {"time": "time", "depth": "depth", "lat": "latitude", "lon": "longitude"}
        }
    """
    if not value:
        #return "A config file is required"
        return None

    try:
        with Path(value[0]["datapath"]).open() as f:
            config = json.load(f)
    except Exception:
        return "File could not be read"

    if not isinstance(config, dict):
        return "File must contain dict"

    variables = config.get("variables")
    dimensions = config.get("dimensions")

    if not isinstance(variables, dict):
        return "File must define a 'variables' dict"
    if not isinstance(dimensions, dict):
        return "File must define a 'dimensions' dict"

    # gives all elements from the first set of variables that are not in the dict.
    missing_variables = {"U", "V"} - variables.keys() # U and V are the minimum requirement
    if missing_variables:
        return f"'variables' is missing required keys: {', '.join(sorted(missing_variables))}"

    missing_dimensions = {"time", "lat", "lon", "depth"} - dimensions.keys()
    if missing_dimensions:
        return f"'dimensions' is missing required keys: {', '.join(sorted(missing_dimensions))}"

    return None

def find_var_by_standard_name(ds, std_name):
    """Return the name of the variable (coord or data var) with this standard_name, or None."""
    return next(
        (name for name, v in ds.variables.items()
         if v.attrs.get("standard_name") == std_name),
        None,
    )

def autobuild_variable_mapping_config_file(netcdf):
    """
    Build variable mapping configuration file automatically, based on
    standard variable names.
    """
    # JSON key -> standard_name to search for
    variables_std_names = {
        "U": "eastward_sea_water_velocity",
        "V": "northward_sea_water_velocity",
    }
    dimensions_std_names = {
        "time": "time",
        "depth": "depth",
        "lat": "latitude",
        "lon": "longitude",
    }

    mapping = {"variables": {}, "dimensions": {}}
    missing = []

    with xr.open_dataset(netcdf) as ds:  # Make sure whatever happens, the NetCDF will be closed
        for section, std_names in [("variables", variables_std_names),
                                   ("dimensions", dimensions_std_names)]:
            for key, std_name in std_names.items():
                name = find_var_by_standard_name(ds, std_name)
                if name is None:
                    missing.append(std_name)
                else:
                    mapping[section][key] = name

    if missing:
        return None

    return mapping


def read_config_file(config_file):
    """Read a variable mapping configuration file. 
    All checks are done in check_config_file() hence there is not need for more checks.
    """
    with Path(config_file).open() as f:
        return json.load(f)
    

def list_speed_field_path(path):
    """List velocity field path(s) (user-provided) suitable for Velocity(src=...).
    """
    p = Path(path)
    if p.is_dir():
        return str(p / "*.nc")
    if p.exists():
        return str(p)  # Return single file
    return None


def get_velocity_extent(velocity):
    """Get the extent of a velocity field (min/max lat/lon)"""
    lat, lon = velocity.dim['lat'], velocity.dim['lon']
    field = velocity.field

    # See also https://github.com/euroargodev/VirtualFleet/blob/master/virtualargofleet/velocity_helpers.py
    if isinstance(field, dict): # for option B
        with xr.open_dataset(glob.glob(field['U'])[0]) as ds:  # noqa: PTH207
            return {
                "lat_min": ds[lat].min().item(),
                "lat_max": ds[lat].max().item(),
                "lon_min": ds[lon].min().item(),
                "lon_max": ds[lon].max().item(),
            }

    ds = field # for option A (directly a xr.Dataset)
    return {
        "lat_min": ds[lat].min().item(),
        "lat_max": ds[lat].max().item(),
        "lon_min": ds[lon].min().item(),
        "lon_max": ds[lon].max().item(),
    }


# Deployment plan module
def interpolate_along_line(coords, n):
    """Evenly space n points between two [lon, lat] endpoints (including them)."""
    (lon1, lat1), (lon2, lat2) = coords
    lons = np.linspace(lon1, lon2, n)
    lats = np.linspace(lat1, lat2, n)
    return [{"lat": lat, "lon": lon} for lon, lat in zip(lons, lats, strict=True)]

def grid_points_in_rectangle(coords, n):
    """Fill a rectangle with n evenly spaced points (grid), given its corners."""
    coords = coords[0] 

    lons = [c[0] for c in coords]
    lats = [c[1] for c in coords]
    lon_min, lon_max = min(lons), max(lons)
    lat_min, lat_max = min(lats), max(lats)

    width = lon_max - lon_min
    height = lat_max - lat_min

    # find rows/cols that best approximate n, keeping the aspect ratio of the rectangle
    best_grid = None
    for rows in range(1, n + 1):
        cols = round(n / rows)
        total = rows * cols
        grid_ratio = cols / rows
        rect_ratio = width / height if height != 0 else 1 # (technically should not happen)
        # Score depends on "how far off is the point count from n"
        # and "how far off is the grid aspect ratio from the rectangle aspect ratio"
        score = abs(total - n) * 1000 + abs(grid_ratio - rect_ratio) 
        if best_grid is None or score < best_grid[0]:
            best_grid = (score, rows, cols)
    _, rows, cols = best_grid

    lon_vals = np.linspace(lon_min, lon_max, cols)
    lat_vals = np.linspace(lat_min, lat_max, rows)

    points = []
    for lat in lat_vals:
        for lon in lon_vals:
            points.append({"lon": lon, "lat": lat})

    return points

def resolve_deployment_points(points, lines, shapes, num_floats):
    """Validate the current map state and return the list of float
    positions to deploy. Raises ValueError if the plan is incomplete.
    Only the first drawn line/shape is used if there are several.
    """
    if not points and not lines and not shapes:
        raise ValueError("Place markers, draw a deployment line, or draw a polygon first.")
    if lines:
        if not num_floats or num_floats < 2:
            raise ValueError("Set 'Number of floats' to at least 2 for a line deployment.")
        return interpolate_along_line(lines[0], num_floats)
    if shapes:
        if not num_floats or num_floats < 3:
            raise ValueError("Set 'Number of floats' to at least 3 for a polygon deployment.")
        return grid_points_in_rectangle(shapes[0], num_floats)
    return points


def build_geojson(points, start_date):
    """Create a GeoJSON FeatureCollection from a list of points and a start date."""
    timestamp = start_date.strftime("%Y-%m-%d")
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [p["lon"], p["lat"]]},
                "properties": {"timestamp": timestamp, "depth": 1},
            }
            for p in points
        ],
    }


def read_deployment_plan(filepath):
    """Read a deployment plan GeoJSON file and return it in the format expected by VirtualFleet, 
    i.e.: {'lat': array, 'lon': array, 'time': array}.
    """
    with Path(filepath).open() as f:
        geojson = json.load(f)

    lats, lons, times = [], [], []
    for feature in geojson["features"]:
        lon, lat = feature["geometry"]["coordinates"]
        lats.append(lat)
        lons.append(lon)
        times.append(np.datetime64(feature["properties"]["timestamp"]))

    return {
        "lat": np.array(lats),
        "lon": np.array(lons),
        "time": np.array(times),
    }


def build_deployment_plan_geojson(plan):
    """Create deployment plan in GeoJSON"""
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [float(lon), float(lat)]},
                "properties": {"timestamp": np.datetime_as_string(t, unit="D")},
            }
            for lat, lon, t in zip(plan["lat"], plan["lon"], plan["time"], strict=True)
        ],
    }


# Mission config module
def build_mission_config(cycle_duration, life_expectancy, parking_depth, profile_depth, vertical_speed):
    """Build a VirtualFleet float configuration JSON from the "same mission
    for all floats" inputs (cycle_duration, lifespan, parking_depth,
    profile_depth, vertical_speed).
    """
    return {
        "created": datetime.now(UTC).isoformat(),
        "version": "2.0",
        "name": "default", # Should I change that to something not default? Like a specific name?
        "parameters": [
            {
                "name": "cycle_duration",
                "value": float(cycle_duration),
                "description": "Maximum length of float complete cycle",
                "meta": {"unit": "hours", "dtype": "float", "techkey": "CONFIG_CycleTime_hours"},
            },
            {
                "name": "life_expectancy",
                "value": int(life_expectancy),
                "description": "Maximum number of completed cycle",
                "meta": {"unit": "cycle", "dtype": "int", "techkey": "CONFIG_MaxCycles_NUMBER"},
            },
            {
                "name": "parking_depth",
                "value": float(parking_depth),
                "description": "Drifting depth",
                "meta": {"unit": "m", "dtype": "float", "techkey": "CONFIG_ParkPressure_dbar"},
            },
            {
                "name": "profile_depth",
                "value": float(profile_depth),
                "description": "Maximum profile depth",
                "meta": {"unit": "m", "dtype": "float", "techkey": "CONFIG_ProfilePressure_dbar"},
            },
            {
                "name": "vertical_speed",
                "value": float(vertical_speed),
                "description": "Vertical profiling speed",
                "meta": {"unit": "m/s", "dtype": "float", "techkey": ""},
            },
        ],
        "$schema": "https://raw.githubusercontent.com/euroargodev/VirtualFleet/json-schemas-FloatConfiguration/schemas/VF-ArgoFloat-Configuration.json",
    }


def check_positive_number(value):
    """Validate a numeric input that must be strictly greater than zero."""
    if value is None:
        return "A value is required."
    if value <= 0:
        return "Must be greater than 0."
    return None


def read_mission_config(filepath):
    """Read a "different mission per float" file: a JSON array of VirtualFleet
    float configuration documents (as produced by build_mission_config), one
    per float.
    """
    with Path(filepath).open() as f:
        configs = json.load(f)

    if not isinstance(configs, list):
        raise ValueError("Mission config file must contain a JSON array of configurations.")

    return configs


def _flatten_single_mission_config(config):
    """Flatten a single mission configuration into a flat parameter dict."""
    return {p["name"]: p["value"] for p in config["parameters"]}


def flatten_mission_config(config):
    """Flatten one or more mission configurations into flat parameter dicts
    expected by VirtualFleet's `mission` argument.
    """
    if isinstance(config, list):
        return [_flatten_single_mission_config(c) for c in config]
    return _flatten_single_mission_config(config)


# Simulated results module
def read_index_prof(index_file):
    """Read a VirtualFleet simulation profile index CSV file
    (produced by simu2csv) and keep only the WMO, cycle number,
    data, longitude and latitude

    Index file should look like this:

    # Title : Profile directory file of a VirtualFleet simulation
    # Description : Profiles from simulation result file: /path/to/simulation.zarr
    # Project : ARGO, EARISE
    # Format version : 2.0
    # Date of update : 20260907132051
    # FTP root number 1 : ftp://ftp.ifremer.fr/ifremer/argo/dac
    # FTP root number 2 : ftp://usgodae.org/pub/outgoing/argo/dac
    # GDAC node : -
    file,date,latitude,longitude,ocean,profiler_type,institution,date_update    
    vf/9000000/profiles/R9000000_01.nc,20260110230000,42.742,7.269,A,999,VF,20260907132052
    vf/9000000/profiles/R9000000_02.nc,20260120230000,42.551,7.356,A,999,VF,20260907132052
    vf/9000000/profiles/R9000000_03.nc,20260130230000,42.705,7.731,A,999,VF,20260907132052

    """

    df = pd.read_csv(index_file, comment="#")
    extracted = df["file"].str.extract(r"R(\d+)_(\d+)\.nc")
    df["wmo"] = extracted[0].astype(int)
    df["cycle_number"] = extracted[1].astype(int)
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d%H%M%S")

    return df[["wmo", "cycle_number", "date", "latitude", "longitude"]]