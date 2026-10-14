# VirtualFleet_webapp

`VirtualFleet_webapp` is a user-friendly web application using [```VirtualFleet```](https://github.com/euroargodev/VirtualFleet) behind the scenes to simulate Argo float cycles and trajectories easily.

It is provided for research and educational purposes. Thus, this app is not intended for heavy simulations. For any operational use, please use directly ```VirtualFleet``` (see [documentation](https://virtualfleet.readthedocs.io/en/latest/index.html)).

## Installation

1. Clone the GitHub repository

```
git clone https://github.com/euroargodev/VirtualFleet_webapp.git
```

2. Install `uv`

`uv` is a Python package and project manager 10-100x faster than the well known `pip`. It is available on all OS (Windows, macOS and Linux).

You can install `uv` with a standalone installer, from PyPI, Homebrew and others. Please check the [installation documentation](https://docs.astral.sh/uv/getting-started/installation/#standalone-installer).

3. Synchronize packages

In the root of the cloned project (i.e., in `VirtualFleet_webapp`), run in your terminal `uv sync` to install the required packages. Note that `uv` will automatically create a virtual environment (`.venv/` folder) in the project directory. 

4. Launch the app

In your terminal, simply run

```
uv run shiny run app.py --launch-browser
```

and the app will be launched automatically. No need to activate the virtual environment, `uv` takes care of that.

 Alternatively, you can write localhost:8000 in any browser you like and you can also specify another port if needed with

 ```
uv run shiny run app.py --launch-browser --port SPECIFY_YOUR_PORT
```

## How to use the app

The app can be used in two ways. 

Either **you want to follow the full `VirtualFleet` workflow**, namely specify a velocity field &rarr; build a deployment plan &rarr; specify the float's mission parameters &rarr; run the simulation &rarr; preview simulation trajectories.

Either **you already have simulation outputs** and you want to easily preview simulation trajectories. In that case, you can directly go to this [section](#previous-simulation-trajectories).

#### Velocity field

Provide a velocity field in NetCDF format, either by browsing local files or by specifying a path to the data (either a file, a folder or a pattern such as './data/file*.nc'). The velocity field must contain the eastward and northward components of the velocity.

A variable mapping configuration file in JSON format can be provided to specify the names of velocity variables and their dimensions.
Example of a mapping file:

```json
{
    "variables": {"U": "uo", "V": "vo"},
    "dimensions": {"time": "time", "depth": "depth", "lat": "latitude", "lon": "longitude"}
}
```

If no mapping is provided, an automatic mapping will be attempted.

Additionally, you can choose whether the velocity field is periodic in time. Note that the period will be automatically computed based on the temporal coverage of the velocity field.

Once you are done, validate the velocity field. If you do not encounter issues, you should see a yellow rectangle focused on your area of interest as well as a message reminding you the temporal coverage of your velocity field.

### Deployment plan

Create (option A) or import (option B) a deployment plan for floats.

Option A: Draw markers, a line or a rectangle, choose the number of floats to deploy (automatically computed for markers) and specify the deployment date. Once validated, 
you can add/remove markers on the map and re-validate your final deployment plan.

Option B: Import a pre-built deployment plan in GeoJSON format (example available [here](https://github.com/euroargodev/VirtualFleet_webapp/blob/master/examples/deployment_plan_example.geojson)).

Note: if you have different deployment dates for different floats, use option B.

### Mission parameters

Specify the mission parameters for all floats. Either all floats have the same parameters either you need to upload a JSON file with specific mission parameters for each float.

We provide examples of a mission configuration file for [one float](https://github.com/euroargodev/VirtualFleet_webapp/blob/master/examples/mission_config_simple.json) and for [multiples floats](https://github.com/euroargodev/VirtualFleet_webapp/blob/master/examples/mission_config_multiple_floats.json) in the examples folder of the repository. Note that for multiple floats, the JSON file needs to be a **list** of configurations.

### Simulation parameters

Specify the simulation parameters and run the simulation.

The simulation data will be written in a folder 'simulations' that will be automatically created in the root folder if it does not exist.

Once the simulation is done, you can download a zip file that contains the zarr file with the simulation output, the deployment plan, the variable mapping, the mission configuration file and the profile index file (ARGO-like index file).

Note: If you run a simulation and quit the browser or close the app the computation is still running in the background.

### Previous simulation trajectories

Read a simulation output (zarr file) to display the float trajectories in the 'Simulation trajectories' tab.
Click on a profile location to see the full trajectory of that float and its pressure time series. Depending on your computer, it can take some time to see the plots, please be patient.
