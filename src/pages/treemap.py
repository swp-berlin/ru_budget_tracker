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

from utils.fetch import TremapDataFetcher
from utils.transform import TreemapTransformer
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
    # Sum over root nodes
    total_root_value = sum(v for v, p in zip(values, parents) if not p)
    # Root share per node
    root_percentages = [
        ((v / total_root_value) * 100) if total_root_value > 0 else 0.0 for v in values
    ]

    # Aggregate direct children per parent label
    parent_totals: dict[str, float] = {}
    for p, v in zip(parents, values):
        if p:
            parent_totals[p] = parent_totals.get(p, 0.0) + (v or 0.0)

    # Each node's share inside its parent
    parent_percentages: list[float] = []
    for p, v in zip(parents, values):
        if not p:
            parent_percentages.append(100.0)
            continue
        total = parent_totals.get(p, 0.0)
        parent_percentages.append(((v / total) * 100) if total > 0 else 0.0)

    return parent_percentages, root_percentages


def fetch_treemap_data(
    budget_id: int | None = None,
    spending_type: SpendingTypeLiteral = "ALL",
    unit: UnitLiteral = "ABSOLUTE",
    viewby: ViewByDimensionTypeLiteral = "MINISTRY",
    character_limit: int = 25,
) -> tuple[list[str], list[str], list[float], list[str], list[str]]:
    """Fetch and transform treemap data for the current filters."""
    data_fetcher = TremapDataFetcher()
    dimensions, programs, sum_mapping = data_fetcher.fetch_data(
        budget_id=budget_id,
        unit=unit,
    )
    transformer = TreemapTransformer()
    children, parents, values, metadata, names = transformer.transform_data(
        dimensions,
        programs,
        sum_mapping,
        translated_names=False,
        viewby=viewby,
        spending_type=spending_type,
    )
    calculator = Calculator(unit=unit)
    values = [calculator.calculate(v) if v is not None else 0.0 for v in values]
    # Add line breaks for better label rendering
    names = [add_breaks(lbl, interval=character_limit) for lbl in names]
    return children, parents, values, metadata, names


def generate_figure(
    children: list[str],
    parents: list[str],
    values: list[float],
    metadata: list[str],
    names: list[str],
    spending_type: SpendingTypeLiteral = "ALL",
    language: LanguageTypeLiteral = "EN",
) -> go.Figure:
    """Build a treemap with stable ids and clean hover info."""
    # Compute percentage metrics for hover
    parent_percentages, root_percentages = _compute_percentages(parents, values)

    # Use leaf-only sizing by setting branch values to 0
    parent_labels = set(parents)
    area_values = [0 if lbl in parent_labels else v for lbl, v in zip(children, values)]

    # Build figure
    fig = px.treemap(
        names=names,
        parents=parents,
        ids=children,
        values=area_values,
        hover_data=None,
    )
    # Layout adjustments
    # Change font to Source Sans 3 and make it wrapped
    fig.update_layout(
        margin=dict(t=15, l=10, r=10, b=10),
        font=dict(family="Source Sans 3"),
    )
    # If spending type is military, adjust the color of the root tiles to #7e8f5f
    # and then get lighter shades of #7e8f5f for the children the deeper they are in the hierarchy
    if spending_type == "MILITARY":
        colorscale = [[1, "#7e8f5f"], [0.5, "#a3b18a"], [0, "#c7d0b8"]]
        fig.update_layout(
            treemapcolorway=["#7e8f5f"],
            coloraxis_colorscale=colorscale,
        )

    # Populate hover with original values and percentages; include explicit node id
    fig.data[0].customdata = [
        [v, m, pp, rp]
        for v, m, pp, rp in zip(values, metadata, parent_percentages, root_percentages)
    ]
    fig.data[0].hovertemplate = (
        "<b>%{label}</b><br>"
        "ID: %{customdata[1]}<br>"
        "Value: %{customdata[0]:,.1f} Billion RUB<br>"
        "% Parent: %{customdata[2]:.2f}%<br>"
        "% Federal Budget: %{customdata[3]:.2f}%<br>"
        "<extra></extra>"
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

    return html.Div(
        # Graph to display the treemap
        [
            dcc.Store(id="store-selected-id"),
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
    Input("store-budget-id", "data"),
    Input("store-viewby", "data"),
    Input("store-spending-type", "data"),
    Input("store-unit", "data", allow_optional=True),
)
def update_figure_from_filters(
    budget_id: int | None = None,
    viewby: ViewByDimensionTypeLiteral = "MINISTRY",
    spending_type: SpendingTypeLiteral = "ALL",
    unit: UnitLiteral = "ABSOLUTE",
) -> tuple[go.Figure, dict[str, str]]:
    # Fetch and render using the selected values from stores
    children, parents, values, metadata, names = fetch_treemap_data(
        budget_id=budget_id,
        spending_type=spending_type,
        unit=unit,
        viewby=viewby,
    )
    return generate_figure(
        children, parents, values, metadata, names, spending_type, language="EN"
    ), {"visibility": "visible"}


@callback(
    Output("store-selected-id", "data"),
    Input("treemap-graph", "clickData"),
)
def update_selected_id(click_data: dict | None) -> Optional[str]:
    """Store the currently selected treemap node id from clickData.customdata[4]."""
    if not click_data:
        raise PreventUpdate
    try:
        pts = click_data.get("points", [])
        if not pts:
            raise PreventUpdate
        # customdata structure: [value, metadata, parent_pct, root_pct, node_id]
        custom = pts[0].get("customdata", [])
        node_id = custom[4] if len(custom) >= 5 else None
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
    budget_id: int | None,
    viewby: ViewByDimensionTypeLiteral,
    spending_type: SpendingTypeLiteral,
    unit: UnitLiteral,
) -> dict[str, Any]:
    """
    Callback to download the current treemap data as a csv file.
    Returns:
        dict[str, Any]: The data for download.
    """
    children, parents, values, metadata, names = fetch_treemap_data(
        budget_id=budget_id,
        spending_type=spending_type,
        unit=unit,
        viewby=viewby,
    )
    return dcc.send_data_frame(  # type: ignore
        pd.DataFrame(
            {
                "Name": names,
                "Id": children,
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
    optional=True,
)
def download_treemap_image(n_clicks: int | None, figure_json: dict) -> dict[str, Any] | None:
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
