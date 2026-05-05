from datetime import date, datetime
from functools import lru_cache
import io
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
    no_update,
    register_page,
    get_relative_path,
)
from dash.exceptions import PreventUpdate
from sqlalchemy import RowMapping

from utils.fetch_treemap import ClassifiedSpendingData, TreemapDataFetcher, fetch_treemap_hierarchy
from utils.transform_treemap import TreemapTransformer
from utils.calculate import Calculator
from utils.helper import (
    create_treemap_colors,
    get_unit_label,
    shape_for_spending_type,
    shape_for_viewby,
)
from utils.definitions import (
    UnitLiteral,
    unit_config,
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
) -> tuple[Sequence[RowMapping], Sequence[RowMapping], ClassifiedSpendingData, date]:
    """Fetch and transform treemap data for the current filters."""
    data_fetcher = TreemapDataFetcher()
    budget_type, published_at = data_fetcher.get_budget_meta(budget_id)
    dimensions, programs, classified = data_fetcher.fetch_data(
        budget_id=budget_id,
        budget_type=budget_type,
        published_at=published_at,
    )

    return dimensions, programs, classified, published_at


@lru_cache(maxsize=5)
def transform_treemap_data(
    budget_id: int,
    spending_type: SpendingTypeLiteral,
    unit: UnitLiteral,
) -> pd.DataFrame:
    dimensions, programs, classified, published_at = fetch_treemap_data(budget_id)
    budget_type: BudgetTypeLiteral = next(
        (row["budget_type"] for row in dimensions if row["budget_type"] in ["LAW", "REPORT"]), "LAW"
    )
    transformer = TreemapTransformer(
        dimensions, programs, classified, spending_type=spending_type, char_limit=45
    )
    flat_rows = fetch_treemap_hierarchy(budget_id)
    if flat_rows:
        df = transformer.transform_from_flat(flat_rows)
    else:
        df = transformer.transform_data()
    calculator = Calculator(unit, budget_id, published_at, budget_type)
    df["VALUE"] = calculator.calculate_series(df["VALUE"]).clip(lower=0)
    return df


