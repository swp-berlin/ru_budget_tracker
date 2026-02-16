import logging
from typing import Any

import dash_bootstrap_components as dbc
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dash import (
    Input,
    Output,
    State,
    callback,
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
    budget_id: int,
    spending_type: SpendingTypeLiteral = "ALL",
    unit: UnitLiteral = "ABSOLUTE",
) -> tuple[pd.DataFrame, str]:
    """Fetch and transform treemap data for the current filters."""
    data_fetcher = BarChartDataFetcher(spending_type)
    published_at = data_fetcher.get_published_at_date(budget_id=budget_id)
    budgets, type = data_fetcher.fetch_data(
        budget_id=budget_id,
    )
    transformer = BarchartTransformer()
    df = transformer.transform_data(budgets)
    # Use apply to calculate expenses for each row in a vectorized way
    for index, row in df.iterrows():
        calculator = Calculator(
            budget_id=budget_id,
            unit=unit,
            date=row["dates"],
        )
        df.at[index, "expenses"] = calculator.calculate(row["expenses"])  # type: ignore
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
        # Force a full redraw when unit changes so the chart reloads reliably.
        uirevision=f"unit:{unit}",
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
    budget_id: int,
    viewby: ViewByDimensionTypeLiteral = "MINISTRY",
    spending_type: SpendingTypeLiteral = "ALL",
    unit: UnitLiteral = "ABSOLUTE",
) -> tuple[go.Figure, dict[str, str]]:
    # Fetch and render using the selected values from stores
    df, _ = fetch_timeseries_data(
        budget_id=budget_id,
        spending_type=spending_type,
        unit=unit,
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
