from typing import Any
import dash
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dash import (
    ALL,
    MATCH,
    ClientsideFunction,
    Input,
    Output,
    State,
    callback,
    clientside_callback,
    dcc,
    html,
    register_page,
)
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc

from models import ViewByDimensionTypeLiteral
from utils import TreemapTransformer, TremapDataFetcher, fetch_budgets
from utils.definitions import (
    LanguageTypeLiteral,
    SpendingScopeLiteral,
    SpendingTypeLiteral,
)
from utils.calculate import Calculator
from utils.helper import add_breaks

import logging

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

register_page(__name__, path="/")

TREEMAP_CONFIG = dcc.Graph.Config(
    displayModeBar=False,
    displaylogo=False,
    responsive=True,
)


def fetch_treemap_data(
    budget_id: int | None = None,
    spending_type: SpendingTypeLiteral = "ALL",
    spending_scope: SpendingScopeLiteral = "ABSOLUTE",
    character_limit: int = 30,
) -> tuple[list[str], list[str], list[float], list[str]]:
    """
    Fetch treemap data based on the provided filters.

    Args:
        budget_id (int | None): The budget dataset ID to filter by.
        viewby (ViewByDimensionTypeLiteral): The dimension to view by.
        spending_type (SpendingTypeLiteral): The type of spending to filter by.
        spending_scope (SpendingScopeLiteral): The scope of spending to filter by.

    Returns:
        list[dict[str, Any]]: The fetched treemap data.
    """
    data_fetcher = TremapDataFetcher()
    dimensions, programs, sum_mapping = data_fetcher.fetch_data(
        budget_id=budget_id,
        spending_type=spending_type,
        spending_scope=spending_scope,
    )
    transformer = TreemapTransformer()
    labels, parents, values, metadata = transformer.transform_data(
        dimensions, programs, sum_mapping, translated_names=False
    )
    calculator = Calculator(spending_scope=spending_scope)
    values = [calculator.calculate(value) if value is not None else 0.0 for value in values]
    labels = [add_breaks(label, interval=character_limit) for label in labels]
    parents = [add_breaks(parent, interval=character_limit) for parent in parents]
    return labels, parents, values, metadata


def generate_figure(
    labels: list[str],
    parents: list[str],
    values: list[float],
    metadata: list[str],
    viewby: ViewByDimensionTypeLiteral = "MINISTRY",
    language: LanguageTypeLiteral = "EN",
) -> go.Figure:
    fig = px.treemap(
        names=labels,
        parents=parents,
        values=values,
        hover_data={"level": metadata},
    )
    fig.update_layout(margin=dict(t=30, b=5, l=5, r=5))
    return fig


