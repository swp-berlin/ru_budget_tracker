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

from utils import TreemapTransformer, TremapDataFetcher, fetch_budgets
from utils.calculate import Calculator
from utils.definitions import (
    LanguageTypeLiteral,
    SpendingScopeLiteral,
    SpendingTypeLiteral,
    ViewByDimensionTypeLiteral,
)
from utils.helper import add_breaks

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

register_page(__name__, path="/")

# Graph config kept simple and explicit for production clarity
TREEMAP_CONFIG = dcc.Graph.Config(
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

SPENDING_SCOPE_OPTIONS: list[tuple[str, str]] = [
    ("Billion RUB", "ABSOLUTE"),
    ("% full-year GDP", "PERCENT_GDP_FULL_YEAR"),
    ("% year-to-year GDP", "PERCENT_GDP_YEAR_TO_YEAR"),
    ("% full-year spending", "PERCENT_FULL_YEAR_SPENDING"),
    ("% year-to-year spending", "PERCENT_YEAR_TO_YEAR_SPENDING"),
    ("% year-to-year revenue", "PERCENT_YEAR_TO_YEAR_REVENUE"),
]


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
    spending_scope: SpendingScopeLiteral = "ABSOLUTE",
    viewby: ViewByDimensionTypeLiteral = "MINISTRY",
    character_limit: int = 30,
) -> tuple[list[str], list[str], list[float], list[str]]:
    """Fetch and transform treemap data for the current filters."""
    data_fetcher = TremapDataFetcher()
    dimensions, programs, sum_mapping = data_fetcher.fetch_data(
        budget_id=budget_id,
        spending_scope=spending_scope,
    )
    transformer = TreemapTransformer()
    labels, parents, values, metadata = transformer.transform_data(
        dimensions,
        programs,
        sum_mapping,
        translated_names=False,
        viewby=viewby,
        spending_type=spending_type,
    )
    calculator = Calculator(spending_scope=spending_scope)
    values = [calculator.calculate(v) if v is not None else 0.0 for v in values]
    # Add line breaks for better label rendering
    labels = [add_breaks(lbl, interval=character_limit) for lbl in labels]
    parents = [add_breaks(par, interval=character_limit) for par in parents]
    return labels, parents, values, metadata


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
    parent_percentages, root_percentages = _compute_percentages(parents, values)

    # Use leaf-only sizing by setting branch values to 0
    parent_labels = set(parents)
    area_values = [0 if lbl in parent_labels else v for lbl, v in zip(labels, values)]

    # Prepare stable ids and map parent labels -> ids
    node_ids = metadata
    label_to_id: dict[str, str] = {label: node_id for label, node_id in zip(labels, node_ids)}
    parent_ids: list[str] = ["" if p == "" else label_to_id.get(p, "") for p in parents]

    # Build figure
    fig = px.treemap(
        names=labels,
        parents=parent_ids,
        ids=node_ids,
        values=area_values,
        hover_data=None,
    )
    # If spending type is military, adjust the color of the root tiles to #7e8f5f
    # and then get lighter shades of #7e8f5f for the children the deeper they are in the hierarchy
    if spending_type == "MILITARY":
        colorscale = [[1, "#7e8f5f"], [0.5, "#a3b18a"], [0, "#c7d0b8"]]
        fig.update_layout(treemapcolorway=["#7e8f5f"], coloraxis_colorscale=colorscale)

    # Populate hover with original values and percentages; include explicit node id
    fig.data[0].customdata = [
        [v, m, pp, rp, nid]
        for v, m, pp, rp, nid in zip(
            values, metadata, parent_percentages, root_percentages, node_ids
        )
    ]
    fig.data[0].hovertemplate = (
        "<b>%{label}</b><br>"
        "ID: %{customdata[4]}<br>"
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

    spending_scope_items = [
        dbc.DropdownMenuItem(
            html.Span(label, title=label),
            id={"type": "spending-scope-item", "value": value},
        )
        for label, value in SPENDING_SCOPE_OPTIONS
    ]
    return html.Div(
        [
            # Store currently selected filter values (these replace dcc.Dropdown.value)
            dcc.Store(id="store-budget-options"),
            dcc.Store(id="store-budget-id"),
            dcc.Store(id="store-viewby", data="MINISTRY"),
            dcc.Store(id="store-spending-type", data="ALL"),
            dcc.Store(id="store-spending-scope", data="ABSOLUTE"),
            # Location component to access URL parameters
            dcc.Location(id="url"),
            # This dummy div is the target for our clientside callback. It's required for the
            # callback to have an Output, but it doesn't need to be visible.
            html.Div(id="dummy-treemap-output", style={"display": "none"}),
            # Add Buttons and dropdowns for filtering by budget type
            dbc.Stack(
                [
                    # Logo image without button styling - only the image is visible
                    html.A(
                        [
                            html.Img(
                                src="/assets/logo/logo.svg",
                                style={"height": "2em"},
                                alt="Logo of Stiftung Wissenschaft und Politik",
                            ),
                        ],
                        style={"margin-right": "20px", "align-self": "center"},
                        href="/",
                        title="Go to Home Page",
                    ),
                    dbc.Stack(
                        [
                            # Budget dataset menu
                            dbc.DropdownMenu(
                                label="Budget",
                                children=[],  # will be set by callback
                                id="menu-budget",
                                direction="down",
                                class_name="me-2 scroll-menu",
                                # Make the dropdown list scrollable to handle many budgets
                            ),
                            # View-by menu
                            dbc.DropdownMenu(
                                label="View by",
                                children=viewby_items,
                                id="menu-viewby",
                                direction="down",
                                class_name="me-2",
                            ),
                            # Spending type menu
                            dbc.DropdownMenu(
                                label="Spending type",
                                children=spending_type_items,
                                id="menu-spending-type",
                                direction="down",
                                class_name="me-2",
                            ),
                            # Spending scope menu
                            dbc.DropdownMenu(
                                label="Spending scope",
                                children=spending_scope_items,
                                id="menu-spending-scope",
                                direction="down",
                                class_name="me-2",
                            ),
                        ],
                        direction="horizontal",
                        gap=2,
                        class_name="me-auto",
                    ),
                    dbc.Stack(
                        [
                            dbc.Button(
                                html.Img(
                                    src="/assets/icons/share.svg",
                                    style={"width": "2em", "height": "2em"},
                                ),
                                id="btn-share-link",
                                title="Copy shareable link to clipboard",
                            ),
                            dbc.Toast(
                                id="share-toast",
                                header="Link copied",
                                children="The shareable link was copied to your clipboard.",
                                is_open=False,
                                duration=2000,
                                dismissable=False,
                                style={
                                    "position": "fixed",
                                    "bottom": 20,
                                    "left": "50%",
                                    "transform": "translateX(-50%)",
                                    "zIndex": 1060,
                                },
                            ),
                            dbc.Button(
                                html.Img(
                                    src="/assets/icons/photo_camera.svg",
                                    style={"width": "2em", "height": "2em"},
                                ),
                                id="btn-download-image",
                                title="Download Treemap Plot as PNG",
                            ),
                            dcc.Download(id="download-treemap-image"),
                            dbc.Button(
                                html.Img(
                                    src="/assets/icons/download.svg",
                                    style={"width": "2em", "height": "2em"},
                                ),
                                id="btn-download-csv",
                                title="Download Treemap Data as CSV",
                            ),
                            dcc.Download(id="download-treemap-data"),
                            dbc.Button(
                                html.Img(
                                    src="/assets/icons/stacked_bar_chart.svg",
                                    style={"width": "2em", "height": "2em"},
                                ),
                                title="Switch to Time Series View",
                            ),
                            dbc.Button(
                                html.Img(
                                    src="/assets/icons/info.svg",
                                    style={"width": "2em", "height": "2em"},
                                ),
                                title="About This Project",
                                href="/about",
                            ),
                        ],
                        direction="horizontal",
                        gap=2,
                    ),
                ],
                direction="horizontal",
                style={
                    "margin-bottom": "10px",
                    "margin-top": "10px",
                    "margin-left": "15px",
                    "margin-right": "15px",
                },
            ),
            # add divider line
            dbc.Row(html.Hr()),
            html.Div(
                # Graph to display the treemap
                [
                    dcc.Store(id="treemap-store"),
                    dcc.Store(id="store-selected-id"),
                    dcc.Graph(
                        id="treemap-graph", config=TREEMAP_CONFIG, style={"visibility": "hidden"}
                    ),
                ],
                style={"width": "100%", "height": "90vh"},
            ),
        ]
    )


@callback(
    Output("treemap-graph", "figure"),
    Output("treemap-graph", "style"),
    Input("store-budget-id", "data"),
    Input("store-viewby", "data"),
    Input("store-spending-type", "data"),
    Input("store-spending-scope", "data"),
)
def update_figure_from_filters(
    budget_id: int | None = None,
    viewby: ViewByDimensionTypeLiteral = "MINISTRY",
    spending_type: SpendingTypeLiteral = "ALL",
    spending_scope: SpendingScopeLiteral = "ABSOLUTE",
) -> tuple[go.Figure, dict[str, str]]:
    # Fetch and render using the selected values from stores
    labels, parents, values, metadata = fetch_treemap_data(
        budget_id=budget_id,
        spending_type=spending_type,
        spending_scope=spending_scope,
        viewby=viewby,
    )
    return generate_figure(labels, parents, values, metadata, spending_type, language="EN"), {
        "visibility": "visible"
    }


# Callback to handle store
@callback(
    Output("treemap-store", "data"),
    Input("store-budget-id", "data"),
    Input("store-viewby", "data"),
    Input("store-spending-type", "data"),
    Input("store-spending-scope", "data"),
)
def update_store_data(
    budget_id: int | None = None,
    viewby: ViewByDimensionTypeLiteral = "MINISTRY",
    spending_type: SpendingTypeLiteral = "ALL",
    spending_scope: SpendingScopeLiteral = "ABSOLUTE",
) -> dict[str, Any]:
    """
    This callback updates the store with the current data based on filters.

    Returns:
        dict[str, Any]: The data to store.
    """
    filter_data = {
        "budget_id": budget_id,
        "viewby": viewby,
        "spending_type": spending_type,
        "spending_scope": spending_scope,
    }
    return filter_data


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
    State("treemap-store", "data"),
    prevent_initial_call=True,
)
def download_data(n_clicks, data) -> dict[str, Any]:
    """
    Callback to download the current treemap data as a csv file.
    Returns:
        dict[str, Any]: The data for download.
    """
    labels, parents, values, metadata = fetch_treemap_data(
        budget_id=data["budget_id"],
        spending_type=data["spending_type"],
        spending_scope=data["spending_scope"],
        viewby=data["viewby"],
    )
    return dcc.send_data_frame(  # type: ignore
        pd.DataFrame(
            {
                "Label": labels,
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
)
def download_image(n_clicks: int | None, figure_json: dict) -> dict[str, Any] | None:
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


# View-by selection (pattern-matched, single callback)
@callback(
    Output("store-viewby", "data"),
    Input({"type": "viewby-item", "value": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def select_viewby(_clicks):
    ctx = dash.callback_context
    if not ctx.triggered:
        raise PreventUpdate
    trig = getattr(ctx, "triggered_id", None)
    if isinstance(trig, dict) and trig.get("type") == "viewby-item":
        return trig.get("value")
    raise PreventUpdate


# Spending type selection (pattern-matched)
@callback(
    Output("store-spending-type", "data"),
    Input({"type": "spending-type-item", "value": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def select_spending_type(_clicks):
    ctx = dash.callback_context
    if not ctx.triggered:
        raise PreventUpdate
    trig = getattr(ctx, "triggered_id", None)
    if isinstance(trig, dict) and trig.get("type") == "spending-type-item":
        return trig.get("value")
    raise PreventUpdate


# Spending scope selection (pattern-matched)
@callback(
    Output("store-spending-scope", "data"),
    Input({"type": "spending-scope-item", "value": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def select_spending_scope(_clicks):
    ctx = dash.callback_context
    if not ctx.triggered:
        raise PreventUpdate
    trig = getattr(ctx, "triggered_id", None)
    if isinstance(trig, dict) and trig.get("type") == "spending-scope-item":
        return trig.get("value")
    raise PreventUpdate


@callback(
    Output("store-budget-options", "data"),
    Output("store-budget-id", "data"),
    Output("menu-budget", "children"),
    Input("url", "pathname"),  # fire once on load
    prevent_initial_call=False,
)
def init_budgets(_):
    # Fetch once and share everywhere via Store
    options = [
        {"label": b["name_translated"] or b["name"], "value": b["id"]} for b in fetch_budgets()
    ]
    # Build menu items with pattern ids
    items = [
        dbc.DropdownMenuItem(
            html.Span(opt["label"], title=opt["label"]),
            id={"type": "budget-item", "value": opt["value"]},
        )
        for opt in options
    ]
    default_value = options[0]["value"] if options else None
    return options, default_value, items


@callback(
    Output("store-budget-id", "data", allow_duplicate=True),
    Output("store-viewby", "data", allow_duplicate=True),
    Output("store-spending-type", "data", allow_duplicate=True),
    Output("store-spending-scope", "data", allow_duplicate=True),
    Input("url", "search"),
    prevent_initial_call="initial_duplicate",
)
def apply_filters_from_url(url_search: str | None):
    """Apply filters from URL query params on load and when the URL changes.

    Recognized params: budget_id, viewby, spending_type, spending_scope.
    Missing params leave the current store values unchanged by returning PreventUpdate markers.
    """
    if not url_search:
        raise PreventUpdate
    try:
        from urllib.parse import parse_qs, unquote_plus

        params = parse_qs(url_search.replace("?", ""))

        # Extract values safely
        def first(key: str):
            vals = params.get(key)
            return unquote_plus(vals[0]).strip() if vals and len(vals) > 0 else None

        budget_id_raw = first("budget_id")
        viewby = first("viewby")
        spending_type = first("spending_type")
        spending_scope = first("spending_scope")

        budget_id = int(budget_id_raw) if budget_id_raw and budget_id_raw.isdigit() else None

        # If none provided, avoid overwriting by returning PreventUpdate
        outputs: list[Any] = []
        outputs.append(budget_id if budget_id is not None else dash.no_update)
        outputs.append(viewby if viewby else dash.no_update)
        outputs.append(spending_type if spending_type else dash.no_update)
        outputs.append(spending_scope if spending_scope else dash.no_update)
        return tuple(outputs)
    except Exception:
        raise PreventUpdate


@callback(
    Output("store-budget-id", "data", allow_duplicate=True),
    Input("store-budget-options", "data"),
    Input({"type": "budget-item", "value": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def select_budget_dynamic(options, clicks):
    """
    Update selected budget_id when any budget menu item is clicked.

    Fix:
    - Use dash.callback_context.triggered_id (parsed) instead of json.loads(prop_id).
    - Only act when the triggered id is a dict with type == "budget-item".
    """
    ctx = dash.callback_context

    # If nothing triggered, do nothing
    if not ctx.triggered:
        raise PreventUpdate

    # triggered_id is either a dict (for pattern-matched components) or a string id
    trig = getattr(ctx, "triggered_id", None)

    # Guard: ignore triggers from non-budget inputs (e.g., store-budget-options)
    if not isinstance(trig, dict):
        # Not a pattern-matched id -> ignore
        raise PreventUpdate

    # Guard: ensure we only react to budget-item clicks
    if trig.get("type") != "budget-item":
        raise PreventUpdate

    selected_value = trig.get("value")
    if selected_value is None:
        # No value in id -> ignore
        raise PreventUpdate

    # Return the selected budget id to the store
    return selected_value


@callback(
    Output("menu-budget", "label"),
    Input("store-budget-id", "data"),
    State("store-budget-options", "data"),
)
def show_selected_budget_label(
    budget_id: Optional[int], options: list[dict[str, Any]] | None
) -> str:
    """
    Set the Budget menu's label to the selected budget's display name.
    Falls back to 'Budget' if nothing is selected or options missing.
    """
    if not options or budget_id is None:
        return "Budget"
    # Find the option whose value matches the selected id
    for opt in options:
        if opt.get("value") == budget_id:
            return opt.get("label", "Budget")
    return "Budget"  # default if not found


@callback(
    Output("menu-viewby", "label"),
    Output("menu-spending-type", "label"),
    Output("menu-spending-scope", "label"),
    Input("store-viewby", "data"),
    Input("store-spending-type", "data"),
    Input("store-spending-scope", "data"),
)
def update_menu_labels(viewby: str | None, spending_type: str | None, spending_scope: str | None):
    viewby_map = {
        "MINISTRY": "View by: Ministry",
        "CHAPTER": "View by: Chapter",
        "PROGRAM": "View by: Program",
    }
    spending_type_map = {
        "ALL": "Spending type: All",
        "MILITARY": "Spending type: Military Only",
    }
    spending_scope_map = {
        "ABSOLUTE": "Scope: Billion RUB",
        "PERCENT_GDP_FULL_YEAR": "Scope: % full-year GDP",
        "PERCENT_GDP_YEAR_TO_YEAR": "Scope: % year-to-year GDP",
        "PERCENT_FULL_YEAR_SPENDING": "Scope: % full-year spending",
        "PERCENT_YEAR_TO_YEAR_SPENDING": "Scope: % year-to-year spending",
        "PERCENT_YEAR_TO_YEAR_REVENUE": "Scope: % year-to-year revenue",
    }
    return (
        viewby_map.get(viewby or "", "View by"),
        spending_type_map.get(spending_type or "", "Spending type"),
        spending_scope_map.get(spending_scope or "", "Spending scope"),
    )


# Clientside callback to handle URL focus parameter and click simulation
clientside_callback(
    ClientsideFunction(namespace="clientside", function_name="findAndClickSlice"),
    Output("dummy-treemap-output", "children"),
    Input("url", "search"),
    Input("treemap-graph", "figure"),
    prevent_initial_call=True,
)

# Clientside share: build URL with current filters and selected id, copy to clipboard
clientside_callback(
    ClientsideFunction(namespace="clientside", function_name="copyShareLink"),
    Output("dummy-treemap-output", "title"),
    Input("btn-share-link", "n_clicks"),
    State("url", "pathname"),
    State("store-budget-id", "data"),
    State("store-viewby", "data"),
    State("store-spending-type", "data"),
    State("store-spending-scope", "data"),
    State("store-selected-id", "data"),
    prevent_initial_call=True,
)


@callback(
    Output("share-toast", "is_open"),
    Input("btn-share-link", "n_clicks"),
    prevent_initial_call=True,
)
def show_share_toast(n_clicks: int | None) -> bool:
    if not n_clicks:
        raise PreventUpdate
    return True
