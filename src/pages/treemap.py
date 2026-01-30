from datetime import date
from functools import lru_cache
import hashlib
import logging
from typing import Any, Optional, Sequence  # Use typing.Sequence for type annotations

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
from sqlalchemy import RowMapping

from utils.fetch import TreemapDataFetcher
from utils.transform import TreemapTransformer
from utils.calculate import Calculator
from utils.definitions import (
    LanguageTypeLiteral,
    UnitLiteral,
    unit_map,
    SpendingTypeLiteral,
    ViewByDimensionTypeLiteral,
    MilitarySpendingDictionary,
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


def _build_treemap_colors(
    df: pd.DataFrame,
    fig: go.Figure,
    spending_type: SpendingTypeLiteral,
    translated: bool,
) -> list[Optional[str]]:
    """Return marker colors for treemap nodes with ministry/root rules applied."""
    name_ending = "_NAME_TRANSLATED" if translated else "_NAME"
    ministry_col = f"MINISTRY{name_ending}"
    ministry_labels = (
        set(df[ministry_col].dropna().astype(str)) if ministry_col in df.columns else set()
    )
    root_label = str(df["ROOT"].iloc[0]) if "ROOT" in df.columns and not df.empty else "ROOT"
    labels = list(fig.data[0].labels)  # type: ignore
    parents = list(fig.data[0].parents)  # type: ignore

    # Use a deterministic palette so non-ministry tiles don't inherit gray.
    palette = (
        ["#7e8f5f", "#a3b18a", "#c7d0b8"]
        if spending_type == "MILITARY"
        else px.colors.qualitative.Set2
    )

    colors: list[Optional[str]] = []
    for label, parent in zip(labels, parents):
        # Root tile should be transparent unless MILITARY, then use the military color.
        if not parent and str(label) == root_label:
            colors.append("#7e8f5f" if spending_type == "MILITARY" else "rgba(0,0,0,0)")
        elif parent == root_label and str(label) in ministry_labels:
            colors.append("#dddddd")
        else:
            # Stable color assignment based on label.
            label_key = str(label)
            color_index = int(hashlib.md5(label_key.encode("utf-8")).hexdigest(), 16) % len(palette)
            colors.append(palette[color_index])

    return colors


def fetch_treemap_data(
    budget_id: int,
) -> tuple[Sequence[RowMapping], Sequence[RowMapping], date]:
    """Fetch and transform treemap data for the current filters."""
    data_fetcher = TreemapDataFetcher()
    published_at = data_fetcher.get_published_at_date(budget_id)
    dimensions, programs, _ = data_fetcher.fetch_data(
        budget_id=budget_id,
    )

    return dimensions, programs, published_at


@lru_cache(maxsize=5)
def transform_treemap_data(
    budget_id: int,
    spending_type: SpendingTypeLiteral,
    unit: UnitLiteral,
    character_limit: int = 25,
) -> pd.DataFrame:
    transformer = TreemapTransformer(max_line_lenght=character_limit)
    dimensions, programs, published_at = fetch_treemap_data(budget_id)
    df = transformer.transform_data(
        dimensions,
        programs,
        spending_type=spending_type,
    )
    # Calculate values based on unit, budget, and published_at
    calculator = Calculator(unit, budget_id, published_at)
    df["VALUE"] = df["VALUE"].apply(calculator.calculate)
    # Keep the base dataframe clean; percentages are computed from the treemap trace.

    return df


def shape_for_viewby(
    df: pd.DataFrame,
    viewby: ViewByDimensionTypeLiteral,
) -> pd.DataFrame:
    """Return the shape configuration for the given viewby dimension."""

    # create a copy to avoid modifying the original dataframe
    df_copy = df.copy()

    relevant_cols = []
    if viewby == "MINISTRY":
        # Remove Everything but Ministry, Chapter, lowest level and Value
        relevant_cols = [
            col for col in df_copy.columns if col.startswith(("MINISTRY", "CHAPTER", "PROGRAM_3"))
        ] + ["VALUE", "ROOT"]

    if viewby == "CHAPTER":
        # Remove Everything but Chapter, lowest level and Value
        relevant_cols = [
            col for col in df_copy.columns if col.startswith(("CHAPTER", "SUBCHAPTER", "PROGRAM_3"))
        ] + ["VALUE", "ROOT"]

    if viewby == "PROGRAM":
        # Remove Everything but lowest level and Value
        relevant_cols = [
            col
            for col in df_copy.columns
            if col.startswith(("PROGRAM_0", "PROGRAM_1", "PROGRAM_3"))
        ] + ["VALUE", "ROOT"]

    df_copy = df_copy[relevant_cols]

    return df_copy


def shape_for_spending_type(
    df: pd.DataFrame,
    spending_type: SpendingTypeLiteral,
) -> pd.DataFrame:
    """Return the shape configuration for the given spending type."""
    # For military spending, we might want to highlight certain ministries or chapters.
    # This function can be expanded in the future if needed.
    df_copy = df.copy()
    if spending_type == "MILITARY":
        # Filter the dataframe columns that begin the the keys in MilitarySpendingDictionary
        # and end in ORIG_ID. Keep only those rows that match the patterns in the dictionary.
        filter_conditions = []
        for key, pattern in MilitarySpendingDictionary.items():
            if key == "COMBINATION":
                for combo in pattern:  # type: ignore
                    condition = pd.Series([True] * len(df_copy))
                    for combo_key, combo_pattern in combo.items():
                        col_name = f"{combo_key}_ORIG_ID"
                        condition &= df_copy[col_name].astype(str).str.match(combo_pattern)
                    filter_conditions.append(condition)
            else:
                col_name = f"{key}_ORIG_ID"
                condition = df_copy[col_name].astype(str).str.match(pattern)  # type: ignore
                filter_conditions.append(condition)

        df_copy["ROOT"] = "Military Spending"

    return df_copy


def generate_figure(
    df: pd.DataFrame,
    spending_type: SpendingTypeLiteral = "ALL",
    unit: UnitLiteral = "ABSOLUTE",
    translated: bool = False,
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
        custom_data=["VALUE"],
    )
    # Layout adjustments
    # Change font to Source Sans 3 and make it wrapped
    fig.update_layout(
        margin=dict(t=15, l=10, r=10, b=10),
        font=dict(family="Source Sans 3"),
    )

    # Apply colors to all nodes.
    colors = _build_treemap_colors(df, fig, spending_type, translated)
    fig.update_traces(marker_colors=colors)

    # If spending type is military, adjust the color of the root tiles to #7e8f5f
    # and then get lighter shades of #7e8f5f for the children the deeper they are in the hierarchy
    if spending_type == "MILITARY":
        colorscale = [[1, "#7e8f5f"], [0.5, "#a3b18a"], [0, "#c7d0b8"]]
        fig.update_layout(
            treemapcolorway=["#7e8f5f"],
            coloraxis_colorscale=colorscale,
        )
    # Compute percentages for all nodes based on treemap aggregation.
    parents = list(fig.data[0].parents)  # type: ignore
    values = [float(v) if v is not None else 0.0 for v in fig.data[0].values]  # type: ignore
    parent_percentages, root_percentages = _compute_percentages(parents, values)
    # Safely read Plotly ids/labels (may be numpy arrays).
    raw_ids = fig.data[0].ids  # type: ignore
    node_ids = [str(node_id) for node_id in (list(raw_ids) if raw_ids is not None else [])]
    if not node_ids:
        raw_labels = fig.data[0].labels  # type: ignore
        node_ids = [str(label) for label in (list(raw_labels) if raw_labels is not None else [])]

    # Attach custom data for hover to every node, including id for click selection.
    fig.data[0].customdata = list(zip(values, parent_percentages, root_percentages, node_ids))

    fig.data[0].hovertemplate = "<br>".join(
        [
            "%{label}",
            "%{customdata[0]:.2f}" + unit_map[unit],
            "%{customdata[1]:.2f}%" + " of parent",
            "%{customdata[2]:.2f}%" + " of total",
        ]
    )
    fig.data[0].texttemplate = "%{label}<br>%{value:.2f}" + unit_map[unit]

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
    Input("store-unit", "data"),
    Input("store-language", "data"),
)
def update_figure_from_filters(
    budget_id: int,
    viewby: ViewByDimensionTypeLiteral = "MINISTRY",
    spending_type: SpendingTypeLiteral = "ALL",
    unit: UnitLiteral = "ABSOLUTE",
    language: str = "RU",
) -> tuple[go.Figure, dict[str, str]]:
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
    return generate_figure(df_shaped, spending_type, unit=unit, translated=translated), {
        "visibility": "visible"
    }


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


