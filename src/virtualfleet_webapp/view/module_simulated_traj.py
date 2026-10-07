import asyncio
import tempfile

import numpy as np
import pandas as pd  # replace it with polars? Faster.
import plotly.graph_objects as go
import xarray as xr
from ipyleaflet import basemap_to_tiles, basemaps, CircleMarker, Map, Polyline, ScaleControl, WidgetControl
from ipywidgets import Dropdown, HTML
from shiny import module, reactive, render, ui
from shinywidgets import output_widget, render_plotly, render_widget
from virtualargofleet.utilities import simu2csv

from virtualfleet_webapp.logic.utils import read_index_prof, section_title

tooltip_content = ui.HTML(
    "Read a simulation output (zarr file) to display the float trajectories<br>"
    "in the 'Simulation trajectories' tab.<br><br>"
    "Click on a profile location to see the full trajectory of that float<br>"
    "and its pressure time series."
)


@module.ui
def simulated_traj_ui():
    return ui.TagList(
        section_title(None, "Preview simulation trajectories", tooltip=tooltip_content),
        ui.div(
            ui.input_text(
                id="simulated_traj_path",
                label=ui.span("Path to simulation output", style="font-size: 0.90rem;"),
                value="./simulations/default.zarr",
                placeholder="Path to simulation results",
            ),
            ui.input_task_button(
                id="read_zarr_file",
                label=ui.HTML('<i class="fa-solid fa-book-open"></i> Read zarr file'),
                style="width: 100%; background: var(--bs-primary); color: white; border: none; margin-top: 0px;",
                label_busy="Reading...",
            ),
        ),
    )


@module.ui
def simulated_traj_map_ui():
    return ui.div(
        ui.card(
            output_widget("map_traj"),
            max_height="80vh",  # 80% of the viewport height
            fill=False,
            style="flex: 0 0 100%;",  # Always take the full visible panel height
        ),
        ui.output_ui("plot_info_traj"),
        class_="html-fill-item html-fill-container",  # Panel height: lets card use flex
        style="overflow-y: auto;",  # Scroll when content overflows
    )


