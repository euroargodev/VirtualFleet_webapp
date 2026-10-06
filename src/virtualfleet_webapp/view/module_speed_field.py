import asyncio
import glob

import pandas as pd
import xarray as xr
from shiny import module, reactive, render, ui
from shiny_validate import InputValidator
from virtualargofleet import Velocity

from virtualfleet_webapp.logic.utils import (
    autobuild_variable_mapping_config_file,
    check_config_file,
    get_velocity_extent,
    list_speed_field_path,
    read_config_file,
    section_title,
)

tooltip_content = "" \
"Provide a velocity field in NetCDF format, either by browsing local files or by specifying" \
" a path to the data (either a file, a folder or a pattern such as './data/file*.nc')." \
" The velocity field must contain the eastward and northward components of the velocity)."\
" A variable mapping configuration file in JSON format can be provided" \
" to specify the names of these variables and their dimensions. If no mapping file" \
" is provided, an automatic mapping will be attempted."

@module.ui
def speed_field_ui():
    return ui.TagList(
        section_title(
            1,
            "Velocity Field",
            tooltip=tooltip_content
        ),
        # Hidden radio group driving which card is "selected"
        ui.div(
            {"class": "option-radio"},
            ui.input_radio_buttons(
                id="speed_field_mode",
                label=None,
                choices={"A": "Browse", "B": "Path"},
                selected="A",
            ),
        ),
        # Option A card
        ui.output_ui("card_browse_speed_field"),
        # Option B card
        ui.output_ui("card_write_speed_field"),
        ui.hr({"class": "section-divider"}),
    )


