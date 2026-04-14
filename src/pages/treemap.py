from datetime import date
from functools import lru_cache
import logging
from typing import Any, Optional, Sequence
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
from sqlalchemy import RowMapping

from utils.fetch import TreemapDataFetcher
from utils.transform import TreemapTransformer
from utils.calculate import Calculator
from utils.helper import create_treemap_colors, shape_for_spending_type, shape_for_viewby
from utils.definitions import (
    UnitLiteral,
    unit_map,
    SpendingTypeLiteral,
    ViewByDimensionTypeLiteral,
    BudgetTypeLiteral,
)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

register_page(__name__, path="/", title="Treemap View")

# Graph config kept simple and explicit for production clarity
TREEMAP_CONFIG = dcc.Graph.Config(
    displayModeBar=False,
    displaylogo=False,
    responsive=True,
)


def _compute_percentages(
    parents: list[str], values: list[float]
) -> tuple[list[float], list[float]]:
    """
    Compute (parent_percentages, root_percentages) for treemap hover info.
    - parent_percentages: share of a node within its parent's direct children.
    - root_percentages: share of a node relative to all roots combined.
    """
    # Sum over root nodes.
    total_root_value = sum(v for v, p in zip(values, parents) if not p)
    # Root share per node.
    root_percentages = [
        ((v / total_root_value) * 100) if total_root_value > 0 else 0.0 for v in values
    ]

    # Aggregate direct children per parent label.
    parent_totals: dict[str, float] = {}
    for p, v in zip(parents, values):
        if p:
            parent_totals[p] = parent_totals.get(p, 0.0) + (v or 0.0)

    # Each node's share inside its parent.
    parent_percentages: list[float] = []
    for p, v in zip(parents, values):
        if not p:
            parent_percentages.append(100.0)
            continue
        total = parent_totals.get(p, 0.0)
        parent_percentages.append(((v / total) * 100) if total > 0 else 0.0)

    return parent_percentages, root_percentages


@lru_cache(maxsize=5)
def fetch_treemap_data(
    budget_id: int,
) -> tuple[Sequence[RowMapping], Sequence[RowMapping], date]:
    """Fetch and transform treemap data for the current filters."""
    data_fetcher = TreemapDataFetcher()
    published_at = data_fetcher.get_published_at_date(budget_id)
    dimensions, programs = data_fetcher.fetch_data(
        budget_id=budget_id,
    )

    return dimensions, programs, published_at


@lru_cache(maxsize=5)
def transform_treemap_data(
    budget_id: int,
    spending_type: SpendingTypeLiteral,
    unit: UnitLiteral,
    character_limit: int = 50,
) -> pd.DataFrame:
    dimensions, programs, published_at = fetch_treemap_data(budget_id)
    budget_type: BudgetTypeLiteral = next(
        (row["budget_type"] for row in dimensions if row["budget_type"] in ["LAW", "REPORT"]), "LAW"
    )
    transformer = TreemapTransformer(dimensions, programs, max_line_lenght=character_limit)
    df = transformer.transform_data()
    # Calculate values based on unit, budget, and published_at
    calculator = Calculator(unit, budget_id, published_at, budget_type)
    df["VALUE"] = df["VALUE"].apply(calculator.calculate)
    return df


def generate_figure(
    df: pd.DataFrame,
    spending_type: SpendingTypeLiteral = "ALL",
    unit: UnitLiteral = "ABSOLUTE",
    translated: bool = False,
    viewby: ViewByDimensionTypeLiteral = "MINISTRY",
) -> go.Figure:
    """Build a treemap with stable ids and clean hover info."""
    # If translated, use translated names
    # ending = "NAME_TRANSLATED" if translated else "NAME"
    name_ending = "_NAME_TRANSLATED" if translated else "_NAME"
    name_cols = ["ROOT"] + [col for col in df.columns if col.endswith(name_ending)]

    # Build figure
    fig = px.treemap(
        data_frame=df,
        path=name_cols,
        values="VALUE",
        hover_data=None,
        custom_data=["BUDGET_TYPE"],
    )

    # Extract the necessary data from the treemap trace to compute percentages
    # and apply coloring rules.
    trace_data = fig.data[0]
    node_ids: list[str] = list(trace_data["ids"])
    parents: list[str] = list(trace_data["parents"])
    values: list[float] = [float(v) if v is not None else 0.0 for v in trace_data["values"]]
    budget_types: list[str] = [budget_type[0] for budget_type in trace_data["customdata"]]

    # Compute percentages for all nodes based on treemap aggregation.
    parent_percentages, root_percentages = _compute_percentages(parents, values)

    # Safely read Plotly ids/labels (may be numpy arrays).
    # Generate list of colors for each node based on classified status, node_id and spending type
    colors = create_treemap_colors(
        node_ids,
        budget_types,
        spending_type,
        viewby,
    )
    # Combine existing customdata with new percentage data and node ids for hover and click interactions.
    # Attach custom data for hover to every node, including id for click selection.
    fig.update_traces(
        marker_colors=colors,
        customdata=list(zip(values, parent_percentages, root_percentages, node_ids)),  # type: ignore
        hovertemplate="<br>".join(
            [
                "%{label}",
                "%{customdata[0]:,.1f}" + unit_map[unit],
                "%{customdata[1]:.1f}%" + " of parent",
                "%{customdata[2]:.1f}%" + " of total",
            ]
        ),
        texttemplate="%{label}<br>%{value:,.1f}" + unit_map[unit],
    )

    # Layout adjustments
    # Change font to Source Sans 3 and make it wrapped
    fig.update_layout(
        margin=dict(t=15, l=10, r=10, b=10),
        font=dict(family="Source Sans 3"),
        transition=dict(duration=300, easing="linear"),
    )

    return fig