@callback(
    Output("download-treemap-image", "data"),
    Input("btn-download-image", "n_clicks"),
    State("treemap-graph", "figure", allow_optional=True),
    State("url", "pathname"),
    State("store-unit", "data"),
    State("store-budget-id", "data"),
    State("store-budget-options", "data"),
    State("store-spending-type", "data"),
    prevent_initial_call=True,
)
def download_treemap_image(
    n_clicks: int | None,
    figure_json: dict,
    pathname: str | None,
    unit: str | None,
    budget_id: int | None,
    budget_options: list[dict[str, Any]] | None,
    spending_type: str | None,
) -> dict[str, Any] | None:
    """
    Generate a PNG image from the current treemap figure and start a download.

    Notes:
    - Uses the already-rendered figure from the Graph (keeps current logic and avoids recomputation).
    - Requires 'kaleido' installed for Plotly static image export.
    - Only fires when on the treemap page (root /).
    """
    # Only run on treemap page (root)
    if pathname and pathname != "/":
        raise PreventUpdate

    # If there is no click or figure, do nothing
    if not n_clicks or not figure_json:
        return None

    # Reconstruct a Plotly Figure from the JSON stored in the Graph
    fig = go.Figure(figure_json)
    # Use font family with fallbacks - Kaleido needs system-installed fonts
    fig.update_layout(font=dict(family="Source Sans 3, Source Sans Pro, Arial, sans-serif"))

    current_year = pd.Timestamp.now().year
    # Add watermark/footer annotation in the lower right corner
    fig.add_annotation(
        text=f"Stiftung Wissenschaft und Politik (SWP), {current_year}| CC BY 4.0",
        xref="paper",
        yref="paper",
        x=1,
        y=0.01,
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

    filename = f"treemap_{now}_{budget_name}_{unit_label}{military_suffix}.png"

    # Send bytes to the browser as a downloadable file
    return dcc.send_bytes(image_bytes, filename)  # type: ignore