def generate_figure(
    df: pd.DataFrame,
    spending_type: SpendingTypeLiteral = "ALL",
    unit: UnitLiteral = "ABSOLUTE",
    translated: bool = False,
    viewby: ViewByDimensionTypeLiteral = "MINISTRY",
) -> tuple[go.Figure, dict[str, str]]:
    """Build a treemap with stable ids and clean hover info."""
    # If translated, use translated names
    # ending = "NAME_TRANSLATED" if translated else "NAME"
    name_ending = "_NAME_TRANSLATED" if translated else "_NAME"
    name_cols = ["ROOT"] + [col for col in df.columns if col.endswith(name_ending)]

    # Strip columns not used in the figure to keep the serialized trace lean.
    keep_cols = [c for c in name_cols + ["VALUE", "BUDGET_TYPE"] if c in df.columns]
    # Build figure
    fig = px.treemap(
        data_frame=df[keep_cols],
        path=name_cols,
        values="VALUE",
        hover_data=None,
        custom_data=["BUDGET_TYPE"],
        title=" ",  # Placeholder, important for download
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
    # Build a label→orig_id mapping for PROGRAM_0 so colors are language-agnostic.
    # Both the Russian and translated labels map to the same orig_id.
    program_label_to_orig_id: dict[str, str] = {}
    if viewby == "PROGRAM" and "PROGRAM_0_ORIG_ID" in df.columns:
        for name_col in ("PROGRAM_0_NAME", "PROGRAM_0_NAME_TRANSLATED"):
            if name_col in df.columns:
                for label, orig_id in zip(df[name_col], df["PROGRAM_0_ORIG_ID"]):
                    if label and orig_id and pd.notna(label) and pd.notna(orig_id):
                        program_label_to_orig_id[str(label)] = str(orig_id)

    # Generate list of colors for each node based on classified status, node_id and spending type
    colors = create_treemap_colors(
        node_ids,
        budget_types,
        spending_type,
        viewby,
        program_label_to_orig_id or None,
    )

    # Replace long path-string ids with short integer ids to reduce JSON payload.
    # The root virtual node keeps its empty-string id; all others get sequential integers.
    path_to_short_id: dict[str, str] = {}
    counter = 0
    for nid in node_ids:
        if nid and nid not in path_to_short_id:
            path_to_short_id[nid] = str(counter)
            counter += 1
    new_ids = [path_to_short_id.get(nid, nid) for nid in node_ids]
    new_parents = [path_to_short_id.get(p, p) for p in parents]

    # Combine existing customdata with new percentage data and node ids for hover and click interactions.
    # Attach custom data for hover to every node, including id for click selection.
    fig.update_traces(
        ids=new_ids,
        parents=new_parents,
        marker_colors=colors,
        customdata=list(
            zip(
                [round(p, 2) for p in parent_percentages],
                [round(p, 2) for p in root_percentages],
            )
        ),
        hovertemplate="<br>".join(
            [
                "%{label}",
                "%{value:,.1f}" + unit_config.map[unit],
                "%{customdata[0]:.1f}%" + " of parent",
                "%{customdata[1]:.1f}%" + " of total",
            ]
        ),
        texttemplate="%{label}<br>%{value:,.1f}" + unit_config.map[unit],
    )

    # Layout adjustments
    fig.update_layout(
        autosize=True,
        width=None,  # don't hardcode width
        height=None,  # don't hardcode height
        margin=dict(t=20, l=10, r=10, b=10),
        font=dict(family="Source Sans 3", color="#444444"),
    )

    return fig, path_to_short_id


def _build_compact_node_map(
    df: pd.DataFrame, path_to_short_id: dict[str, str] | None = None
) -> dict[str, str]:
    """Build a compact {short_id: dim_id} reverse map for clientside JS use.

    Each short_id is unique (assigned per path), so the same dim_id appearing under
    multiple parents gets a separate entry — no overwrites.
    """
    compact: dict[str, str] = {}
    records = df.to_dict("records")

    # path_to_short_id covers only the figure's current language; assign fresh IDs for the other.
    next_id = (
        max((int(v) for v in path_to_short_id.values()), default=-1) + 1 if path_to_short_id else 0
    )
    extra_path_to_id: dict[str, str] = {}

    for name_ending in ("_NAME", "_NAME_TRANSLATED"):
        name_cols = ["ROOT"] + [col for col in df.columns if col.endswith(name_ending)]

        for record in records:
            labels: list[str] = []
            for col in name_cols:
                label = record.get(col)
                if not label:
                    continue
                labels.append(str(label))
                if col == "ROOT":
                    continue
                dim_id = record.get(f"{col.replace(name_ending, '')}_DIM_ID")
                if pd.isnull(dim_id):
                    continue
                path = "/".join(labels)
                if path_to_short_id and path in path_to_short_id:
                    node_ref = path_to_short_id[path]
                elif path in extra_path_to_id:
                    node_ref = extra_path_to_id[path]
                else:
                    node_ref = str(next_id)
                    extra_path_to_id[path] = node_ref
                    next_id += 1
                compact[node_ref] = str(int(dim_id))

    return compact


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
            dcc.Graph(
                id="timeseries-graph",
                responsive=True,
                style={"display": "none", "height": "100%", "width": "100%"},
            ),
            # Loading spinner overlay, hidden once the graph is ready.
            html.Div(
                html.Div(className="treemap-spinner"),
                id="treemap-spinner",
                style={
                    "position": "absolute",
                    "top": "50%",
                    "left": "50%",
                    "transform": "translate(-50%, -50%)",
                    "zIndex": 10,
                },
            ),
            dcc.Graph(
                responsive=True,
                id="treemap-graph",
                config=TREEMAP_CONFIG,
                style={"visibility": "hidden", "height": "100%", "width": "100%"},
            ),
        ],
        style={"width": "100%", "height": "100%", "position": "relative"},
    )


