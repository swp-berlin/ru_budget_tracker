import io
from datetime import date, datetime
from functools import lru_cache
from typing import Any, Optional, Sequence

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
    get_relative_path,
    no_update,
)
from dash.exceptions import PreventUpdate
from sqlalchemy import RowMapping

from callbacks.helper import (
    build_compact_node_map,
    build_name_cols,
    create_treemap_colors,
    create_treemap_text_colors,
    get_unit_label,
    shape_dataframe,
)
from utils.calculate import Calculator
from utils.definitions import (
    BudgetTypeLiteral,
    Colors,
    SpendingTypeLiteral,
    UnitTypeLiteral,
    ViewByDimensionTypeLiteral,
    unit_config,
)
from utils.fetch_treemap import (
    ClassifiedSpendingData,
    TreemapDataFetcher,
    fetch_treemap_hierarchy,
)
from utils.transform_treemap import TreemapTransformer


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
    unit: UnitTypeLiteral,
) -> pd.DataFrame:
    dimensions, programs, classified, published_at = fetch_treemap_data(budget_id)
    budget_type: BudgetTypeLiteral = next(
        (row["budget_type"] for row in dimensions if row["budget_type"] in ["LAW", "REPORT"]), "LAW"
    )
    transformer = TreemapTransformer(dimensions, programs, classified, spending_type=spending_type)
    flat_rows = fetch_treemap_hierarchy(budget_id)
    if flat_rows:
        df = transformer.transform_from_flat(flat_rows)
    else:
        df = transformer.transform_data()
    calculator = Calculator(unit, budget_id, published_at, budget_type)
    df["VALUE"] = calculator.calculate_series(df["VALUE"]).clip(lower=0)
    return df


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


def _prepare_trace_overrides(
    trace_data: Any,
    df: pd.DataFrame,
    viewby: ViewByDimensionTypeLiteral,
    spending_type: SpendingTypeLiteral,
    unit: UnitTypeLiteral,
) -> tuple[dict, dict[str, str]]:
    """Compute ids, colors, percentages, and templates for fig.update_traces.

    Returns (trace_kwargs, path_to_short_id). path_to_short_id maps original
    Plotly path strings to compact integer ids and is needed by build_compact_node_map.
    """
    node_ids: list[str] = list(trace_data["ids"])
    parents: list[str] = list(trace_data["parents"])
    values: list[float] = [float(v) if v is not None else 0.0 for v in trace_data["values"]]
    # px.treemap wraps each custom_data value in a list, so each entry is [budget_type_str].
    budget_types: list[str] = [budget_type[0] for budget_type in trace_data["customdata"]]

    # Compute percentages for all nodes based on treemap aggregation.
    parent_percentages, root_percentages = _compute_percentages(parents, values)

    # Build a label→orig_id mapping for PROGRAM_0 so colors are language-agnostic.
    # Both the Russian and translated labels map to the same orig_id.
    program_label_to_orig_id: dict[str, str] = {}
    if viewby == "PROGRAM" and "PROGRAM_0_ORIG_ID" in df.columns:
        for name_col in ("PROGRAM_0_NAME", "PROGRAM_0_NAME_TRANSLATED"):
            if name_col in df.columns:
                for label, orig_id in zip(df[name_col], df["PROGRAM_0_ORIG_ID"]):
                    if label and orig_id and pd.notna(label) and pd.notna(orig_id):
                        program_label_to_orig_id[str(label)] = str(orig_id)

    colors = create_treemap_colors(
        node_ids,
        budget_types,
        values,
        spending_type,
        viewby,
        program_label_to_orig_id or None,
    )
    text_colors = create_treemap_text_colors(colors)

    # Replace long path-string ids with short integer ids to reduce JSON payload.
    # The root virtual node keeps its empty-string id; all others get sequential integers.
    unique_nids = dict.fromkeys(nid for nid in node_ids if nid)
    path_to_short_id = {nid: str(i) for i, nid in enumerate(unique_nids)}
    unit_label = unit_config.map[unit]

    trace_kwargs = dict(
        ids=[path_to_short_id.get(nid, nid) for nid in node_ids],
        parents=[path_to_short_id.get(p, p) for p in parents],
        marker_colors=colors,
        textfont_color=text_colors,
        pathbar_textfont_size=18,  # Max size of pathbar text. Increase with text size.
        marker_pad=dict(t=25, l=5, r=5, b=5),
        customdata=list(
            zip(
                [round(p, 2) for p in parent_percentages],
                [round(p, 2) for p in root_percentages],
            )
        ),
        hovertemplate="<br>".join(
            [
                "<b>%{label}</b>",
                "<br>%{value:,.1f}" + unit_config.map[unit],
                "%{customdata[0]:.1f}%" + " of parent",
                "%{customdata[1]:.1f}%" + " of total",
            ]
        ),
        texttemplate="%{label}<br>%{value:,.1f}" + unit_config.map[unit],
    )
    return trace_kwargs, path_to_short_id