@module.server
def simulated_traj_server(input, output, session):

    #######
    # MAP #
    #######
    dropdown = Dropdown(
        options={
            "Esri World Imagery": basemap_to_tiles(basemaps.Esri.WorldImagery),
            "OpenStreetMap": basemap_to_tiles(basemaps.OpenStreetMap.Mapnik),
            "OpenTopoMap": basemap_to_tiles(basemaps.OpenTopoMap),
        },
        layout=dict(width="150px"),
    )

    dropdown.observe(lambda change: m.substitute(change["old"], change["new"]), names="value")

    m = Map(
        center=(0, 0),
        zoom=3,
        layers=[dropdown.value],
        scroll_wheel_zoom=True,
    )

    # Add options
    m.add(WidgetControl(widget=dropdown, position="topright"))
    m.add(ScaleControl(position="bottomleft"))

    trajectory_layers = []  # For profile trajectories (index_data)

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
    # Note: Keep the index file in temporary file because
    # it needs to stay independent from any simulation.
    def _read_index_data(zarr_path):
        with tempfile.TemporaryDirectory() as tmp_dir:
            index_file = simu2csv(zarr_path, index_file=f"{tmp_dir}/index.txt")
            return read_index_prof(index_file)

    @ui.bind_task_button(button_id="read_zarr_file")
    @reactive.extended_task
    async def read_index_data(zarr_path):
        return await asyncio.to_thread(_read_index_data, zarr_path)

    @reactive.effect
    @reactive.event(read_zarr_file.status)
    def _():
        if read_zarr_file.status() == "error":
            try:
                read_zarr_file.result()
            except Exception as e:
                ui.notification_show(f"Could not read zarr file: {e}", type="error")
            return
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
        Show full float trajectory and phase cycles.
        """

        def _on_click(**kwargs):  # need to accept **kwargs because of ipyleaflet's on_click definition
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

        for layer in trajectory_layers:  # For previous file's trajectories
            m.remove(layer)
        trajectory_layers.clear()
        selected_trajectory.set(None)  # Clear plot selection from a previous file

        ds = read_zarr_file.result()
        if "lat" not in ds or "lon" not in ds:
            return

        lat_deployment = ds["lat"].isel(obs=0).values
        lon_deployment = ds["lon"].isel(obs=0).values
        if lat_deployment.size == 0:
            return

        # Re-center the map on selected trajectory
        m.fit_bounds(
            [[ds["lat"].min().values, ds["lon"].min().values], [ds["lat"].max().values, ds["lon"].max().values]]
        )

        # Read profile index file
        df = index_data()
        if df is None:
            return

        for i, (lat_init, lon_init) in enumerate(zip(lat_deployment, lon_deployment, strict=True)):
            lat_init, lon_init = float(lat_init), float(lon_init)

            unique_wmos = sorted(df["wmo"].unique())

            # Add "cycle 0" (i.e. deployment info)
            cycle_zero = pd.DataFrame(
                [
                    {
                        "wmo": int(unique_wmos[i]),
                        "cycle_number": 0,
                        "date": pd.NaT,
                        "latitude": lat_init,
                        "longitude": lon_init,
                    }
                ]
            )

            if df is not None:
                profile = df[df["wmo"] == int(unique_wmos[i])].sort_values("cycle_number")
                profile = pd.concat([cycle_zero, profile], ignore_index=True)
            else:
                profile = cycle_zero  # Float did not reach one profile for x reason

            if len(profile) > 1:  # Polyline needs at least 2 points
                trajectory = list(zip(profile["latitude"], profile["longitude"], strict=True))
                line = Polyline(locations=trajectory, color="#000000", weight=2, fill=False)
                m.add(line)
                trajectory_layers.append(line)

            for row in profile.itertuples():  # Better than iterrows() here (simpler access to fields)
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
                    radius=5,
                    color="black",
                    fill_color="white",
                    fill_opacity=1,
                    weight=2,
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
        return ui.card(
            ui.layout_columns(
                ui.card(output_widget("trajectory_map")),
                ui.card(output_widget("trajectory_plots")),
            ),
            fill=False,
            class_="flex-shrink-0",  # Means don't shrink and scroll instead
        )

    @output
    @render_plotly
    def trajectory_map():
        idx = selected_trajectory()
        if idx is None or read_zarr_file.status() != "success":
            return None

        ds = read_zarr_file.result()
        traj = ds.isel(trajectory=idx)  # idx = float_index

        lat = traj["lat"].values
        lon = traj["lon"].values
        time = pd.to_datetime(traj["time"].values)
        days = (time - time[0]).total_seconds() / 86400  # Plotly colorscales need numbers

        fig = go.Figure()
        fig.add_trace(
            go.Scattermap(
                lat=lat,
                lon=lon,
                mode="markers",
                customdata=time.astype(str),
                hovertemplate="Time: %{customdata}<br>Lat: %{lat:.2f}<br>Lon: %{lon:.2f}<extra></extra>",
                marker=dict(
                    size=6,
                    color=days,
                    colorscale="Magma_r"
                ),
                showlegend=False,
            )
        )
        fig.add_trace(
            go.Scattermap(
                lat=[lat[0]],
                lon=[lon[0]],
                mode="markers",
                marker=dict(size=14, color="black"),
                hovertemplate="Deployment<extra></extra>",
                showlegend=False,
            )
        )

        # Center on the trajectory
        # https://plotly.com/python/tile-map-layers/
        fig.update_layout(
            map=dict(
                style="open-street-map",
                center=dict(lat=float(np.nanmean(lat)), lon=float(np.nanmean(lon))),
                zoom=6
            )
        )

        fig.update_layout(modebar_remove=["autoScale", "sendChartToCloud", "lasso", "pan", "select"])

        return fig

    @output
    @render_plotly
    def trajectory_plots():
        idx = selected_trajectory()
        if idx is None or read_zarr_file.status() != "success":
            return None

        ds = read_zarr_file.result()
        traj = ds.isel(trajectory=idx)  # idx = float_index

        # Legend/colour details
        phase_labels = ["Sink to parking", "Drift", "Sink to profile", "Profiling", "Surface"]  # Order matters
        # colors = ['#beaed4', '#fdc086', '#7fc97f', '#ffff99', '#386cb0'] # Based on colorbrewer2.org
        colors = ["#377eb8", "#ff7f00", "#4daf4a", "#984ea3", "#e41a1c"]

        n = len(colors)
        colorscale = []
        for i, c in enumerate(colors):
            colorscale.append([i / n, c])
            colorscale.append([(i + 1) / n, c])

        phase_names = pd.Series(traj["cycle_phase"].values).map(dict(enumerate(phase_labels)))

        fig = go.Figure()
        # fig.add_trace(go.Scattergl( # gl not always supported by browser.
        fig.add_trace(
            go.Scatter(
                x=pd.to_datetime(traj["time"].values).astype(str),
                y=traj["z"].values,
                mode="markers",
                customdata=phase_names,
                hovertemplate="Time: %{x}<br>Pressure: %{y}<br>Phase: %{customdata}<extra></extra>",
                marker=dict(
                    size=6,
                    color=traj["cycle_phase"],
                    colorscale=colorscale,
                    cmin=0,
                    cmax=5,
                    showscale=False,  # Hover the points to get the phase info.
                    colorbar=dict(tickvals=[0.5, 1.5, 2.5, 3.5, 4.5], ticktext=phase_labels, title="Cycle phase"),
                ),
            )
        )

        fig.update_yaxes(autorange="reversed", title_text="Pressure (m)")
        fig.update_xaxes(title_text="Time", tickangle=45)
        fig.update_layout(modebar_remove=["autoScale", "sendChartToCloud", "lasso", "pan", "select", "zoom"])

        return fig
