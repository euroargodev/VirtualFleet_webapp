import asyncio
import tempfile

import cartopy.crs as ccrs
import cartopy.feature as cfeature
import matplotlib.pyplot as plt
import pandas as pd # replace it with polars? Faster.
import plotly.graph_objects as go
import xarray as xr
from ipyleaflet import (
    basemaps,
    basemap_to_tiles,
    CircleMarker,
    LayersControl,
    Map,
    Polyline,
    ScaleControl
)
from ipywidgets import HTML
from shiny import module, reactive, render, ui
from shinywidgets import output_widget, render_plotly, render_widget
from virtualargofleet.utilities import simu2csv

from virtualfleet_webapp.logic.utils import read_index_prof


@module.ui
def simulated_traj_ui():
    # Sidebar layout
    return ui.layout_sidebar(
        ui.sidebar(
            ui.input_text(
                id="simulated_traj_path",
                label="Path to simulation output",
                value="./simulations/default.zarr",
                placeholder="Path to simulation results",
            ),
            ui.input_task_button(
                id="read_zarr_file",
                label=ui.HTML("Read zarr file"),
                class_="btn-primary",
                label_busy="Reading..."
            ),
            gap=10,  # Vertical spacing in the sidebar
        ),
        # Main panel
        ui.div(
            ui.card(
                output_widget("map_traj"),
                max_height="80vh", # 80% of the viewport height
                fill=False,
            ),
            ui.output_ui("plot_info_traj"),
        ),
    )


