import io
import logging
from typing import Any, cast
from datetime import date, datetime

import dash_bootstrap_components as dbc
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dash import (
    ClientsideFunction,
    Input,
    Output,
    State,
    callback,
    clientside_callback,
    dcc,
    html,
    register_page,
    get_relative_path,
)
from dash.exceptions import PreventUpdate

from utils.fetch_timeseries import TimeseriesDataFetcher
from utils.helper import get_unit_label
from utils.transform_timeseries import TimeseriesTransformer
from utils.calculate import Calculator
from utils.definitions import (
    BudgetTypeLiteral,
    LanguageTypeLiteral,
    UnitLiteral,
    SpendingTypeLiteral,
    unit_config,
    period_config,
    spending_type_config,
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
    # Cache one Calculator per unique date (was one per row) and collect drops to apply at the end.
    _calculator_cache: dict[date, Calculator] = {}
    rows_to_drop: list = []

    for index, row in df.iterrows():
        try:
            budget_date = row["dates"].date()
        except (AttributeError, ValueError):
            # NaT or unparseable dates — drop the row (matches original behaviour).
            rows_to_drop.append(index)
            continue

        if budget_date not in _calculator_cache:
            _calculator_cache[budget_date] = Calculator(
                budget_id=budget_id, unit=unit, date=budget_date, budget_type=budget_type
            )
        try:
            df.at[index, "expenses"] = _calculator_cache[budget_date].calculate(row["expenses"])
        except ValueError:
            rows_to_drop.append(index)

    if rows_to_drop:
        df = df.drop(rows_to_drop)
    return df


_PERIOD_MONTH = {"Q1": 3, "Q2": 6, "Q3": 9, "Q4": 12}


def _shape_for_period(df: pd.DataFrame, period: PeriodLiteral) -> pd.DataFrame:
    if period == "ALL":
        return df
    month = _PERIOD_MONTH.get(period)
    if month is None:
        raise ValueError(f"Invalid period: {period}")
    return df.loc[df["dates"].dt.month == month]


def fetch_timeseries_data(
    budget_id: int,
    spending_type: SpendingTypeLiteral = "ALL",
    unit: UnitLiteral = "ABSOLUTE",
    period: PeriodLiteral = "ALL",
    selected_dimension: dict[str, int | str] | None = None,
    classified_only: bool = False,
) -> tuple[pd.DataFrame, str, BudgetTypeLiteral]:
    """Fetch and transform treemap data for the current filters."""
    data_fetcher = TimeseriesDataFetcher(spending_type)
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
    transformer = TimeseriesTransformer()
    if unit in [
        "PERCENT_YEAR_TO_DATE_SPENDING",
        "PERCENT_YEAR_TO_DATE_REVENUE",
    ]:
        df = transformer.transform_data(budgets, normalize=True, spending_type=spending_type)
    else:
        df = transformer.transform_data(budgets, normalize=False, spending_type=spending_type)
    # Use apply to calculate expenses for each row in a vectorized way
    budget_type: BudgetTypeLiteral = next(
        (row["type"] for row in budgets if row["type"] in ["LAW", "REPORT"]), "LAW"
    )
    # Period filtering only applies to REPORT budgets; LAW uses full-year values.
    if budget_type == "REPORT":
        df = _shape_for_period(df, period)
    df = _calculate_values(df, budget_id, unit, budget_type)
    df["expenses"] = df["expenses"].clip(lower=0)
    # Rename LAW and REPORT to OPEN for clearer legend labeling in the timeseries view.
    df["types"] = df["types"].where(df["types"] == "CLASSIFIED", "OPEN")
    if classified_only:
        df = df.loc[df["types"] == "CLASSIFIED"]
    return df, type, budget_type


def generate_figure(
    df: pd.DataFrame,
    metadata: list[str] = [],
    unit: UnitLiteral = "ABSOLUTE",
    spending_type: SpendingTypeLiteral = "ALL",
    language: LanguageTypeLiteral = "EN",
    title: str | None = None,
    budget_type: BudgetTypeLiteral = "LAW",
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
            "OPEN": "#1f77b4",
            "CLASSIFIED": "#cccccc",
        },
        template="none",
    )
    # Get unit label
    unit_label = unit_labels.get(unit, "billion RUB (nominal)")

    # Layout adjustments
    # Change font to Source Sans 3 and make it wrapped
    fig.update_layout(
        margin=dict(t=50, l=80, r=30, b=10, autoexpand=True),
        font=dict(family="Source Sans 3"),
        title=title,  # Ensure the title reflects treemap selections and filters.
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=-0.15,
            xanchor="center",
            x=0.5,
            maxheight=0.1,  # Comment maxheight to see legend take up 0.5 of plotting area
            title_text="",
        ),
        yaxis_title=f"{unit_label}",
        xaxis_title="",  # Format x-axis to show quarter labels (e.g., "2018-Q1")
        uirevision=f"unit:{unit}",
    )
    # Set x-axis tick labels and hover format based on budget type
    if budget_type == "REPORT":
        # Constrain ticks to visible data to avoid extra quarters.
        tick_values = df["dates"].dropna().sort_values().unique().tolist()
        fig.update_layout(
            xaxis=dict(
                tickformat="%Y-Q%q",  # Plotly quarter format: year-quarter
                tickangle=-45,  # Angle text to prevent overlap
                tickmode="array",
                tickvals=tick_values,
                tick0=df["dates"].min() if not df.empty else None,
                hoverformat="%Y-Q%q",
            ),  # Force a full redraw when unit changes so the chart reloads reliably
        )
    else:
        fig.update_layout(
            xaxis=dict(hoverformat="%Y", tickangle=-45),
        )

    # Set custom hover templates per trace, matched by name for robustness.
    classified_label = "CLASSIFIED (EST.)" if spending_type == "MILITARY" else "CLASSIFIED"
    for trace in fig.data:
        bar = cast(go.Bar, trace)
        n = len(bar.x) if bar.x is not None else 0  # type: ignore
        bar.customdata = [[unit_label]] * n
        if bar.name == "OPEN":
            bar.hovertemplate = (
                "<b>%{x}</b><br>Value: %{y:,.1f} %{customdata[0]}<br><extra></extra>"
            )
        elif bar.name == "CLASSIFIED":
            bar.hovertemplate = (
                "<b>%{x}</b><br>Value: %{y:,.1f} %{customdata[0]} (CLASSIFIED)<br><extra></extra>"
            )
            bar.name = classified_label

    return fig


