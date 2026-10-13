import asyncio
import tempfile
from pathlib import Path

import cartopy.crs as ccrs
import cartopy.io.shapereader as shpreader
import matplotlib

matplotlib.use("Agg")  # Make sure matplotlib does not cause issue with processes in threads.

import numpy as np
import pandas as pd  # replace it with polars? Faster.
import plotly.graph_objects as go
import xarray as xr
from ipyleaflet import CircleMarker, Map, Polyline, ScaleControl, WidgetControl, basemap_to_tiles, basemaps
from ipywidgets import HTML, Dropdown
from matplotlib import colormaps
from matplotlib.colors import BoundaryNorm
from matplotlib.figure import Figure
from plotly.colors import qualitative
from shiny import module, reactive, render, ui
from shinywidgets import output_widget, render_plotly, render_widget
from virtualargofleet.utilities import simu2csv

from virtualfleet_webapp.logic.utils import load_bathymetry, read_index_prof, section_title

# Add path for cartopy coastline and land features
RESOURCES_DIR = Path(__file__).parents[1] / "resources"

tooltip_content = ui.HTML(
    "Read a simulation output (zarr file) to display the float trajectories<br>"
    "in the 'Simulation trajectories' tab.<br><br>"
    "Click on a profile location to see the full trajectory of that float<br>"
    "and its pressure time series."
)


