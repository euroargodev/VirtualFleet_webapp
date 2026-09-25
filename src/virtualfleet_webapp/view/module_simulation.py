import asyncio
import io
import json
import math
import zipfile
from datetime import timedelta
from pathlib import Path

from shiny import module, reactive, render, ui
from shiny_validate import InputValidator
from virtualargofleet import VirtualFleet

from virtualfleet_webapp.logic.utils import (
    build_deployment_plan_geojson,
    check_positive_number,
    flatten_mission_config,
    section_title,
)

SIMULATIONS_FOLDER = "./simulations/"  # Don't want to let the user choses that.


def _run_simulation_with_progress(vfleet, duration, step, record, output_path, on_progress):
    """Run VirtualFleet simulation and compute progress."""

    duration = duration if isinstance(duration, timedelta) else timedelta(days=duration)
    step = step if isinstance(step, timedelta) else timedelta(minutes=step)
    record = record if isinstance(record, timedelta) else timedelta(hours=record)

    # https://github.com/euroargodev/VirtualFleet/blob/e06944f1289a742991854069a07ba549d10693fd/virtualargofleet/virtualargofleet.py#L242
    particle_set = vfleet.ParticleSet
    total_kernels = max(1, math.ceil(duration / record))  # record = writing step, duration = simulation length
    kernels_done = 0

    def _tick():
        nonlocal kernels_done  # Needed because kernels_done declared outside the function
        kernels_done += 1
        on_progress(min(kernels_done, total_kernels), total_kernels)

    # See https://github.com/Parcels-code/Parcels/blob/v3.1.4/parcels/particleset.py#L987
    particle_set.execute(
        pyfunc=vfleet._parcels["kernels"],  # Kernel function to execute.
        runtime=duration,
        dt=step,
        verbose_progress=True,
        output_file=particle_set.ParticleFile(name=str(output_path), outputdt=record),
        postIterationCallbacks=[_tick],
        callbackdt=record,
    )
    return vfleet


@module.ui
def simulation_ui():
    return ui.TagList(
        section_title(4, "Simulation Parameters", tooltip="TBD"),
        ui.div(
            {"class": "mission-grid"},
            ui.div(
                ui.input_numeric(
                    id="simulation_time",
                    label=ui.span("Simulation length (days)", style="font-size: 0.90rem;"),
                    value=1,
                    update_on="blur",
                )
            ),
            ui.div(
                ui.input_numeric(
                    id="time_step",
                    label=ui.span("Time step (minutes)", style="font-size: 0.90rem;"),
                    value=5,
                    update_on="blur",
                )
            ),
            ui.div(
                ui.input_numeric(
                    id="writing_step",
                    label=ui.span("Writing time step (hours)", style="font-size: 0.90rem;"),
                    value=1,
                    update_on="blur",
                )
            ),
            ui.div(
                ui.input_text(
                    id="simulation_name",
                    label=ui.span("Simulation name", style="font-size: 0.90rem;"),
                    value="default",
                    update_on="blur",
                )
            ),
        ),
        ui.input_task_button(
            id="run_simulation",
            label=ui.HTML('<i class="fa-solid fa-play"></i> Run Simulation'),
            class_="btn-primary",
            label_busy="Running...",
        ),
        ui.output_ui("simulation_progress"),
        ui.output_ui("save_simulation_slot"),
    )