def _format_timeseries_title(
    selected_node_id: str | None,
    spending_type: SpendingTypeLiteral,
) -> str:
    max_length = 60
    # Use the last path segment as the node label to keep titles readable.
    if selected_node_id:
        node_label = selected_node_id.split("/")[-1]
        # Strip the leading original identifier prefix like "123 - " for cleaner titles.
        if " - " in node_label:
            node_label = node_label.split(" - ", 1)[1]
        if "<br>" in node_label:
            node_label = node_label.replace("<br>", " ")
        title = f"Russian Budget: {node_label}"
    else:
        title = "Russian Budget Spending"

    # Append a military suffix when that filter is active.
    if spending_type == "MILITARY":
        title = f"{title} (military)"

    # Truncate long titles with an ellipsis suffix for visual consistency.
    if len(title) > max_length:
        title = f"{title[:max_length]}..."

    return title


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
        for label, value in period_config.options
    ]

    spending_type_items = [
        dbc.DropdownMenuItem(
            html.Span(label, title=label),
            id={"type": "spending-type-item", "value": value},
        )
        for label, value in spending_type_config.options
    ]

    unit_items = [
        dbc.DropdownMenuItem(
            html.Span(label, title=label),
            id={"type": "unit-item", "value": value},
        )
        for label, value in unit_config.options
    ]
    return html.Div(
        # Graph to display the timeseries
        [
            # Hidden treemap graph keeps cross-page callbacks satisfied.
            dcc.Graph(
                id="treemap-graph", style={"display": "none", "height": "100%", "width": "100%"}
            ),
            # Loading spinner overlay, hidden once the graph is ready.
            html.Div(
                html.Div(className="treemap-spinner"),
                id="timeseries-spinner",
                style={
                    "position": "absolute",
                    "top": "50%",
                    "left": "50%",
                    "transform": "translate(-50%, -50%)",
                    "zIndex": 10,
                },
            ),
            dcc.Graph(
                id="timeseries-graph",
                config=TIMESERIES_CONFIG,
                style={"visibility": "hidden", "height": "100%", "width": "100%"},
            ),
        ],
        style={"width": "100%", "height": "90vh", "position": "relative"},
    )


@callback(
    Output("timeseries-graph", "figure"),
    Output("timeseries-graph", "style"),
    Output("store-timeseries-ticks", "data"),
    Input("url", "pathname"),
    Input("store-budget-id", "data"),
    Input("store-period", "data"),
    Input("store-spending-type", "data"),
    Input("store-unit", "data"),
    Input("store-selected-id", "data"),
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
) -> tuple[go.Figure, dict[str, str], dict | None]:
    # Guard: only render on the timeseries page to keep hidden graphs hidden.
    if pathname != get_relative_path("/timeseries"):
        return go.Figure(), {"display": "none"}, None
    # Guard: wait until a budget is selected
    if budget_id is None:
        raise PreventUpdate

    # Fetch and render using the selected values from stores
    selected_dimension = node_map.get(selected_node_id) if selected_node_id and node_map else None
    classified_only = False
    if selected_dimension and "CLASSIFIED" in str(
        selected_dimension.get("dimension_original_identifier", "")
    ):
        classified_only = True
        # Use the parent chapter's dimension for the API filter.
        parent_path = "/".join(selected_node_id.split("/")[:-1]) if selected_node_id else None
        selected_dimension = node_map.get(parent_path) if parent_path and node_map else None
    df, _, budget_type = fetch_timeseries_data(
        budget_id=budget_id,
        spending_type=spending_type,
        unit=unit,
        period=period,
        selected_dimension=selected_dimension,
        classified_only=classified_only,
    )
    # Build a title based on the treemap selection and spending-type filter.
    title = _format_timeseries_title(selected_node_id, spending_type)

    # Provide tick metadata for the clientside responsive-tick callback.
    # Only needed for REPORT budgets shown with all periods (many quarterly ticks).
    tick_info: dict | None = None
    if budget_type == "REPORT" and period == "ALL":
        tick_values = df["dates"].dropna().sort_values().unique().tolist()
        tick_info = {"tickvals": [t.isoformat() for t in tick_values]}

    return (
        generate_figure(
            df, [], unit, spending_type, language="EN", title=title, budget_type=budget_type
        ),
        {"visibility": "visible"},
        tick_info,
    )


