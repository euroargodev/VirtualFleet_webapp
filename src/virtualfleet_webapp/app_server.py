"""
Server logic
"""

from shiny import reactive

# import custom modules
from virtualfleet_webapp.view.module_deployment_plan import deployment_plan_server
from virtualfleet_webapp.view.module_mission import mission_config_server
from virtualfleet_webapp.view.module_simulated_traj import simulated_traj_server
from virtualfleet_webapp.view.module_simulation import simulation_server
from virtualfleet_webapp.view.module_speed_field import speed_field_server


def server(input, output, session):

    # Part 1 - Speed field and config file
    speed_field, speed_field_extent = speed_field_server("speed_field")

    # Part 2 - Deployment plan
    deployment_plan = deployment_plan_server("deployment_plan", speed_field_extent)

    # Part 3 - Mission configuration
    mission_config = mission_config_server("mission_config")

    # Part 4 - Simulation
    simulation_server("simulation", speed_field, deployment_plan, mission_config)

    # Part 5 - Simulated trajectories
    simulated_traj_server("simulated_traj")

    # Little trick to keep the app alive
    # Actually, during the simulation (async process), there is a 1 second feedback
    # for the progress bar so it's OK. However, if the user gets back on the app
    # after the simulation is finished since a while it will be idle/timed out automatically.
    # Hence, here is a little "heartbeat" every 5 minutes. Might be needed to decrease it.
    @reactive.effect()
    def _():
        reactive.invalidate_later(300)