@module.server
def simulated_traj_server(input, output, session):

    #######
    # MAP #
    #######
    # Allow the user to choose between different basemaps
    # Also check https://github.com/jupyter-widgets/ipyleaflet/issues/970
    esri_world_imagery = basemap_to_tiles(basemaps.Esri.WorldImagery)
    esri_world_imagery.base = True
    
    openstreetmap = basemap_to_tiles(basemaps.OpenStreetMap.Mapnik)
    openstreetmap.base = True

    opentopomap = basemap_to_tiles(basemaps.OpenTopoMap)
    opentopomap.base = True

    m = Map(
        center=(0, 0),
        zoom=3,
        layers=[openstreetmap, opentopomap, esri_world_imagery],
        scroll_wheel_zoom=True,
    )

    m.add_control(LayersControl(position="topright"))

    # Add options
    m.add(ScaleControl(position="bottomleft"))

    trajectory_layers = [] # For profile trajectories (index_data)

    @output
    @render_widget
    def map_traj():
        return m

    ###################
    # Read .zarr file #
    ###################
    def _read_zarr_file(file):
        return xr.open_zarr(file)

    @ui.bind_task_button(button_id="read_zarr_file")
    @reactive.extended_task
    async def read_zarr_file(file):
        return await asyncio.to_thread(_read_zarr_file, file)

    @reactive.effect
    @reactive.event(input.read_zarr_file)
    def _():
        read_zarr_file(input.simulated_traj_path())

    ######################
    # Read index profile #
    ######################
    def _read_index_data(zarr_path):
        with tempfile.TemporaryDirectory() as tmp_dir:
            index_file = simu2csv(zarr_path, index_file=f"{tmp_dir}/index.txt")
            return read_index_prof(index_file)

    @reactive.extended_task
    async def read_index_data(zarr_path):
        return await asyncio.to_thread(_read_index_data, zarr_path)

    @reactive.effect
    @reactive.event(read_zarr_file.status)
    def _():
        # No need to read the index data if the zarr file was not successiully loaded
        # or is still running
        if read_zarr_file.status() != "success":
            return
        read_index_data(input.simulated_traj_path())

    @reactive.effect
    def _():
        if read_index_data.status() == "error":
            try:
                read_index_data.result()
            except Exception as e:
                ui.notification_show(f"Could not read index data: {e}", type="error")

    @reactive.calc
    def index_data():
        if read_index_data.status() != "success":
            return None
        return read_index_data.result()
    
    # Reactive value for creating the plots after clicking on a trajectory
    selected_trajectory = reactive.value(None)

    def _show_plots(float_index):
        """
        TO DO
        """
        def _on_click(**kwargs): # need to accept **kwargs because of ipyleaflet's on_click definition
            selected_trajectory.set(float_index)

        return _on_click

    # Plot every float's whole trajectory (based on index data, i.e. profiles)
    @reactive.effect
    @reactive.event(index_data)
    def _():
        status = read_zarr_file.status()

        if status == "error":
            try:
                read_zarr_file.result()
            except Exception as e:
                ui.notification_show(f"Could not read zarr file: {e}", type="error")
            return
        if status != "success":
            return

        for layer in trajectory_layers: # For previous file's trajectories
            m.remove(layer)
        trajectory_layers.clear()
        selected_trajectory.set(None) # Clear plot selection from a previous file

        ds = read_zarr_file.result()
        if "lat" not in ds or "lon" not in ds:
            return

        lat_deployment = ds["lat"].isel(obs=0).values
        lon_deployment = ds["lon"].isel(obs=0).values
        if lat_deployment.size == 0:
            return

        # Read profile index file
        df = index_data()
        if df is None:
            return

        for i, (lat_init, lon_init) in enumerate(zip(lat_deployment, lon_deployment, strict=True)):
            lat_init, lon_init = float(lat_init), float(lon_init)

            unique_wmos = sorted(df["wmo"].unique())

            # Add "cycle 0" (i.e. deployment info)
            cycle_zero = pd.DataFrame([{
                "wmo": int(unique_wmos[i]),
                "cycle_number": 0,
                "date": pd.NaT,
                "latitude": lat_init,
                "longitude": lon_init,
            }])

            if df is not None:
                profile = df[df["wmo"] == int(unique_wmos[i])].sort_values("cycle_number")
                profile = pd.concat([cycle_zero, profile], ignore_index=True)
            else:
                profile = cycle_zero # Float did not reach one profile for x reason

            if len(profile) > 1: # Polyline needs at least 2 points
                trajectory = list(zip(profile["latitude"], profile["longitude"], strict=True))
                line = Polyline(locations=trajectory, color="#000000", weight=1, fill=False)
                m.add(line)
                trajectory_layers.append(line)

            for row in profile.itertuples(): # Better than iterrows() here (simpler access to fields)
                popup = HTML(
                    value=(
                        f"<b>Float</b> {row.wmo}<br>"
                        f"<b>Cycle</b> {row.cycle_number}<br>"
                        f"<b>Datetime</b> {row.date}<br>"
                        f"<b>Latitude</b> {row.latitude:.3f}<br>"
                        f"<b>Longitude</b> {row.longitude:.3f}"
                    )
                )
                point = CircleMarker(
                    location=(row.latitude, row.longitude),
                    radius=3,
                    color="#FFFFFF",
                    fill_color="#000000",
                    fill_opacity=1,
                    weight=1,
                    popup=popup,
                )
                m.add(point)
                trajectory_layers.append(point)
                point.on_click(_show_plots(i))

    ########################
    # Pressure time series #
    ########################
    has_selection = reactive.value(False)

    @reactive.effect
    def _():
        has_selection.set(selected_trajectory() is not None)

    @output
    @render.ui
    def plot_info_traj():
        if not has_selection():
            return None
        return ui.layout_columns(
            ui.card(ui.output_plot("trajectory_map")),
            ui.card(output_widget("trajectory_plots")),
        )

    @output
    @render.plot
    def trajectory_map():
        idx = selected_trajectory()
        if idx is None or read_zarr_file.status() != "success":
            return None

        ds = read_zarr_file.result()
        traj = ds.isel(trajectory=idx) # idx = float_index

        lat = traj['lat'].values
        lon = traj['lon'].values

        # Trajectory plot
        fig = plt.figure(figsize=(5, 5))
        ax = fig.add_subplot(1, 1, 1, projection=ccrs.PlateCarree())

        lat_min, lat_max = lat.min(), lat.max()
        lon_min, lon_max = lon.min(), lon.max()
        lat_margin = (lat_max - lat_min) + 10
        lon_margin = (lon_max - lon_min) + 10
        ax.set_extent(
            [lon_min - lon_margin, lon_max + lon_margin, lat_min - lat_margin, lat_max + lat_margin],
            crs=ccrs.PlateCarree(),
        )
        ax.plot(lon, lat, color="black", linewidth=1, marker="o", markersize=3, transform=ccrs.PlateCarree())

        ax.add_wms(wms="https://wms.gebco.net/mapserv?", layers=["GEBCO_LATEST"])
        ax.add_feature(cfeature.COASTLINE, linewidth=0.5)
        ax.add_feature(cfeature.BORDERS, linewidth=0.3)
        ax.gridlines(draw_labels=True, linewidth=0.3, alpha=0.5)

        return fig

    @output
    @render_plotly
    def trajectory_plots():
        idx = selected_trajectory()
        if idx is None or read_zarr_file.status() != "success":
            return None

        ds = read_zarr_file.result()
        traj = ds.isel(trajectory=idx) # idx = float_index

        #
        # Build pressure plot #
        #

        # Legend/colour details
        phase_labels = ['Sink to parking', 'Drift', 'Sink to profile', 'Profiling', 'Surface']
        #colors = ['#beaed4', '#fdc086', '#7fc97f', '#ffff99', '#386cb0'] # Based on colorbrewer2.org
        colors = ['#377eb8', '#ff7f00', '#4daf4a', '#984ea3', '#e41a1c']

        n = len(colors)
        colorscale = []
        for i, c in enumerate(colors):
            colorscale.append([i / n, c])
            colorscale.append([(i + 1) / n, c])

        fig = go.Figure()
        #fig.add_trace(go.Scattergl( # gl not always supported by browser.
        fig.add_trace(go.Scatter(
            x=pd.to_datetime(traj['time'].values).astype(str),
            y=traj['z'].values,
            mode='markers',
            marker=dict(
                size=6,
                color=traj['cycle_phase'],
                colorscale=colorscale,
                cmin=0,
                cmax=5,
                showscale=True,
                colorbar=dict(
                    tickvals=[0.5, 1.5, 2.5, 3.5, 4.5],
                    ticktext=phase_labels,
                    title="Cycle phase"
                )
            ),
        ))

        fig.update_yaxes(autorange="reversed", title_text="Pressure (m)")
        fig.update_xaxes(title_text="Time", tickangle=45)
        fig.update_layout(height=500, width=900, template="plotly_white")

        return fig
