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

from utils.fetch import BarChartDataFetcher
from utils.transform import BarchartTransformer
from utils.calculate import Calculator
from utils.definitions import (
    LanguageTypeLiteral,
    UnitLiteral,
    SpendingTypeLiteral,
    ViewByDimensionTypeLiteral,
    UNIT_OPTIONS,
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

unit_labels = {
    "ABSOLUTE": "billion RUB (nominal)",
    "DOLLARS": "billion PPP dollar (OECD)",
    "PERCENT_GDP_FULL_YEAR": "% of full-year GDP",
    "PERCENT_GDP_YEAR_TO_DATE": "% of GDP (year-to-date)",
    "PERCENT_FULL_YEAR_SPENDING": "% of full-year spending",
    "PERCENT_YEAR_TO_DATE_SPENDING": "% of spending (year-to-date)",
    "PERCENT_YEAR_TO_DATE_REVENUE": "% year-to-date revenue",
}


def fetch_timeseries_data(
    budget_id: int | None = None,
    spending_type: SpendingTypeLiteral = "ALL",
    unit: UnitLiteral = "ABSOLUTE",
    viewby: ViewByDimensionTypeLiteral = "MINISTRY",
    character_limit: int = 25,
) -> tuple[pd.DataFrame, str]:
    """Fetch and transform treemap data for the current filters."""
    data_fetcher = BarChartDataFetcher()
    budgets, type = data_fetcher.fetch_data(
        budget_id=budget_id,
    )
    transformer = BarchartTransformer()
    df = transformer.transform_data(budgets=budgets)
    calculator = Calculator(unit=unit)
    df["expenses"] = [calculator.calculate(v) if v is not None else 0.0 for v in df["expenses"]]
    # Add line breaks for better label rendering
    return df, type


def generate_figure(
    df: pd.DataFrame,
    metadata: list[str] = [],
    unit: UnitLiteral = "ABSOLUTE",
    spending_type: SpendingTypeLiteral = "ALL",
    language: LanguageTypeLiteral = "EN",
) -> go.Figure:
    """Build a treemap with stable ids and clean hover info."""
    # Build figure
    fig = px.bar(
        df,
        x="dates",
        y="expenses",
        color="types",
        barmode="stack",
        color_discrete_map={
            "REPORT": "#1f77b4",
            "LAW": "#1f77b4",
            "CLASSIFIED": "#cccccc",
        },
        template="none",
    )
    # Get unit label
    unit_label = unit_labels.get(unit, "billion RUB (nominal)")

    # Layout adjustments
    # Change font to Source Sans 3 and make it wrapped
    fig.update_layout(
        margin=dict(t=15, l=60, r=30, b=50),
        font=dict(family="Source Sans 3"),
        showlegend=False,
        yaxis_title=f"{unit_label}",
        xaxis_title="",
    )

    # Set custom hover templates for each trace
    # First trace is regular budget data (LAW or REPORT)
    if len(fig.data) > 0:  # type: ignore
        fig.data[0].customdata = [[unit_label] for _ in df["dates"]]
        fig.data[
            0
        ].hovertemplate = "<b>%{x}</b><br>Value: %{y:,.1f} %{customdata[0]}<br><extra></extra>"

    # Second trace is classified spending (only present when TOTAL budget exists)
    if len(fig.data) > 1:  # type: ignore
        fig.data[1].customdata = [[unit_label] for _ in df["dates"]]
        fig.data[
            1
        ].hovertemplate = (
            "<b>%{x}</b><br>Value: %{y:,.1f} %{customdata[0]} (classified)<br><extra></extra>"
        )

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
    df, type = fetch_timeseries_data(
        budget_id=budget_id,
        spending_type=spending_type,
        unit=unit,
        viewby=viewby,
    )
    return generate_figure(df, [], unit, spending_type, language="EN"), {"visibility": "visible"}


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
    State("timeseries-graph", "figure", allow_optional=True),
    State("url", "pathname"),
    State("store-unit", "data"),
    State("store-budget-id", "data"),
    State("store-budget-options", "data"),
    State("store-spending-type", "data"),
    prevent_initial_call=True,
)
def download_timeseries_image(
    n_clicks: int | None,
    figure_json: dict,
    pathname: str | None,
    unit: str | None,
    budget_id: int | None,
    budget_options: list[dict[str, Any]] | None,
    spending_type: str | None,
) -> dict[str, Any] | None:
    """
    Generate a PNG image from the current timeseries figure and start a download.

    Notes:
    - Uses the already-rendered figure from the Graph (keeps current logic and avoids recomputation).
    - Requires 'kaleido' installed for Plotly static image export.
    - Only fires when on the timeseries page.
    """
    # Only run on timeseries page
    if not pathname or pathname != "/timeseries":
        raise PreventUpdate

    # If there is no click or figure, do nothing
    if not n_clicks or not figure_json:
        return None

    # Reconstruct a Plotly Figure from the JSON stored in the Graph
    fig = go.Figure(figure_json)

    # Rename legend labels for the screenshot
    legend_name_map = {"LAW": "budget", "REPORT": "execution"}
    for trace in fig.data:
        if trace.name in legend_name_map:  # type: ignore
            trace.name = legend_name_map[trace.name]  # type: ignore

    fig.update_layout(
        margin=dict(t=15, l=60, r=30, b=50),
        # Use font family with fallbacks - Kaleido needs system-installed fonts
        font=dict(family="Source Sans 3, Source Sans Pro, Arial, sans-serif"),
        showlegend=True,
        legend=dict(
            title="Budget Type",
            yanchor="top",
            y=0.99,
            xanchor="left",
            x=0.02,
        ),
        yaxis_title=f"{unit_labels.get(unit or 'billion RUB (nominal)')}",
        xaxis_title="",
    )

    # Add watermark/footer annotation in the lower right corner
    fig.add_annotation(
        text="Stiftung Wissenschaft und Politik (SWP) | CC BY 4.0",
        xref="paper",
        yref="paper",
        x=1,
        y=-0.08,
        xanchor="right",
        yanchor="top",
        showarrow=False,
        font=dict(
            family="Source Sans 3, Source Sans Pro, Arial, sans-serif",
            size=10,
            color="black",
        ),
    )

    # Convert the figure to PNG bytes (kaleido backend)
    image_bytes = fig.to_image(format="png", scale=3.0)  # Ensure 'kaleido' is in your dependencies

    # Build filename with budget name, unit, and military filter
    now = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")

    # Get budget name from options
    budget_name = "unknown"
    if budget_options and budget_id is not None:
        for opt in budget_options:
            if opt.get("value") == budget_id:
                budget_name = opt.get("label", "unknown")
                break
    # Sanitize budget name for filename (replace spaces and special chars)
    budget_name = budget_name.replace(" ", "_").replace("/", "-")

    # Get unit label (short version)
    unit_label = (unit or "ABSOLUTE").lower()

    # Add military filter suffix if active
    military_suffix = "_military" if spending_type == "MILITARY" else ""

    filename = f"{now}_{budget_name}_{unit_label}{military_suffix}.png"

    # Send bytes to the browser as a downloadable file
    return dcc.send_bytes(image_bytes, filename)  # type: ignore