def layout(**other_kwargs) -> html.Div:
    """
    Defines the static layout of the page. The graph is empty initially and
    will be populated by a callback.

    Args:
        budgettype (Any, optional): The initial budget type from the URL.
        **other_unknown_query_strings: Catches any other query parameters.

    Returns:
        html.Div: The Dash component tree for the page layout.
    """

    viewby_items = [
        dbc.DropdownMenuItem(label, id={"type": "viewby-item", "value": value})
        for label, value in [
            ("Ministry", "MINISTRY"),
            ("Chapter", "CHAPTER"),
            ("Program", "PROGRAM"),
        ]
    ]

    spending_type_items = [
        dbc.DropdownMenuItem(label, id={"type": "spending-type-item", "value": value})
        for label, value in [
            ("All", "ALL"),
            ("Military Only", "MILITARY"),
        ]
    ]

    spending_scope_items = [
        dbc.DropdownMenuItem(label, id={"type": "spending-scope-item", "value": value})
        for label, value in [
            ("Billion RUB", "ABSOLUTE"),
            ("% full-year GDP", "PERCENT_GDP_FULL_YEAR"),
            ("% year-to-year GDP", "PERCENT_GDP_YEAR_TO_YEAR"),
            ("% full-year spending", "PERCENT_FULL_YEAR_SPENDING"),
            ("% year-to-year spending", "PERCENT_YEAR_TO_YEAR_SPENDING"),
            ("% year-to-year revenue", "PERCENT_YEAR_TO_YEAR_REVENUE"),
        ]
    ]
    return html.Div(
        [
            # Store currently selected filter values (these replace dcc.Dropdown.value)
            dcc.Store(id="store-budget-options"),
            dcc.Store(id="store-budget-id"),
            dcc.Store(id="store-viewby", data="MINISTRY"),
            dcc.Store(id="store-spending-type", data="ALL"),
            dcc.Store(id="store-spending-scope", data="ABSOLUTE"),
            # Location component to access URL parameters
            dcc.Location(id="url"),
            # This dummy div is the target for our clientside callback. It's required for the
            # callback to have an Output, but it doesn't need to be visible.
            html.Div(id="dummy-treemap-output", style={"display": "none"}),
            # Add Buttons and dropdowns for filtering by budget type
            dbc.Stack(
                [
                    html.Div(
                        [
                            html.Img(
                                src="/assets/logo/logo.svg",
                                style={"height": "2em"},
                            ),
                        ],
                        style={"margin-right": "20px", "align-self": "center"},
                    ),
                    dbc.Stack(
                        [
                            # Budget dataset menu
                            dbc.DropdownMenu(
                                label="Budget",
                                children=[],  # will be set by callback
                                id="menu-budget",
                                direction="down",
                                class_name="me-2 scroll-menu",
                                # Make the dropdown list scrollable to handle many budgets
                            ),
                            # View-by menu
                            dbc.DropdownMenu(
                                label="View by",
                                children=viewby_items,
                                id="menu-viewby",
                                direction="down",
                                class_name="me-2",
                            ),
                            # Spending type menu
                            dbc.DropdownMenu(
                                label="Spending type",
                                children=spending_type_items,
                                id="menu-spending-type",
                                direction="down",
                                class_name="me-2",
                            ),
                            # Spending scope menu
                            dbc.DropdownMenu(
                                label="Spending scope",
                                children=spending_scope_items,
                                id="menu-spending-scope",
                                direction="down",
                                class_name="me-2",
                            ),
                        ],
                        direction="horizontal",
                        gap=2,
                        class_name="me-auto",
                    ),
                    dbc.Stack(
                        [
                            dbc.Button(
                                html.Img(
                                    src="/assets/icons/photo_camera.svg",
                                    style={"width": "2em", "height": "2em"},
                                ),
                                id="btn-download-image",
                                title="Download Treemap Plot as PNG",
                            ),
                            dcc.Download(id="download-treemap-image"),
                            dbc.Button(
                                html.Img(
                                    src="/assets/icons/download.svg",
                                    style={"width": "2em", "height": "2em"},
                                ),
                                id="btn-download-csv",
                                title="Download Treemap Data as CSV",
                            ),
                            dcc.Download(id="download-treemap-data"),
                            dbc.Button(
                                html.Img(
                                    src="/assets/icons/stacked_bar_chart.svg",
                                    style={"width": "2em", "height": "2em"},
                                ),
                                title="Switch to Time Series View",
                            ),
                            dbc.Button(
                                html.Img(
                                    src="/assets/icons/info.svg",
                                    style={"width": "2em", "height": "2em"},
                                ),
                                title="About This Project",
                                href="/about",
                            ),
                        ],
                        direction="horizontal",
                        gap=2,
                    ),
                ],
                direction="horizontal",
                style={
                    "margin-bottom": "10px",
                    "margin-top": "10px",
                    "margin-left": "15px",
                    "margin-right": "15px",
                },
            ),
            # add divider line
            dbc.Row(html.Hr()),
            html.Div(
                # Graph to display the treemap
                [
                    dcc.Store(id="treemap-store"),
                    dcc.Graph(id="treemap-graph", config=TREEMAP_CONFIG),
                ],
                style={"width": "100%", "height": "90vh"},
            ),
        ]
    )


