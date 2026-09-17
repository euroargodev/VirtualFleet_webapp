"""
Application User Interface
"""

from shiny import ui

# import custom modules
from virtualfleet_webapp.view.module_deployment_plan import deployment_plan_map_ui, deployment_plan_ui
from virtualfleet_webapp.view.module_mission import mission_config_ui
from virtualfleet_webapp.view.module_simulated_traj import simulated_traj_ui
from virtualfleet_webapp.view.module_simulation import simulation_ui
from virtualfleet_webapp.view.module_speed_field import speed_field_ui

app_ui = ui.page_fluid(
    # Style
    ui.head_content(
        ui.tags.link(
            rel="stylesheet",
            href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.2/css/all.min.css",
        ),
        ui.tags.link(rel="stylesheet", href="styles.css"),
    ),
    # Busy indicator
    ui.busy_indicators.use(),
    # Navbar layout
    ui.navset_bar(
        navbar_options=ui.navbar_options(bg="var(--bs-primary)", theme="dark"),
        title=ui.row(
            ui.column(
                4,
                ui.div(
                    ui.a(
                        ui.img(
                            src="images/logo-EuroArgo.png",
                            style="height:60px; display:block; pointer-events:none;",
                        ),
                        href="https://www.euro-argo.eu/",
                        target="_blank",
                        style="display:inline-block; cursor:pointer; position:relative;",
                    ),
                    ui.a(
                        ui.img(
                            src="images/logo-ArgoFrance.png",
                            style="height:50px; display:block; pointer-events:none;",
                        ),
                        href="https://www.argo-france.fr/",
                        target="_blank",
                        style="display:inline-block; cursor:pointer; position:relative;",
                    ),
                    ui.a(
                        ui.img(
                            src="images/logo-LOPS.png",
                            style="height:50px; display:block; pointer-events:none;",
                        ),
                        href="https://www.umr-lops.fr/",
                        target="_blank",
                        style="display:inline-block; cursor:pointer; position:relative;",
                    ),
                    ui.span("VirtualFleet", style="font-weight: 700; font-size: 1.2rem;"),
                    style="display: flex; align-items: center; gap: 12px;",
                ),
            ),
        ),
    ),
    # Sidebar layout
    ui.layout_sidebar(
        ui.sidebar(
            # Part 1 - Speed Field
            speed_field_ui("speed_field"),
            # Part 2 - Deployment Plan
            deployment_plan_ui("deployment_plan"),
            # Part 3 - Mission Parameters
            mission_config_ui("mission_config"),
            # Part 4 - Simulation Parameters
            simulation_ui("simulation"),
            # Sidebar layout options
            bg="",
            width=420,
            gap=10, # Vertical spacing in the sidebar
        ),
        # Main panel content
        ui.navset_card_underline(
            ui.nav_panel(
                "Deployment Map",
                deployment_plan_map_ui("deployment_plan"),
            ),
            ui.nav_panel(
                "Simulation Results",
                simulated_traj_ui("simulated_traj"),
            ),
        ),
        height="80vh", # For a scrollable sidebar.
    ),
    # Footer
    ui.div(
        ui.p(
            "This repository is developed within the framework of the Euro-Argo ONE project.",
            style="margin-bottom: 4px;",
        ),
        ui.p(
            "This project has received funding from the European Union's Horizon 2020 research "
            "and innovation programme under project no ",
            ui.tags.strong("101188133"),
            ".",
            style="margin-bottom: 4px;",
        ),
        ui.p(
            "Call ",
            ui.tags.strong("HORIZON-INFRA-2024-DEV-03"),
            ": Developing, consolidating and optimising the European research infrastructures "
            "landscape, maintaining global leadership.",
            style="margin-bottom: 12px;",
        ),
        ui.div(
            ui.a(
                "Euro-Argo Website",
                href="https://www.euro-argo.eu/",
                target="_blank",
                class_="footer-link",
                style="font-weight: 700;",
            ),
            ui.span(" | ", style="margin: 0 10px;"),
            ui.a(
                "GitHub",
                href="https://github.com/euroargodev",
                target="_blank",
                class_="footer-link",
                style="font-weight: 700;",
            ),
        ),
        ui.div(
            "Interface developed by ",
            ui.a(
                "Florian Ricour",
                href="https://www.fricour.com",
                target="_blank",
                style="text-decoration: underline;",
            ),
            style="margin-top: 10px;",
        ),
        style=("text-align: center; padding: 10px; font-size: 0.85rem; color: #6B6B6B;"),
    ),
    # use brand theme
    theme=ui.Theme.from_brand(__file__),
)