def generate_figure(
    df: pd.DataFrame,
    spending_type: SpendingTypeLiteral = "ALL",
    unit: UnitTypeLiteral = "ABSOLUTE",
    translated: bool = False,
    viewby: ViewByDimensionTypeLiteral = "MINISTRY",
) -> tuple[go.Figure, dict[str, str]]:
    """Build a treemap with stable ids and clean hover info."""
    name_ending = "_NAME_TRANSLATED" if translated else "_NAME"
    name_cols = build_name_cols(df, name_ending, include_root=True)
    keep_cols = [c for c in name_cols + ["VALUE", "BUDGET_TYPE"] if c in df.columns]

    fig = px.treemap(
        data_frame=df[keep_cols],
        path=name_cols,
        values="VALUE",
        hover_data=None,
        custom_data=["BUDGET_TYPE"],
        title=" ",  # Placeholder, important for download
    )

    trace_kwargs, path_to_short_id = _prepare_trace_overrides(
        fig.data[0], df, viewby, spending_type, unit
    )
    fig.update_traces(**trace_kwargs)
    fig.update_layout(
        autosize=True,
        width=None,  # don't hardcode width
        height=None,  # don't hardcode height
        margin=dict(t=27, l=10, r=10, b=10),
        # Default for pathbar and title; tile labels are overridden per node above.
        font=dict(family="Source Sans 3", color=Colors.TEXT_ON_LIGHT),
    )

    return fig, path_to_short_id


def remap_selected_id(
    selected_id: str | None,
    previous_node_map: dict | None,
    new_node_map: dict | None,
) -> str | None:
    """Map a transient Plotly id to the same semantic node in a new figure.

    Compact ids are reassigned whenever the Treemap is rebuilt. The stable
    identity is the leaf dimension id together with its ancestor context.
    Returning ``None`` deliberately selects the root when that identity is not
    available under the new hierarchy or spending filter.
    """
    if not selected_id or not previous_node_map or not new_node_map:
        return None
    previous = previous_node_map.get(str(selected_id))
    if not isinstance(previous, dict):
        return None
    identity = (
        str(previous.get("leaf", "")),
        tuple(str(value) for value in (previous.get("ctx", []) or [])),
    )
    if not identity[0]:
        return None
    for node_id, entry in new_node_map.items():
        if not isinstance(entry, dict):
            continue
        candidate = (
            str(entry.get("leaf", "")),
            tuple(str(value) for value in (entry.get("ctx", []) or [])),
        )
        if candidate == identity:
            return str(node_id)
    return None