def _build_treemap_node_map(df: pd.DataFrame, translated: bool) -> dict[str, dict[str, int | str]]:
    """Build a node-id map (Plotly treemap ids) to dimension metadata."""
    name_ending = "_NAME_TRANSLATED" if translated else "_NAME"
    name_cols = ["ROOT"] + [col for col in df.columns if col.endswith(name_ending)]
    node_map: dict[str, dict[str, int | str]] = {}

    for _, row in df.iterrows():
        labels: list[str] = []
        for col in name_cols:
            label = row.get(col)
            if not label:
                break
            labels.append(str(label))
            if col == "ROOT":
                continue
            base = col.replace(name_ending, "")
            dim_id = row.get(f"{base}_DIM_ID")
            dim_orig_id = row.get(f"{base}_ORIG_ID")
            dim_type = "PROGRAM" if base.startswith("PROGRAM_") else base
            path = "/".join(labels)
            # Skip null/NaN ids that can appear for root/placeholder nodes.
            if pd.notnull(dim_id) and pd.notnull(dim_orig_id):
                node_map[path] = {
                    "dimension_id": int(dim_id),
                    "dimension_original_identifier": str(dim_orig_id),
                    "dimension_type": str(dim_type),
                }

    return node_map


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

    return html.Div(
        # Graph to display the treemap
        [
            # Hidden timeseries graph keeps cross-page callbacks satisfied.
            dcc.Graph(id="timeseries-graph", style={"display": "none"}),
            dcc.Graph(
                id="treemap-graph",
                config=TREEMAP_CONFIG,
                style={"visibility": "hidden"},
            ),
        ],
        style={"width": "100%", "height": "90vh"},
    )


@callback(
    Output("treemap-graph", "figure"),
    Output("treemap-graph", "style"),
    Output("store-treemap-node-map", "data"),
    Input("url", "pathname"),
    Input("store-budget-id", "data"),
    Input("store-viewby", "data"),
    Input("store-spending-type", "data"),
    Input("store-unit", "data"),
    Input("store-language", "data"),
    prevent_initial_call=True,
)
def update_figure_from_filters(
    pathname: str | None,
    budget_id: int,
    viewby: ViewByDimensionTypeLiteral = "MINISTRY",
    spending_type: SpendingTypeLiteral = "ALL",
    unit: UnitLiteral = "ABSOLUTE",
    language: str = "RU",
) -> tuple[go.Figure, dict[str, str], dict[str, dict[str, int | str]]]:
    # Guard: only run when the treemap page is active.
    if pathname != "/":
        raise PreventUpdate
    # Guard: wait until a budget is selected
    if budget_id is None:
        raise PreventUpdate

    # Fetch and render using the selected values from stores
    # Use translated names when language is ENG (English)
    translated = language == "ENG"
    df = transform_treemap_data(
        budget_id=budget_id,
        spending_type=spending_type,
        unit=unit,
    )
    df_shaped = shape_for_spending_type(df, spending_type=spending_type)
    df_shaped = shape_for_viewby(df_shaped, viewby=viewby)
    # Build a lookup map for treemap node selection across pages.
    node_map = _build_treemap_node_map(df_shaped, translated=translated)
    return (
        generate_figure(df_shaped, spending_type, unit=unit, translated=translated, viewby=viewby),
        {"visibility": "visible"},
        node_map,
    )


@callback(
    Output("store-selected-id", "data"),
    Input("treemap-graph", "clickData"),
)
def update_selected_id(click_data: dict | None) -> Optional[str]:
    """Store the currently selected treemap node id from clickData.customdata[3]."""
    if not click_data:
        raise PreventUpdate
    try:
        pts = click_data.get("points", [])
        if not pts:
            raise PreventUpdate
        # Prefer explicit id provided by Plotly for treemap nodes.
        node_id = pts[0].get("id")
        if not node_id:
            # customdata structure: [value, parent_pct, root_pct, node_id]
            custom = pts[0].get("customdata", [])
            node_id = custom[3] if len(custom) >= 4 else None
        if not node_id:
            raise PreventUpdate
        return node_id
    except Exception:
        raise PreventUpdate


@callback(
    Output("download-treemap-data", "data"),
    Input("btn-download-csv", "n_clicks"),
    State("store-budget-id", "data"),
    State("store-viewby", "data"),
    State("store-spending-type", "data"),
    State("store-unit", "data"),
    prevent_initial_call=True,
    optional=True,
)
def download_treemap_data(
    n_clicks,
    budget_id: int,
    viewby: ViewByDimensionTypeLiteral,
    spending_type: SpendingTypeLiteral,
    unit: UnitLiteral,
) -> dict[str, Any]:
    """
    Callback to download the current treemap data as a csv file.
    Returns:
        dict[str, Any]: The data for download.
    """
    df = transform_treemap_data(
        budget_id=budget_id,
        spending_type=spending_type,
        unit=unit,
    )
    return dcc.send_data_frame(  # type: ignore
        df.to_csv,
        "treemap_data.csv",
        sep=";",
        index=False,
        encoding="utf-8",
    )