@callback(
    Output("treemap-graph", "figure"),
    Output("treemap-graph", "style"),
    Output("store-treemap-node-map", "data"),
    Output("warning-toast", "is_open", allow_duplicate=True),
    Output("warning-toast", "children", allow_duplicate=True),
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
) -> tuple[Any, Any, Any, bool, str]:
    # Guard: only run when the treemap page is active.
    if pathname != get_relative_path("/"):
        raise PreventUpdate
    # Guard: wait until a budget is selected
    if budget_id is None:
        raise PreventUpdate

    # Fetch and render using the selected values from stores
    # Use translated names when language is EN (English)
    translated = language == "EN"
    try:
        df = transform_treemap_data(
            budget_id=budget_id,
            spending_type=spending_type,
            unit=unit,
        )
    except ValueError as e:
        return no_update, no_update, no_update, True, str(e)

    df_shaped = shape_for_spending_type(df, spending_type=spending_type)
    df_shaped = shape_for_viewby(df_shaped, viewby=viewby)
    fig, path_to_short_id = generate_figure(
        df_shaped, spending_type, unit=unit, translated=translated, viewby=viewby
    )
    compact_map = _build_compact_node_map(df_shaped, path_to_short_id=path_to_short_id)
    return (
        fig,
        {"visibility": "visible"},
        compact_map,
        False,
        "",
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
        return str(node_id)
    except Exception:
        raise PreventUpdate


def _build_download_df(
    df: pd.DataFrame,
    spending_type: SpendingTypeLiteral,
    viewby: ViewByDimensionTypeLiteral,
    translated: bool,
    unit: UnitLiteral = "ABSOLUTE",
) -> pd.DataFrame:
    """Build a flat aggregated DataFrame for CSV download with root, Level 1, Level 2, value columns."""
    df_shaped = shape_for_spending_type(df, spending_type=spending_type)
    df_shaped = shape_for_viewby(df_shaped, viewby=viewby)

    name_ending = "_NAME_TRANSLATED" if translated else "_NAME"
    name_cols = [col for col in df_shaped.columns if col.endswith(name_ending)]

    leaf1_col = name_cols[0] if len(name_cols) > 0 else None
    leaf2_col = name_cols[1] if len(name_cols) > 1 else None

    root_name = df_shaped["ROOT"].iloc[0] if len(df_shaped) > 0 else "Federal Budget"
    value_col = get_unit_label(unit)

    def clean(val: Any) -> str | None:
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return None
        return str(val).replace("<br>", " ")

    rows: list[dict[str, Any]] = []

    # Root aggregate across all rows
    rows.append(
        {
            "Root": root_name,
            "Level 1": None,
            "Level 2": None,
            value_col: round(df_shaped["VALUE"].sum(), 2),
        }
    )

    if not leaf1_col:
        return pd.DataFrame(rows, columns=["Root", "Level 1", "Level 2", value_col])  # noqa: RET504

    # Drop rows where leaf1 is null — they have no meaningful hierarchy position
    base = df_shaped.dropna(subset=[leaf1_col])

    # Compute leaf1 subtotals via a single flat groupby
    leaf1_sums: pd.Series = base.groupby(leaf1_col, sort=True)["VALUE"].sum()

    # Compute (leaf1, leaf2) subtotals via a single flat groupby when leaf2 exists
    pair_sums: pd.DataFrame | None = None
    if leaf2_col:
        pair_sums = (
            base.dropna(subset=[leaf2_col])
            .groupby([leaf1_col, leaf2_col], sort=True)["VALUE"]
            .sum()
            .reset_index()
        )
        pair_sums.columns = pd.Index(["leaf1", "leaf2", "value"])

    for leaf1_val, leaf1_sum in leaf1_sums.items():
        leaf1_clean = clean(leaf1_val)
        if leaf1_clean is None:
            continue
        rows.append(
            {
                "Root": root_name,
                "Level 1": leaf1_clean,
                "Level 2": None,
                value_col: round(leaf1_sum, 2),
            }
        )

        if pair_sums is not None:
            for row2 in pair_sums[pair_sums["leaf1"] == leaf1_val].itertuples(index=False):
                leaf2_clean = clean(row2.leaf2)

                if leaf2_clean is None:
                    continue
                rows.append(
                    {
                        "Root": root_name,
                        "Level 1": leaf1_clean,
                        "Level 2": leaf2_clean,
                        value_col: round(float(row2.value), 2),  # type: ignore[arg-type]
                    }
                )

    return pd.DataFrame(rows, columns=["Root", "Level 1", "Level 2", value_col])


@callback(
    Output("download-treemap-data", "data"),
    Input("btn-download-csv", "n_clicks"),
    State("url", "pathname"),
    State("store-budget-id", "data"),
    State("store-budget-options", "data"),
    State("store-viewby", "data"),
    State("store-spending-type", "data"),
    State("store-unit", "data"),
    State("store-language", "data"),
    prevent_initial_call=True,
    optional=True,
)
def download_treemap_data(
    n_clicks,
    pathname: str | None,
    budget_id: int,
    budget_options: list[dict] | None,
    viewby: ViewByDimensionTypeLiteral,
    spending_type: SpendingTypeLiteral,
    unit: UnitLiteral,
    language: str = "RU",
) -> dict[str, Any]:
    if pathname != get_relative_path("/"):
        raise PreventUpdate
    df = transform_treemap_data(
        budget_id=budget_id,
        spending_type=spending_type,
        unit=unit,
    )
    translated = language == "EN"
    download_df = _build_download_df(
        df, spending_type=spending_type, viewby=viewby, translated=translated, unit=unit
    )
    budget_label = next(
        (o["label"] for o in (budget_options or []) if o["value"] == budget_id), str(budget_id)
    )
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    sanitized = budget_label.replace(" ", "_").replace("/", "-")
    military = "_military" if spending_type == "MILITARY" else ""
    filename = f"treemap_{timestamp}_{sanitized}_{unit.lower()}{military}.csv"
    buf = io.BytesIO()
    download_df.to_csv(buf, sep=";", index=False, encoding="utf-8-sig")
    return dcc.send_bytes(buf.getvalue(), filename)  # type: ignore