# Update your existing callbacks to read from the stores instead of the dcc.Dropdowns.
@callback(
    Output("treemap-graph", "figure"),
    Input("store-budget-id", "data"),
    Input("store-viewby", "data"),
    Input("store-spending-type", "data"),
    Input("store-spending-scope", "data"),
)
def update_figure_from_filters(
    budget_id: int | None = None,
    viewby: ViewByDimensionTypeLiteral = "MINISTRY",
    spending_type: SpendingTypeLiteral = "ALL",
    spending_scope: SpendingScopeLiteral = "ABSOLUTE",
) -> go.Figure:
    # Fetch and render using the selected values from stores
    labels, parents, values, metadata = fetch_treemap_data(
        budget_id=budget_id,
        spending_type=spending_type,
        spending_scope=spending_scope,
    )
    return generate_figure(labels, parents, values, metadata, viewby=viewby, language="EN")


# Callback to handle store
@callback(
    Output("treemap-store", "data"),
    Input("store-budget-id", "data"),
    Input("store-viewby", "data"),
    Input("store-spending-type", "data"),
    Input("store-spending-scope", "data"),
)
def update_store_data(
    budget_id: int | None = None,
    viewby: ViewByDimensionTypeLiteral = "MINISTRY",
    spending_type: SpendingTypeLiteral = "ALL",
    spending_scope: SpendingScopeLiteral = "ABSOLUTE",
) -> dict[str, Any]:
    """
    This callback updates the store with the current data based on filters.

    Returns:
        dict[str, Any]: The data to store.
    """
    filter_data = {
        "budget_id": budget_id,
        "viewby": viewby,
        "spending_type": spending_type,
        "spending_scope": spending_scope,
    }
    return filter_data


@callback(
    Output("download-treemap-data", "data"),
    Input("btn-download-csv", "n_clicks"),
    State("treemap-store", "data"),
    prevent_initial_call=True,
)
def download_data(n_clicks, data) -> dict[str, Any]:
    """
    Callback to download the current treemap data as a csv file.
    Returns:
        dict[str, Any]: The data for download.
    """
    labels, parents, values, metadata = fetch_treemap_data(
        budget_id=data["budget_id"],
        spending_type=data["spending_type"],
        spending_scope=data["spending_scope"],
    )
    return dcc.send_data_frame(  # type: ignore
        pd.DataFrame(
            {
                "Label": labels,
                "Parent": parents,
                "Value": values,
                "Level": metadata,
            }
        ).to_csv,
        "treemap_data.csv",
        sep=";",
        index=False,
        encoding="utf-8",
    )


@callback(
    Output("download-treemap-image", "data"),
    Input("btn-download-image", "n_clicks"),
    State("treemap-graph", "figure"),
    prevent_initial_call=True,
)
def download_image(n_clicks: int | None, figure_json: dict) -> dict[str, Any] | None:
    """
    Generate a PNG image from the current treemap figure and start a download.

    Notes:
    - Uses the already-rendered figure from the Graph (keeps current logic and avoids recomputation).
    - Requires 'kaleido' installed for Plotly static image export.
    """
    # If there is no click or figure, do nothing
    if not n_clicks or not figure_json:
        return None

    # Reconstruct a Plotly Figure from the JSON stored in the Graph
    fig = go.Figure(figure_json)

    # Convert the figure to PNG bytes (kaleido backend)
    image_bytes = fig.to_image(format="png", scale=3.0)  # Ensure 'kaleido' is in your dependencies

    # Send bytes to the browser as a downloadable file
    return dcc.send_bytes(image_bytes, "treemap_figure.png")  # type: ignore


# View-by selection
@callback(
    Output("store-viewby", "data"),
    Input({"type": "viewby-item", "value": "MINISTRY"}, "n_clicks"),
    Input({"type": "viewby-item", "value": "CHAPTER"}, "n_clicks"),
    Input({"type": "viewby-item", "value": "PROGRAM"}, "n_clicks"),
    prevent_initial_call=True,
)
def select_viewby(n_min, n_chap, n_prog):
    """Update viewby store based on which menu item was clicked."""
    if n_prog:
        return "PROGRAM"
    if n_chap:
        return "CHAPTER"
    if n_min:
        return "MINISTRY"
    raise PreventUpdate