@module.ui
def simulated_traj_ui():
    return ui.TagList(
        ui.div(section_title(None, "Preview simulation trajectories", tooltip=tooltip_content), id="results-section"),
        ui.div(
            ui.input_text(
                id="simulated_traj_path",
                label=ui.span("Path to simulation output", style="font-size: 0.90rem;"),
                # value="./simulations/default.zarr",
                value=None,
                placeholder="Write the path to your simulation results",
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
    return (
        ui.div(
            ui.card_body(
                output_widget("map_traj"),
                max_height="80vh",  # 80% of the viewport height
                padding=0,
                fill=False,
                style="flex: 0 0 100%;",  # Always take the full visible panel height
            ),
            ui.output_ui("plot_info_traj"),
            class_="html-fill-item html-fill-container",  # Panel height: lets card use flex
            style="overflow-y: auto;",  # Scroll when content overflows
        ),
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
        scroll_wheel_zoom=False,
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
        # Show the trajectories tab (navset defined outside the module, hence the root session to skip the namespace)
        ui.update_navset("main_tabs", selected="Simulation trajectories", session=session.root_scope())

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

        float_colors = qualitative.Alphabet  # 26 colours, the maximum here (https://plotly.com/python/discrete-color/)

        for i, (lat_init, lon_init) in enumerate(zip(lat_deployment, lon_deployment, strict=True)):
            lat_init, lon_init = float(lat_init), float(lon_init)
            float_color = float_colors[i % len(float_colors)]

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
                line = Polyline(locations=trajectory, color=float_color, weight=2, fill=False)
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
                if row.cycle_number == 0:
                    point = CircleMarker(
                        location=(row.latitude, row.longitude),
                        radius=10,
                        color="black",
                        fill_color=float_color,
                        fill_opacity=1,
                        weight=2,
                        popup=popup,
                    )
                else:
                    point = CircleMarker(
                        location=(row.latitude, row.longitude),
                        radius=5,
                        color="black",
                        fill_color=float_color,
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
                ui.card_body(ui.output_plot("trajectory_map", height="400px"), padding=0),
                ui.card_body(output_widget("trajectory_plots", height="400px"), padding=0),
            ),
            fill=False,
            class_="flex-shrink-0",
            id="float_plots",
        )

    def _trajectory_map(traj):
        lat = traj["lat"].values
        lon = traj["lon"].values
        time = pd.to_datetime(traj["time"].values)
        days = (time - time[0]).total_seconds() / 86400

        # Trajectory bounding box with some margin around it
        pad = 2  # degrees
        lon_min, lon_max = float(np.nanmin(lon)) - pad, float(np.nanmax(lon)) + pad
        lat_min, lat_max = max(float(np.nanmin(lat)) - pad, -90), min(float(np.nanmax(lat)) + pad, 90)

        # Based on https://cartopy.readthedocs.io/stable/gallery/lines_and_polygons/ocean_bathymetry.html
        depths_str, shp_dict = load_bathymetry(lat_min, lat_max, lon_min, lon_max)

        # Construct a discrete colormap with colors corresponding to each depth
        depths = depths_str.astype(int)
        n = len(depths)
        nudge = 0.01  # shift bin edge slightly to include data
        boundaries = [min(depths), *sorted(depths + nudge)]  # low to high
        norm = BoundaryNorm(boundaries, n)
        blues_cm = colormaps["Blues_r"].resampled(n)
        colors_depths = blues_cm(norm(depths))

        # Set up plot (Figure directly instead of pyplot.subplots because pyplot is not thread safe
        fig = Figure(figsize=(9, 7))
        ax = fig.add_subplot(projection=ccrs.LambertCylindrical())
        ax.set_extent([lon_min, lon_max, lat_min, lat_max], crs=ccrs.PlateCarree())  # x0, x1, y0, y1

        # Iterate and plot feature for each depth level
        for i, depth_str in enumerate(depths_str):
            ax.add_geometries(shp_dict[depth_str].geometries(), crs=ccrs.PlateCarree(), color=colors_depths[i])

        # Add standard features
        coast_reader = shpreader.Reader(
            RESOURCES_DIR / "ne_10m_coastline" / "ne_10m_coastline.shp", bbox=(lon_min, lat_min, lon_max, lat_max)
        )
        ax.add_geometries(
            coast_reader.geometries(), crs=ccrs.PlateCarree(), facecolor="grey", edgecolor="black", linewidth=0.5
        )  # Coastline
        ax.gridlines(draw_labels={"bottom": "x", "left": "y"})

        # Convert vector bathymetries to raster (saves a lot of disk space)
        # while leaving labels as vectors
        ax.set_rasterized(True)

        # Add float positions
        ax.scatter(lon, lat, c=days, cmap="magma_r", s=12, transform=ccrs.PlateCarree(), zorder=3)

        # Add float deployment
        ax.scatter(
            lon[0],
            lat[0],
            s=90,
            c="black",
            edgecolors="white",
            transform=ccrs.PlateCarree(),
            zorder=4,
            label="Deployment",
        )
        ax.legend(loc="upper right", fontsize="small")

        return fig

    def _phase_plot(traj):
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
        fig.update_xaxes(title_text="Time")
        fig.update_layout(modebar_remove=["autoScale", "sendChartToCloud", "lasso", "pan", "select", "zoom"])

        return fig

    # Build both figures in an async process
    def _build_float_figures(ds, idx):
        # idx = float_index, that is the selected trajectory
        traj = ds.isel(trajectory=idx)
        return _trajectory_map(traj), _phase_plot(traj)

    @reactive.extended_task
    async def build_float_figures(ds, idx):
        return await asyncio.to_thread(_build_float_figures, ds, idx)

    @reactive.effect
    @reactive.event(selected_trajectory)
    def _():
        idx = selected_trajectory()
        if idx is None or read_zarr_file.status() != "success":
            return
        build_float_figures(read_zarr_file.result(), idx)
        if build_float_figures.status() == "running":
            ui.notification_show(
                ui.HTML("Computing plots...<br>If you zarr file is heavy, it can take a while, be patient."),
                type="message",
            )

        # Scroll down to the (still empty) plot card directly.
        async def _scroll_to_plots():
            await session.send_custom_message("scroll_to", {"id": session.ns("float_plots")})

        session.on_flushed(_scroll_to_plots)  # Needed, otherwise the scroll at first click won't work

    @reactive.effect
    def _():
        status = build_float_figures.status()
        if status == "error":
            try:
                build_float_figures.result()
            except Exception as e:
                ui.notification_show(f"Could not plot float data: {e}", type="error")

    @output
    @render.plot
    def trajectory_map():
        if (
            selected_trajectory() is None or build_float_figures.status() == "error"
        ):  # Keep the busy state for "running" async func
            return None
        return build_float_figures.result()[0]

    @output
    @render_plotly
    def trajectory_plots():
        if selected_trajectory() is None or build_float_figures.status() == "error":
            return None
        return build_float_figures.result()[1]