@callback(
    Output("treemap-graph", "figure"),
    Output("treemap-graph", "style"),
    Output("store-treemap-node-map", "data"),
    Output("store-selected-id", "data", allow_duplicate=True),
    Output("store-treemap-hierarchy-key", "data"),
    Output("warning-toast", "is_open", allow_duplicate=True),
    Output("warning-toast", "children", allow_duplicate=True),
    Input("treemap-page-ready", "data", allow_optional=True),
    Input("url", "pathname"),
    Input("store-budget-id", "data"),
    Input("store-viewby", "data"),
    Input("store-spending-type", "data"),
    Input("store-unit", "data"),
    Input("store-language", "data"),
    State("store-treemap-hierarchy-key", "data"),
    State("store-selected-id", "data"),
    State("store-treemap-node-map", "data"),
    prevent_initial_call="initial_duplicate",
)
def update_figure_from_filters(
    page_ready: bool | None,
    pathname: str | None,
    budget_id: int,
    viewby: ViewByDimensionTypeLiteral = "MINISTRY",
    spending_type: SpendingTypeLiteral = "ALL",
    unit: UnitTypeLiteral = "ABSOLUTE",
    language: str = "EN",
    previous_hierarchy_key: list | None = None,
    selected_id: str | None = None,
    previous_node_map: dict | None = None,
) -> tuple[Any, Any, Any, Any, Any, bool, str]:
    if not page_ready:
        raise PreventUpdate
    # Guard: only run when the treemap page is active.
    if pathname != get_relative_path("/"):
        raise PreventUpdate
    # Guard: wait until a budget is selected
    if budget_id is None:
        raise PreventUpdate

    hierarchy_key = [viewby, spending_type]

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
        return no_update, no_update, no_update, no_update, no_update, True, str(e)

    df_shaped = shape_dataframe(df, spending_type, viewby)
    fig, path_to_short_id = generate_figure(
        df_shaped, spending_type, unit=unit, translated=translated, viewby=viewby
    )
    compact_map = build_compact_node_map(df_shaped, path_to_short_id=path_to_short_id)
    selection_update = (
        remap_selected_id(selected_id, previous_node_map, compact_map)
        if selected_id
        else no_update
    )
    return (
        fig,
        {"visibility": "visible"},
        compact_map,
        selection_update,
        hierarchy_key,
        False,
        "",
    )


clientside_callback(
    ClientsideFunction(namespace="clientside", function_name="storeTreemapSelection"),
    Output("store-selected-id", "data"),
    Input("treemap-graph", "clickData"),
)


def _build_download_df(
    df: pd.DataFrame,
    spending_type: SpendingTypeLiteral,
    viewby: ViewByDimensionTypeLiteral,
    translated: bool,
    unit: UnitTypeLiteral = "ABSOLUTE",
) -> pd.DataFrame:
    """Build a flat aggregated DataFrame for CSV download with root, Level 1, Level 2, value columns."""
    df_shaped = shape_dataframe(df, spending_type, viewby)

    name_ending = "_NAME_TRANSLATED" if translated else "_NAME"
    name_cols = build_name_cols(df_shaped, name_ending)

    leaf1_col = name_cols[0] if len(name_cols) > 0 else None
    leaf2_col = name_cols[1] if len(name_cols) > 1 else None

    root_name = df_shaped["ROOT"].iloc[0] if len(df_shaped) > 0 else "Federal budget"
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
    Output("warning-toast", "is_open", allow_duplicate=True),
    Output("warning-toast", "children", allow_duplicate=True),
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
    unit: UnitTypeLiteral,
    language: str = "EN",
) -> tuple[Any, Any, Any]:
    if pathname != get_relative_path("/"):
        raise PreventUpdate
    try:
        df = transform_treemap_data(
            budget_id=budget_id,
            spending_type=spending_type,
            unit=unit,
        )
    except ValueError as e:
        return no_update, True, str(e)
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
    download_df.to_csv(
        buf, sep=";", index=False, encoding="utf-8-sig"
    )  # utf-8-sig adds BOM for Excel
    return dcc.send_bytes(buf.getvalue(), filename), no_update, no_update