# Spending type selection
@callback(
    Output("store-spending-type", "data"),
    Input({"type": "spending-type-item", "value": "ALL"}, "n_clicks"),
    Input({"type": "spending-type-item", "value": "MILITARY"}, "n_clicks"),
    prevent_initial_call=True,
)
def select_spending_type(n_all, n_mil):
    """Update spending_type store."""
    if n_mil:
        return "MILITARY"
    if n_all:
        return "ALL"
    raise PreventUpdate


# Spending scope selection
@callback(
    Output("store-spending-scope", "data"),
    Input({"type": "spending-scope-item", "value": "ABSOLUTE"}, "n_clicks"),
    Input({"type": "spending-scope-item", "value": "PERCENT_GDP_FULL_YEAR"}, "n_clicks"),
    Input({"type": "spending-scope-item", "value": "PERCENT_GDP_YEAR_TO_YEAR"}, "n_clicks"),
    Input({"type": "spending-scope-item", "value": "PERCENT_FULL_YEAR_SPENDING"}, "n_clicks"),
    Input({"type": "spending-scope-item", "value": "PERCENT_YEAR_TO_YEAR_SPENDING"}, "n_clicks"),
    Input({"type": "spending-scope-item", "value": "PERCENT_YEAR_TO_YEAR_REVENUE"}, "n_clicks"),
    prevent_initial_call=True,
)
def select_spending_scope(n_abs, n_gdp_full, n_gdp_yty, n_spend_full, n_spend_yty, n_rev_yty):
    """Update spending_scope store."""
    if n_rev_yty:
        return "PERCENT_YEAR_TO_YEAR_REVENUE"
    if n_spend_yty:
        return "PERCENT_YEAR_TO_YEAR_SPENDING"
    if n_spend_full:
        return "PERCENT_FULL_YEAR_SPENDING"
    if n_gdp_yty:
        return "PERCENT_GDP_YEAR_TO_YEAR"
    if n_gdp_full:
        return "PERCENT_GDP_FULL_YEAR"
    if n_abs:
        return "ABSOLUTE"
    raise PreventUpdate


@callback(
    Output("store-budget-options", "data"),
    Output("store-budget-id", "data"),
    Output("menu-budget", "children"),
    Input("url", "pathname"),  # fire once on load
    prevent_initial_call=False,
)
def init_budgets(_):
    # Fetch once and share everywhere via Store
    options = [
        {"label": b["name_translated"] or b["name"], "value": b["id"]} for b in fetch_budgets()
    ]
    # Build menu items with pattern ids
    items = [
        dbc.DropdownMenuItem(opt["label"], id={"type": "budget-item", "value": opt["value"]})
        for opt in options
    ]
    default_value = options[0]["value"] if options else None
    return options, default_value, items


@callback(
    Output("store-budget-id", "data", allow_duplicate=True),
    Input("store-budget-options", "data"),
    Input({"type": "budget-item", "value": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def select_budget_dynamic(options, clicks):
    """
    Update selected budget_id when any budget menu item is clicked.

    Fix:
    - Use dash.callback_context.triggered_id (parsed) instead of json.loads(prop_id).
    - Only act when the triggered id is a dict with type == "budget-item".
    """
    ctx = dash.callback_context

    # If nothing triggered, do nothing
    if not ctx.triggered:
        raise PreventUpdate

    # triggered_id is either a dict (for pattern-matched components) or a string id
    trig = getattr(ctx, "triggered_id", None)

    # Guard: ignore triggers from non-budget inputs (e.g., store-budget-options)
    if not isinstance(trig, dict):
        # Not a pattern-matched id -> ignore
        raise PreventUpdate

    # Guard: ensure we only react to budget-item clicks
    if trig.get("type") != "budget-item":
        raise PreventUpdate

    selected_value = trig.get("value")
    if selected_value is None:
        # No value in id -> ignore
        raise PreventUpdate

    # Return the selected budget id to the store
    return selected_value


# Clientside callback to handle URL focus parameter and click simulation
clientside_callback(
    ClientsideFunction(namespace="clientside", function_name="findAndClickSlice"),
    Output("dummy-treemap-output", "children"),
    Input("url", "search"),  # Listen directly to URL changes
    Input("treemap-graph", "figure"),  # Also listen to figure updates to re-trigger focus
    prevent_initial_call=True,  # Only run when inputs change
)