@module.server
def speed_field_server(input, output, session):

    iv_a = InputValidator()
    iv_a.add_rule("browse_config_file", check_config_file)
    iv_a.enable()

    iv_b = InputValidator()
    iv_b.add_rule("write_config_file", check_config_file)
    iv_b.enable()

    last_validated_option = reactive.Value(None)

    @reactive.effect
    @reactive.event(input.pick_a)
    def _():
        ui.update_radio_buttons(id="speed_field_mode", selected="A")

    @reactive.effect
    @reactive.event(input.pick_b)
    def _():
        ui.update_radio_buttons(id="speed_field_mode", selected="B")

    @render.ui
    def card_browse_speed_field():
        selected = input.speed_field_mode() == "A"
        card_class = "option-card selected" if selected else "option-card collapsed"

        # Header made with the help of AI (Claude Sonnet 5)
        header = ui.div(
            {"class": "option-header", "onclick": f"Shiny.setInputValue('{session.ns('pick_a')}', Math.random())"},
            ui.tags.i(class_="fa-solid fa-folder-open"),
            "Browse local data",
        )

        if not selected:
            return ui.div({"class": card_class}, header)

        return ui.div(
            {"class": card_class},
            header,
            ui.input_file(
                id="browse_speed_field_path",
                label=None,
                placeholder="Import local velocity field",
                accept=[".nc"],
                multiple=True,
            ),
            ui.input_file(
                id="browse_config_file",
                label=None,
                placeholder="Import variable mapping",
                accept=[".json"],
            ),
            ui.input_switch(
                id="periodic_switch_a", 
                label=ui.span("Periodic field", style="font-size: 0.90rem;"),
                value=False
            ),
            ui.input_task_button(
                id="validate_speed_field_a",
                label=ui.HTML('<i class="fa-solid fa-check"></i> Validate velocity field'),
                style="width: 100%; background: var(--bs-primary); color: white; border: none; margin-top: 0px;",
            ),
        )

    @render.ui
    def card_write_speed_field():
        selected = input.speed_field_mode() == "B"
        card_class = "option-card selected" if selected else "option-card collapsed"

        # Header made with the help of AI (Claude Sonnet 5)
        header = ui.div(
            {"class": "option-header", "onclick": f"Shiny.setInputValue('{session.ns('pick_b')}', Math.random())"},
            ui.tags.i(class_="fa-solid fa-keyboard"),
            "Provide path to data",
        )

        if not selected:
            return ui.div({"class": card_class}, header)

        return ui.div(
            {"class": card_class},
            header,
            ui.input_text(
                id="write_speed_field_path",
                label="",
                placeholder="Path to velocity field file or folder",
                value="./data/",
            ),
            ui.input_file(
                id="write_config_file", 
                label="", 
                placeholder="Import variable mapping file", 
                accept=[".json"]
            ),
            ui.input_switch(
                id="periodic_switch_b", 
                label=ui.span("Periodic field", style="font-size: 0.90rem;"),
                value=False
            ),
            ui.input_task_button(
                id="validate_speed_field_b",
                label=ui.HTML('<i class="fa-solid fa-check"></i> Validate velocity field'),
                style="width: 100%; background: var(--bs-primary); color: white; border: none; margin-top: 0px;",
            ),
        )

    def _build_velocity_field(src, mapping, periodicity):  # Internal use, should not be used elsewhere
        return Velocity(
            model="custom",
            src=src,
            variables=mapping["variables"],
            dimensions=mapping["dimensions"],
            isglobal=False,  # Need to see if this is should be specified by the user
            time_periodic=periodicity
        )

    # Opening a NetCDF can take a while (e.g. size) so better
    # use an async process (if app deployed on server at some point)
    @ui.bind_task_button(button_id="validate_speed_field_a")
    @ui.bind_task_button(button_id="validate_speed_field_b")
    @reactive.extended_task
    async def _load_velocity_field(src, mapping, periodicity):
        return await asyncio.to_thread(_build_velocity_field, src, mapping, periodicity)

    @reactive.effect
    @reactive.event(input.validate_speed_field_a)
    def _():
        # Upload velocity field
        files = input.browse_speed_field_path()
        if not files:
            ui.notification_show("Select local velocity field file(s).", type="error")
            return
        # Upload OR automatically build variable mapping
        config_file = input.browse_config_file()
        if not config_file:  # No variable mapping has been uploaded
            mapping = autobuild_variable_mapping_config_file(files[0]["datapath"])
            if not mapping:  # Autobuild failed
                ui.notification_show("Automatic mapping failed. Upload a variable mapping config file.", type="error")
                return
        else:
            if not iv_a.is_valid():
                ui.notification_show("Fix the mapping file.", type="error")
                return
            try:
                mapping = read_config_file(config_file[0]["datapath"])
            except Exception:
                ui.notification_show("Could not read the config file.", type="error")
                return
        # Load the velocity field from the selected files
        paths = [f["datapath"] for f in files]  # When uploading manually, it is automatically sorted by the upload order
        try:
            src = xr.combine_by_coords(
                [xr.open_dataset(p) for p in paths],
                compat="override",
                coords="minimal",
                combine_attrs="override",
            )
        except Exception as e:
            ui.notification_show(f"Could not open the velocity field: {e}", type="error")
            return
        last_validated_option.set("A")
        extent = get_velocity_extent(src, mapping["dimensions"])
        if input.periodic_switch_a():
            _load_velocity_field(src, mapping,extent["time_span"])
        else:
            _load_velocity_field(src, mapping, False)

    @reactive.effect
    @reactive.event(input.validate_speed_field_b)
    def _():
        path = input.write_speed_field_path()
        if not path:
            ui.notification_show("Provide a path to the velocity field.", type="error")
            return
        pattern = list_speed_field_path(path)  # used for Velocity(src=...)
        if not pattern:
            ui.notification_show("Path does not exist", type="error")
            return
        nc_file = next(glob.iglob(pattern), None)  # noqa: PTH207 (for ruff to pass)
        if nc_file is None:
            ui.notification_show("No .nc file found at this path.", type="error")
            return
        # Variable mapping config file can be uploaded or automatically built
        config_file = input.write_config_file()
        if not config_file:  # No variable mapping uploaded: build it automatically
            mapping = autobuild_variable_mapping_config_file(nc_file)
            if not mapping:  # Autobuild failed
                ui.notification_show("Automatic mapping failed. Upload a variable mapping config file.", type="error")
                return
        else:
            if not iv_b.is_valid():
                ui.notification_show("Fix the mapping file.", type="error")
                return
            try:
                mapping = read_config_file(config_file[0]["datapath"])
            except Exception:
                ui.notification_show("Could not read the config file.", type="error")
                return
        filenames = {k: pattern for k in mapping["variables"]}
        last_validated_option.set("B")
        extent = get_velocity_extent(filenames, mapping["dimensions"])
        if input.periodic_switch_b():
            _load_velocity_field(filenames, mapping, extent["time_span"])
        else:
            _load_velocity_field(filenames, mapping, False)

    @reactive.effect
    def _():
        status = _load_velocity_field.status()
        if status == "error":
            try:
                _load_velocity_field.result()
            except Exception as e:
                ui.notification_show(f"Could not load speed field: {e}", type="error")
        elif status == "success" and last_validated_option() is not None:
            # ui.notification_show("Velocity field OK", type="message")
            extent = velocity_field_extent()
            ui.notification_show(
                ui.HTML(
                    f"Temporal coverage:<br>{pd.to_datetime(extent['time_min'])} - {pd.to_datetime(extent['time_max'])}"
                ),
                duration=None,  # User needs to close the notification manually
                type="message",
            )

    @reactive.calc
    def velocity_field():
        if _load_velocity_field.status() != "success":
            return None
        return _load_velocity_field.result()

    @reactive.calc
    def velocity_field_extent():
        v = velocity_field()
        if v is None:
            return None
        return get_velocity_extent(v.field, v.dim)

    return velocity_field, velocity_field_extent