@callback(
    Output("download-timeseries-data", "data"),
    Input("btn-download-csv", "n_clicks"),
    State("url", "pathname"),
    State("store-budget-id", "data"),
    State("store-budget-options", "data"),
    State("store-period", "data"),
    State("store-spending-type", "data"),
    State("store-unit", "data"),
    State("store-selected-id", "data"),
    State("store-treemap-node-map", "data"),
    prevent_initial_call=True,
    optional=True,
)
def download_timeseries_data(
    n_clicks,
    pathname: str | None,
    budget_id: int | None = None,
    budget_options: list[dict] | None = None,
    period: PeriodLiteral = "ALL",
    spending_type: SpendingTypeLiteral = "ALL",
    unit: UnitLiteral = "ABSOLUTE",
    selected_node_id: str | None = None,
    node_map: dict[str, dict[str, int | str]] | None = None,
) -> dict[str, Any]:
    """
    Callback to download the current timeseries data as a csv file.
    Returns:
        dict[str, Any]: The data for download.
    """
    if pathname != get_relative_path("/timeseries"):
        raise PreventUpdate
    if budget_id is None:
        raise PreventUpdate
    selected_dimension = node_map.get(selected_node_id) if selected_node_id and node_map else None
    classified_only = False
    if selected_dimension and "CLASSIFIED" in str(
        selected_dimension.get("dimension_original_identifier", "")
    ):
        classified_only = True
        parent_path = "/".join(selected_node_id.split("/")[:-1]) if selected_node_id else None
        selected_dimension = node_map.get(parent_path) if parent_path and node_map else None
    df, _, budget_type = fetch_timeseries_data(
        budget_id=budget_id,
        spending_type=spending_type,
        unit=unit,
        period=period,
        selected_dimension=selected_dimension,
        classified_only=classified_only,
    )

    value_col = get_unit_label(unit)

    def _format_period(dt: pd.Timestamp) -> str:
        if budget_type == "REPORT":
            quarter = dt.month // 3
            return f"{dt.year}-Q{quarter}"
        return str(dt.year)

    download_df = df[["dates", "expenses", "types"]].copy()
    download_df["Period"] = download_df["dates"].apply(_format_period)
    if classified_only:
        pivoted = (
            download_df.groupby("Period")["expenses"]
            .sum()
            .round(2)
            .reset_index()
            .rename(columns={"expenses": f"Classified ({value_col})"})
        )
    else:
        pivoted = (
            download_df.groupby(["Period", "types"])["expenses"]
            .sum()
            .round(2)
            .unstack(fill_value=0)
            .reindex(columns=["OPEN", "CLASSIFIED"], fill_value=0)
            .reset_index()
            .rename(
                columns={"OPEN": f"Open ({value_col})", "CLASSIFIED": f"Classified ({value_col})"}
            ),
        )[0]
        pivoted[f"Total ({value_col})"] = (
            pivoted[f"Open ({value_col})"] + pivoted[f"Classified ({value_col})"]
        ).round(2)

    budget_label = next(
        (o["label"] for o in (budget_options or []) if o["value"] == budget_id), str(budget_id)
    )
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    sanitized = budget_label.replace(" ", "_").replace("/", "-")
    military = "_military" if spending_type == "MILITARY" else ""
    filename = f"timeseries_{timestamp}_{sanitized}_{unit.lower()}{military}.csv"
    buf = io.BytesIO()
    pivoted.to_csv(buf, sep=";", index=False, encoding="utf-8-sig")
    return dcc.send_bytes(buf.getvalue(), filename)  # type: ignore


# Poll window width via a lightweight interval so resize events reach Dash.
clientside_callback(
    "function(n) { return window.innerWidth; }",
    Output("store-window-width", "data"),
    Input("timeseries-resize-interval", "n_intervals"),
)

# Adjust quarterly tick labels when the viewport crosses the 640 px stacking threshold.
# Only active for REPORT budgets with all periods selected (many quarterly ticks).
clientside_callback(
    ClientsideFunction(namespace="clientside", function_name="adjustTimeseriesTicks"),
    Output("timeseries-graph", "figure", allow_duplicate=True),
    Input("store-window-width", "data"),
    Input("store-timeseries-ticks", "data"),
    State("timeseries-graph", "figure"),
    prevent_initial_call=True,
)