@module.server
def simulation_server(input, output, session, speed_field, deployment_plan, mission_config):

    # Init progress bar values
    progress_slot = [0, None]

    iv = InputValidator()
    iv.add_rule("simulation_time", check_positive_number)
    iv.add_rule("time_step", check_positive_number)
    iv.add_rule("writing_step", check_positive_number)
    iv.enable()

    def _run_simulation(plan, fieldset, mission, duration, step, record, output_file):
        vfleet = VirtualFleet(plan=plan, fieldset=fieldset, mission=mission)

        def on_progress(n, total):
            progress_slot[0], progress_slot[1] = n, total

        output_path = Path(SIMULATIONS_FOLDER) / output_file
        _run_simulation_with_progress(vfleet, duration, step, record, output_path, on_progress)
        return 

    @ui.bind_task_button(button_id="run_simulation")
    @reactive.extended_task
    async def run_simulation(plan, fieldset, mission, duration, step, record, output_file):
        # progress_slot[0], progress_slot[1] = 0, None # Needed to avoid a second simulation that starts with 100%
        return await asyncio.to_thread(_run_simulation, plan, fieldset, mission, duration, step, record, output_file)

    @reactive.effect
    def _():
        if run_simulation.status() == "error":
            try:
                run_simulation.result()
            except Exception as e:
                ui.notification_show(f"Simulation failed: {e}", type="error")

    @render.ui
    def simulation_progress():
        reactive.invalidate_later(1)
        n, total = progress_slot
        pct = (n / total * 100) if total else 0
        return ui.div( # Thanks to Claude Sonnet 5 for the CSS
            {"class": "progress", "style": "height: 1.25rem;"},
            ui.div(
                {
                    "class": "progress-bar",
                    "role": "progressbar",
                    "style": f"width: {pct:.0f}%;",
                    "aria-valuenow": f"{pct:.0f}",
                    "aria-valuemin": "0",
                    "aria-valuemax": "100",
                },
                f"{pct:.0f}%",
            ),
        )

    @reactive.effect
    @reactive.event(input.run_simulation)
    def _():
        fieldset = speed_field()
        if not fieldset:
            ui.notification_show("Upload a variable mapping config file first.", type="error")
            return
        plan = deployment_plan()
        if not plan:
            ui.notification_show("Validate a deployment plan first.", type="error")
            return
        config = mission_config()
        if not config:
            ui.notification_show("Validate a mission configuration first.", type="error")
            return
        if not iv.is_valid():
            ui.notification_show("Fix the highlighted simulation parameters first.", type="error")
            return

        run_simulation(
            plan,
            fieldset,
            flatten_mission_config(config),
            input.simulation_time(),
            input.time_step(),
            input.writing_step(),
            input.simulation_name(),
        )

    @render.ui
    def save_simulation_slot():
        if run_simulation.status() != "success":
            return ui.input_action_button(
                id="save_simulation_disabled",
                label=ui.HTML('<i class="fa-solid fa-save"></i> Save Simulation (.zip)'),
                class_="btn-secondary",
                disabled=True,
            )
        return ui.download_button(
            id="save_simulation", label=ui.HTML('<i class="fa-solid fa-save"></i> Save Simulation'), class_="btn-light"
        )

    @render.download_button(filename=lambda: f"{input.simulation_name()}.zip")
    def save_simulation():
        if run_simulation.status() != "success":
            ui.notification_show("Run a simulation successfully before saving.", type="error")
            raise Exception("No completed simulation to save yet.")
            

        name = input.simulation_name()
        zarr_name = name if name.endswith(".zarr") else f"{name}.zarr"
        zarr_path = Path(SIMULATIONS_FOLDER) / zarr_name
        if not zarr_path.is_dir(): # zarr is a directory
            ui.notification_show(f"Could not find simulation output at {zarr_path}.", type="error")
            raise Exception(f"Missing zarr output: {zarr_path}")

        buffer = io.BytesIO() # Create archive in memory, not in disk (in a temp file)
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            # Simulation output (zarr store is a directory of many files).
            for full_path in zarr_path.rglob("*"):
                if full_path.is_file():
                    archive_name = Path(zarr_name) / full_path.relative_to(zarr_path)
                    zf.write(full_path, archive_name)

            # Deployment plan, as GeoJSON.
            plan = deployment_plan()
            if plan:
                zf.writestr("deployment_plan.geojson", json.dumps(build_deployment_plan_geojson(plan), indent=2))

            # Mission configuration(s).
            config = mission_config()
            if config:
                zf.writestr("mission_config.json", json.dumps(config, indent=2))

            # Variable mapping.
            fieldset = speed_field()
            if fieldset:
                mapping = {"variables": fieldset.var, "dimensions": fieldset.dim}
                zf.writestr("variable_mapping.json", json.dumps(mapping, indent=2))

        yield buffer.getvalue() # Write on disk now

    return run_simulation
