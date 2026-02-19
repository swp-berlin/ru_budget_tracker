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
    BudgetTypeLiteral,
    LanguageTypeLiteral,
    UnitLiteral,
    SpendingTypeLiteral,
    UNIT_OPTIONS,
    PERIOD_OPTIONS,
    PeriodLiteral,
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


def _calculate_values(
    df: pd.DataFrame, budget_id: int, unit: UnitLiteral, budget_type: BudgetTypeLiteral
) -> pd.DataFrame:
    for index, row in df.iterrows():
        calculator = Calculator(
            budget_id=budget_id,
            unit=unit,
            date=row["dates"],
            budget_type=budget_type,
        )
        try:
            df.at[index, "expenses"] = calculator.calculate(row["expenses"])  # type: ignore
        except ValueError:
            # drop rows with calculation errors (e.g., missing data for the date/unit)
            df = df.drop(index)

    return df


def _shape_for_period(df: pd.DataFrame, period: PeriodLiteral) -> pd.DataFrame:
    if period == "ALL":
        return df
    elif period == "Q1":
        filtered_df = df.loc[df["dates"].dt.month == 3]
        return filtered_df
    elif period == "Q2":
        filtered_df = df.loc[df["dates"].dt.month == 6]
        return filtered_df
    elif period == "Q3":
        filtered_df = df.loc[df["dates"].dt.month == 9]
        return filtered_df
    elif period == "Q4":
        filtered_df = df.loc[df["dates"].dt.month == 12]
        return filtered_df
    else:
        raise ValueError(f"Invalid period: {period}")


def _resolve_selected_dimension(
    selected_node_id: str | None,
    node_map: dict[str, dict[str, int | str]] | None,
) -> dict[str, int | str] | None:
    """Resolve a selected treemap node id into dimension metadata."""
    if not selected_node_id or not node_map:
        return None
    return node_map.get(selected_node_id)


def fetch_timeseries_data(
    budget_id: int,
    spending_type: SpendingTypeLiteral = "ALL",
    unit: UnitLiteral = "ABSOLUTE",
    period: PeriodLiteral = "ALL",
    selected_dimension: dict[str, int | str] | None = None,
) -> tuple[pd.DataFrame, str]:
    """Fetch and transform treemap data for the current filters."""
    data_fetcher = BarChartDataFetcher(spending_type)
    dimension_id = None
    if selected_dimension is not None:
        dimension_id_value = selected_dimension.get("dimension_id")
        dimension_orig_id = selected_dimension.get("dimension_original_identifier", "")
        # Skip synthetic classified nodes that do not map to real dimensions.
        if isinstance(dimension_id_value, int) and "CLASSIFIED" not in str(dimension_orig_id):
            dimension_id = dimension_id_value

    budgets, type = data_fetcher.fetch_data(
        budget_id=budget_id,
        dimension_id=dimension_id,
    )
    transformer = BarchartTransformer()
    if unit in [
        "PERCENT_YEAR_TO_DATE_SPENDING",
        "PERCENT_YEAR_TO_DATE_REVENUE",
    ]:
        df = transformer.transform_data(budgets, normalize=True)
    else:
        df = transformer.transform_data(budgets, normalize=False)
    # Use apply to calculate expenses for each row in a vectorized way
    budget_type: BudgetTypeLiteral = next(
        (row["type"] for row in budgets if row["type"] in ["LAW", "REPORT"]), "LAW"
    )
    # Period filtering only applies to REPORT budgets; LAW uses full-year values.
    if budget_type == "REPORT":
        df = _shape_for_period(df, period)
    df = _calculate_values(df, budget_id, unit, budget_type)
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
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=-0.20,
            xanchor="center",
            x=0.5,
            maxheight=0.1,  # Comment maxheight to see legend take up 0.5 of plotting area
            title_text="",
        ),
        yaxis_title=f"{unit_label}",
        xaxis_title="",  # Format x-axis to show quarter labels (e.g., "2018-Q1")
        uirevision=f"unit:{unit}",
    )
    # Set x-axis tick labels to show quarters if budget_type is REPORT
    if "REPORT" in df["types"].values:
        # Constrain ticks to visible data to avoid extra quarters.
        tick_values = df["dates"].dropna().sort_values().unique().tolist()
        fig.update_layout(
            xaxis=dict(
                tickformat="%Y-Q%q",  # Plotly quarter format: year-quarter
                tickangle=-45,  # Angle text to prevent overlap
                tickmode="array",
                tickvals=tick_values,
                tick0=df["dates"].min()
                if not df.empty
                else None,  # Anchor ticks to first data point
            ),  # Force a full redraw when unit changes so the chart reloads reliably
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

    period_items = [
        dbc.DropdownMenuItem(
            html.Span(label, title=label),
            id={"type": "period-item", "value": value},
        )
        for label, value in PERIOD_OPTIONS
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
            # Hidden treemap graph keeps cross-page callbacks satisfied.
            dcc.Graph(id="treemap-graph", style={"display": "none"}),
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
    Input("url", "pathname"),
    Input("store-budget-id", "data"),
    Input("store-period", "data"),
    Input("store-spending-type", "data"),
    Input("store-unit", "data"),
    State("store-selected-id", "data"),
    State("store-treemap-node-map", "data"),
)
def update_figure_from_filters(
    pathname: str | None,
    budget_id: int,
    period: PeriodLiteral = "ALL",
    spending_type: SpendingTypeLiteral = "ALL",
    unit: UnitLiteral = "ABSOLUTE",
    selected_node_id: str | None = None,
    node_map: dict[str, dict[str, int | str]] | None = None,
) -> tuple[go.Figure, dict[str, str]]:
    # Guard: only render on the timeseries page to keep hidden graphs hidden.
    if pathname != "/timeseries":
        return go.Figure(), {"display": "none"}
    # Guard: wait until a budget is selected
    if budget_id is None:
        raise PreventUpdate

    # Fetch and render using the selected values from stores
    selected_dimension = _resolve_selected_dimension(selected_node_id, node_map)
    df, _ = fetch_timeseries_data(
        budget_id=budget_id,
        spending_type=spending_type,
        unit=unit,
        period=period,
        selected_dimension=selected_dimension,
    )
    return generate_figure(df, [], unit, spending_type, language="EN"), {"visibility": "visible"}


@callback(
    Output("download-timeseries-data", "data"),
    Input("btn-download-csv", "n_clicks"),
    State("store-budget-id", "data"),
    State("store-period", "data"),
    State("store-spending-type", "data"),
    State("store-unit", "data"),
    prevent_initial_call=True,
    optional=True,
)
def download_timeseries_data(
    n_clicks,
    budget_id: int | None = None,
    period: PeriodLiteral = "ALL",
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
