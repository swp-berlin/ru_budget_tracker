import logging
from typing import Any, Optional

import dash
import dash_bootstrap_components as dbc
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dash import (
    ALL,
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

from utils import BarChartDataFetcher, BarchartTransformer, fetch_budgets
from utils.calculate import Calculator
from utils.definitions import (
    LanguageTypeLiteral,
    UnitLiteral,
    SpendingTypeLiteral,
    ViewByDimensionTypeLiteral,
)
from utils.helper import add_breaks

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

register_page(__name__, path="/timeseries", title="Time Series View")

# Graph config kept simple and explicit for production clarity
TIMESERIES_CONFIG = dcc.Graph.Config(
    displayModeBar=False,
    displaylogo=False,
    responsive=True,
)

# Menu option definitions to avoid duplication and keep layout concise
VIEWBY_OPTIONS: list[tuple[str, str]] = [
    ("Ministry", "MINISTRY"),
    ("Chapter", "CHAPTER"),
    ("Program", "PROGRAM"),
]

SPENDING_TYPE_OPTIONS: list[tuple[str, str]] = [
    ("All", "ALL"),
    ("Military Only", "MILITARY"),
]

UNIT_OPTIONS: list[tuple[str, str]] = [
    ("Billion RUB", "ABSOLUTE"),
    ("Dollars", "DOLLARS"),
    ("% full-year GDP", "PERCENT_GDP_FULL_YEAR"),
    ("% year-to-year GDP", "PERCENT_GDP_YEAR_TO_YEAR"),
    ("% full-year spending", "PERCENT_FULL_YEAR_SPENDING"),
    ("% year-to-year spending", "PERCENT_YEAR_TO_YEAR_SPENDING"),
    ("% year-to-year revenue", "PERCENT_YEAR_TO_YEAR_REVENUE"),
]


def generate_figure(
    labels: list[str],
    parents: list[str],
    values: list[float],
    metadata: list[str],
    spending_type: SpendingTypeLiteral = "ALL",
    language: LanguageTypeLiteral = "EN",
) -> go.Figure:
    """Build a treemap with stable ids and clean hover info."""
    # Compute percentage metrics for hover

    # Build figure
    fig = px.histogram()
    # Layout adjustments
    # Change font to Source Sans 3 and make it wrapped
    fig.update_layout(
        margin=dict(t=15, l=10, r=10, b=10),
        font=dict(family="Source Sans 3"),
    )

    # Populate hover with original values and percentages; include explicit node id
    fig.data[0].customdata = []
    fig.data[0].hovertemplate = "<b>%{label}</b><br><br>"

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
        dbc.DropdownMenuItem(
            html.Span(label, title=label),
            id={"type": "viewby-item", "value": value},
        )
        for label, value in VIEWBY_OPTIONS
    ]

    spending_type_items = [
        dbc.DropdownMenuItem(
            html.Span(label, title=label),
            id={"type": "spending-type-item", "value": value},
        )
        for label, value in SPENDING_TYPE_OPTIONS
    ]

    unit_items = [
        dbc.DropdownMenuItem(
            html.Span(label, title=label),
            id={"type": "unit-item", "value": value},
        )
        for label, value in UNIT_OPTIONS
    ]
    return html.Div(
        # Graph to display the timeseries
        [
            dcc.Store(id="store-selected-id"),
            dcc.Graph(
                id="timeseries-graph",
                config=TIMESERIES_CONFIG,
                style={"visibility": "hidden"},
            ),
        ],
        style={"width": "100%", "height": "90vh"},
    )


@callback(
    Output("timeseries-graph", "figure"),
    Output("timeseries-graph", "style"),
    Input("store-budget-id", "data"),
    Input("store-viewby", "data"),
    Input("store-spending-type", "data"),
    Input("store-unit", "data"),
)
def update_figure_from_filters(
    budget_id: int | None = None,
    viewby: ViewByDimensionTypeLiteral = "MINISTRY",
    spending_type: SpendingTypeLiteral = "ALL",
    unit: UnitLiteral = "ABSOLUTE",
) -> tuple[go.Figure, dict[str, str]]:
    # Fetch and render using the selected values from stores
    labels, parents, values, metadata = [], [], [], []
    return generate_figure(labels, parents, values, metadata, spending_type, language="EN"), {
        "visibility": "visible"
    }


@callback(
    Output("download-timeseries-data", "data"),
    Input("btn-download-csv", "n_clicks"),
    State("store-budget-id", "data"),
    State("store-viewby", "data"),
    State("store-spending-type", "data"),
    State("store-unit", "data"),
    prevent_initial_call=True,
    optional=True,
)
def download_timeseries_data(
    n_clicks,
    budget_id: int | None = None,
    viewby: ViewByDimensionTypeLiteral = "MINISTRY",
    spending_type: SpendingTypeLiteral = "ALL",
    unit: UnitLiteral = "ABSOLUTE",
) -> dict[str, Any]:
    """
    Callback to download the current treemap data as a csv file.
    Returns:
        dict[str, Any]: The data for download.
    """
    return dcc.send_data_frame(  # type: ignore
        pd.DataFrame([]).to_csv,
        "timeseries_data.csv",
        sep=";",
        index=False,
        encoding="utf-8",
    )


@callback(
    Output("download-timeseries-image", "data"),
    Input("btn-download-image", "n_clicks"),
    State("timeseries-graph", "figure"),
    prevent_initial_call=True,
    optional=True,
)
def download_timeseries_image(n_clicks: int | None, figure_json: dict) -> dict[str, Any] | None:
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
