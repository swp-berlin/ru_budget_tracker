"""Dash Plotly App."""

from typing import Any
import dash_bootstrap_components as dbc
from dash import (
    ALL,
    ClientsideFunction,
    Dash,
    Input,
    Output,
    State,
    callback,
    callback_context,
    clientside_callback,
    dcc,
    html,
    no_update,
    page_container,
    get_asset_url,
    get_relative_path,
)
from dash.exceptions import PreventUpdate

from utils.fetch import fetch_budgets_for_dropdown
from utils.definitions import (
    UNIT_OPTIONS,
    PERIOD_OPTIONS,
    SPENDING_TYPE_OPTIONS,
    VIEWBY_OPTIONS,
    unit_map,
    spending_type_map,
    viewby_map,
    period_map,
)

from settings import settings

external_stylesheets = [
    dbc.themes.BOOTSTRAP,
]

app = Dash(
    __name__,
    use_pages=True,
    external_stylesheets=external_stylesheets,
    suppress_callback_exceptions=True,  # Required for pages with callbacks referencing shared stores
    update_title=None,  # type: ignore
    url_base_pathname=settings.app.url_base_pathname,  # Set base pathname from settings
)


server = app.server


@app.server.route("/healthz")
def healthz():
    return {"status": "ok"}


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

period_items = [
    dbc.DropdownMenuItem(
        html.Span(label, title=label),
        id={"type": "period-item", "value": value},
    )
    for label, value in PERIOD_OPTIONS
]

layout = html.Div(
    [
        # Store currently selected filter values (these replace dcc.Dropdown.value)
        dcc.Store(id="store-budget-options"),
        dcc.Store(id="store-budget-id"),
        # Store the treemap selection for cross-page filtering.
        dcc.Store(id="store-selected-id"),
        dcc.Store(id="store-viewby", data="CHAPTER"),
        dcc.Store(id="store-period", data="ALL"),
        dcc.Store(id="store-spending-type", data="ALL"),
        dcc.Store(id="store-unit", data="ABSOLUTE"),
        dcc.Store(id="store-language", data="RU"),
        # Store treemap node metadata for cross-page selection context.
        dcc.Store(id="store-treemap-node-map"),
        # Store for download status (used by clientside callback, not displayed)
        dcc.Store(id="store-download-status"),
        # Timeseries page: tick metadata and window width for responsive tick labels
        dcc.Store(id="store-timeseries-ticks"),
        dcc.Store(id="store-window-width", data=1280),
        dcc.Interval(id="timeseries-resize-interval", interval=300, disabled=True),
        # Location component to access URL parameters
        dcc.Location(id="url"),
        # This dummy div is the target for our clientside callback. It's required for the
        # callback to have an Output, but it doesn't need to be visible.
        html.Div(id="dummy-output", style={"display": "none"}),
        dbc.Stack(
            [
                # Logo image without button styling - only the image is visible
                html.A(
                    [
                        html.Img(
                            src=get_asset_url("logo/logo.svg"),
                            style={"height": "2em"},
                            alt="Logo of Stiftung Wissenschaft und Politik",
                        ),
                    ],
                    style={"marginRight": "20px", "alignSelf": "center"},
                    href=get_relative_path("/"),
                    title="Go to Home Page",
                ),
                html.Div(
                    [
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
                                # View-by menu (shown on treemap, hidden on timeseries)
                                dbc.DropdownMenu(
                                    label="View by",
                                    children=viewby_items,
                                    id="menu-viewby",
                                    direction="down",
                                    class_name="me-2",
                                    style={},  # controlled by callback
                                ),
                                # Period menu (for timeseries, hidden on treemap)
                                dbc.DropdownMenu(
                                    label="Period",
                                    children=period_items,
                                    id="menu-period",
                                    direction="down",
                                    class_name="me-2",
                                    style={"display": "none"},  # controlled by callback
                                ),
                                # Spending type menu
                                dbc.DropdownMenu(
                                    label="Spending type",
                                    children=spending_type_items,
                                    id="menu-spending-type",
                                    direction="down",
                                    class_name="me-2",
                                ),
                                # Unit menu
                                dbc.DropdownMenu(
                                    label="Unit",
                                    children=unit_items,
                                    id="menu-unit",
                                    direction="down",
                                    class_name="me-2",
                                ),
                            ],
                            direction="horizontal",
                            class_name="toolbar-group",
                        ),
                        # Stack for action buttons on the right
                        dbc.Stack(
                            [
                                # Button to switch to the time series view
                                dbc.Button(
                                    [
                                        # Icon for the button
                                        html.Img(
                                            src=get_asset_url("icons/stacked_bar_chart.svg"),
                                        ),
                                        # Text for the button
                                        html.Span("Timeseries", className="btn-label"),
                                    ],
                                    id="btn-switch-graphs",
                                    title="Switch to Time Series View",
                                    href="/timeseries",
                                ),
                                # Share button
                                dbc.Button(
                                    html.Img(
                                        src=get_asset_url("icons/share.svg"),
                                    ),
                                    id="btn-share-link",
                                    title="Copy shareable link to clipboard",
                                ),
                                # Toast notification for sharing
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
                                # Download image button
                                dbc.Button(
                                    html.Img(
                                        src=get_asset_url("icons/photo_camera.svg"),
                                    ),
                                    id="btn-download-image",
                                    title="Download Plot as PNG",
                                ),
                                dcc.Download(id="download-treemap-image"),
                                dcc.Download(id="download-timeseries-image"),
                                # Download data button
                                dbc.Button(
                                    html.Img(
                                        src=get_asset_url("icons/download.svg"),
                                    ),
                                    id="btn-download-csv",
                                    title="Download Data as CSV",
                                ),
                                dcc.Download(id="download-treemap-data"),
                                dcc.Download(id="download-timeseries-data"),
                                # Language toggle button: default text shows next language (EN), default param RU
                                dbc.Button(
                                    [
                                        # Text for the button
                                        html.Span("EN", className="btn-label"),
                                    ],
                                    id="btn-switch-data-language",
                                    title="Toggle data language",
                                ),
                                # Info/About button
                                dbc.Button(
                                    html.Img(
                                        src=get_asset_url("icons/info.svg"),
                                    ),
                                    id="btn-about",
                                    title="About This Project",
                                    href="/about",
                                ),
                            ],
                            direction="horizontal",
                            gap=2,
                            class_name="toolbar-group toolbar-actions",
                        ),
                    ],
                    className="toolbar-body",
                ),
            ],
            direction="horizontal",
            style={
                "marginBottom": "10px",
                "marginTop": "10px",
                "marginLeft": "15px",
                "marginRight": "15px",
            },
            class_name="toolbar",
        ),
        dbc.Row(html.Hr()),
    ]
)


def serve_layout():
    """Serve the layout as a function to defer component evaluation.

    This ensures callbacks in pages can reference stores defined here.
    """
    return html.Div(
        children=[
            layout,
            page_container,
        ]
    )


app.layout = serve_layout

# Validation layout includes all components that callbacks might reference.
# This prevents "component not found" warnings during callback validation.
app.validation_layout = html.Div(
    children=[
        layout,
        page_container,
        # Include page-specific components for callback validation
        dcc.Store(id="store-selected-id"),
        dcc.Store(id="store-treemap-node-map"),
        dcc.Graph(id="timeseries-graph"),
        dcc.Graph(id="treemap-graph"),
        dcc.Download(id="download-timeseries-data"),
        html.Div(id="timeseries-spinner"),
    ]
)


@callback(
    Output("btn-switch-graphs", "href"),
    Output("btn-switch-graphs", "children"),
    Output("btn-switch-graphs", "title"),
    Input("url", "pathname"),
    Input("store-budget-id", "data"),
)
def switch_graphs(pathname: str | None, budget_id: int | None):
    """Swap destination, icon, and label based on current page.

    - On root (/): link to /timeseries with stacked_bar_chart icon and label 'Timeseries'.
    - On /timeseries: link to / with dashboard icon and label 'Treemap'.
    - Includes budget_id as query parameter if available.
    """
    # Build query string with budget_id if available
    query_string = f"?budget_id={budget_id}" if budget_id is not None else ""

    if pathname == get_relative_path("/timeseries"):
        return (
            f"{get_relative_path('/')}{query_string}",
            [
                html.Img(src=get_asset_url("icons/dashboard.svg"), alt="Treemap icon"),
                html.Span("Treemap", className="btn-label"),
            ],
            "Switch to Treemap View",
        )
    # Default: treat anything else as root
    return (
        f"{get_relative_path('/timeseries')}{query_string}",
        [
            html.Img(src=get_asset_url("icons/stacked_bar_chart.svg"), alt="Timeseries icon"),
            html.Span("Timeseries", className="btn-label"),
        ],
        "Switch to Time Series View",
    )


@callback(
    Output("menu-viewby", "style"),
    Output("menu-period", "style"),
    Input("url", "pathname"),
    Input("store-budget-id", "data"),
    State("store-budget-options", "data"),
)
def toggle_viewby_period_menu(
    pathname: str | None, budget_id: int | None, options: list[dict[str, Any]] | None
):
    """Toggle visibility of View By and Period menus based on current page.

    - On /timeseries: hide viewby, show period
    - On other pages: show viewby, hide period
    """
    if pathname == get_relative_path("/timeseries"):
        period_style: dict[str, Any] = {}
        if budget_id and options:
            budget_type = next(
                (opt.get("type") for opt in options if opt.get("value") == budget_id),
                None,
            )
            if budget_type == "LAW":
                period_style = {
                    "cursor": "not-allowed",
                }
        return {"display": "none"}, period_style
    return {}, {"display": "none"}


@callback(
    Output("menu-period", "disabled"),
    Input("store-budget-id", "data"),
    State("store-budget-options", "data"),
)
def toggle_period_menu_disabled(
    budget_id: int | None, options: list[dict[str, Any]] | None
) -> bool:
    # Disable the period menu for LAW budgets where quarter selection does not apply.
    if not budget_id or not options:
        return False
    budget_type = next((opt.get("type") for opt in options if opt.get("value") == budget_id), None)
    return budget_type == "LAW"


# Hide the treemap loading spinner once the graph becomes visible.
# Uses a named ClientsideFunction so the inline string parser in Dash 4 is not involved.
clientside_callback(
    ClientsideFunction(namespace="clientside", function_name="hideTreemapSpinner"),
    Output("dummy-output", "lang"),
    Input("treemap-graph", "figure", allow_optional=True),
    prevent_initial_call=True,
)

# Show treemap spinner when any filter store changes (before the Python callback completes).
clientside_callback(
    ClientsideFunction(namespace="clientside", function_name="showTreemapSpinner"),
    Output("dummy-output", "dir"),
    Input("store-budget-id", "data"),
    Input("store-viewby", "data"),
    Input("store-spending-type", "data"),
    Input("store-unit", "data"),
    Input("store-language", "data"),
    prevent_initial_call=True,
)

# Show timeseries spinner when any filter store changes.
clientside_callback(
    ClientsideFunction(namespace="clientside", function_name="showTimeseriesSpinner"),
    Output("dummy-output", "tabIndex"),
    Input("store-budget-id", "data"),
    Input("store-period", "data"),
    Input("store-spending-type", "data"),
    Input("store-unit", "data"),
    prevent_initial_call=True,
)

# Hide the timeseries spinner once the graph becomes visible.
clientside_callback(
    ClientsideFunction(namespace="clientside", function_name="hideTimeseriesSpinner"),
    Output("dummy-output", "accessKey"),
    Input("timeseries-graph", "figure", allow_optional=True),
    prevent_initial_call=True,
)

# Clientside callback to constrain treemap text within tile boundaries via SVG textLength.
clientside_callback(
    ClientsideFunction(namespace="clientside", function_name="applyTreemapTextInset"),
    Output("dummy-output", "className"),
    Input("treemap-graph", "figure", allow_optional=True),
)

# Clientside callback to handle URL focus parameter and click simulation
clientside_callback(
    ClientsideFunction(namespace="clientside", function_name="findAndClickSlice"),
    Output("dummy-output", "children"),
    Input("url", "search"),
    Input("treemap-graph", "figure", allow_optional=True),
    State("store-treemap-node-map", "data"),
    State("store-language", "data"),
    prevent_initial_call=True,
)

# Clientside share: build URL with current filters and selected id, copy to clipboard
clientside_callback(
    ClientsideFunction(namespace="clientside", function_name="copyShareLink"),
    Output("dummy-output", "title"),
    Input("btn-share-link", "n_clicks"),
    State("url", "pathname"),
    State("store-budget-id", "data"),
    State("store-viewby", "data"),
    State("store-spending-type", "data"),
    State("store-unit", "data"),
    State("store-selected-id", "data"),
    State("store-treemap-node-map", "data"),
    prevent_initial_call=True,
)

# Clientside callback for downloading the current graph as PNG image.
# Uses Plotly's client-side export directly from the browser (no Kaleido required).
# Handles both treemap and timeseries pages based on pathname.
clientside_callback(
    ClientsideFunction(namespace="clientside", function_name="downloadPlotImage"),
    Output("store-download-status", "data"),
    Input("btn-download-image", "n_clicks"),
    State("url", "pathname"),
    State("store-budget-id", "data"),
    State("store-budget-options", "data"),
    State("store-unit", "data"),
    State("store-spending-type", "data"),
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


@callback(
    Output("btn-switch-data-language", "children"),
    Output("store-language", "data", allow_duplicate=True),
    Input("btn-switch-data-language", "n_clicks"),
    State("store-language", "data"),
    prevent_initial_call=True,
)
def toggle_language(n_clicks: int | None, current_lang: str | None):
    """Toggle the language between RU and EN.

    - Button text shows the next language (handled by a separate callback).
    """
    if not n_clicks:
        raise PreventUpdate

    new_lang = "EN" if (current_lang or "RU") == "RU" else "RU"
    btn_label = "RU" if new_lang == "EN" else "EN"

    return [html.Span(btn_label, className="btn-label")], new_lang


# View-by selection (pattern-matched, single callback)
@callback(
    Output("store-viewby", "data"),
    Input({"type": "viewby-item", "value": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def select_viewby(_clicks):
    ctx = callback_context
    if not ctx.triggered:
        raise PreventUpdate
    trig = getattr(ctx, "triggered_id", None)
    if isinstance(trig, dict) and trig.get("type") == "viewby-item":
        return trig.get("value")
    raise PreventUpdate


# Period selection (pattern-matched, for timeseries page)
@callback(
    Output("store-period", "data"),
    Input({"type": "period-item", "value": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def select_period(_clicks):
    ctx = callback_context
    if not ctx.triggered:
        raise PreventUpdate
    trig = getattr(ctx, "triggered_id", None)
    if isinstance(trig, dict) and trig.get("type") == "period-item":
        return trig.get("value")
    raise PreventUpdate


# Spending type selection (pattern-matched)
@callback(
    Output("store-spending-type", "data"),
    Input({"type": "spending-type-item", "value": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def select_spending_type(_clicks):
    ctx = callback_context
    if not ctx.triggered:
        raise PreventUpdate
    trig = getattr(ctx, "triggered_id", None)
    if isinstance(trig, dict) and trig.get("type") == "spending-type-item":
        return trig.get("value")
    raise PreventUpdate


# Unit selection (pattern-matched)
@callback(
    Output("store-unit", "data"),
    Input({"type": "unit-item", "value": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def select_unit(_clicks):
    ctx = callback_context
    if not ctx.triggered:
        raise PreventUpdate
    trig = getattr(ctx, "triggered_id", None)
    if isinstance(trig, dict) and trig.get("type") == "unit-item":
        return trig.get("value")
    raise PreventUpdate


@callback(
    Output("store-budget-options", "data"),
    Output("store-budget-id", "data"),
    Output("menu-budget", "children"),
    Input("url", "pathname"),  # fire once on load
    State("url", "search"),  # get URL search params to check for budget_id
    prevent_initial_call=False,
)
def init_budgets(_, url_search: str | None):
    # Fetch once and include budget type for downstream UI logic.
    options = [
        {"label": b["original_identifier"], "value": b["id"], "type": b["type"]}
        for b in fetch_budgets_for_dropdown()
    ]
    # Build menu items with pattern ids
    items = [
        dbc.DropdownMenuItem(
            html.Span(opt["label"], title=opt["label"]),
            id={"type": "budget-item", "value": opt["value"]},
        )
        for opt in options
    ]

    # Check if budget_id is in URL params, otherwise use default
    default_value = options[0]["value"] if options else None
    if url_search:
        from urllib.parse import parse_qs, unquote_plus

        params = parse_qs(url_search.replace("?", ""))
        budget_id_raw = params.get("budget_id", [None])[0]
        if budget_id_raw:
            budget_id_raw = unquote_plus(budget_id_raw).strip()
            if budget_id_raw.isdigit():
                # Verify the budget_id exists in options
                budget_id_int = int(budget_id_raw)
                if any(opt["value"] == budget_id_int for opt in options):
                    default_value = budget_id_int

    return options, default_value, items


@callback(
    Output("store-budget-id", "data", allow_duplicate=True),
    Output("store-viewby", "data", allow_duplicate=True),
    Output("store-spending-type", "data", allow_duplicate=True),
    Output("store-unit", "data", allow_duplicate=True),
    Output("store-language", "data", allow_duplicate=True),
    Input("url", "search"),
    prevent_initial_call="initial_duplicate",
)
def apply_filters_from_url(url_search: str | None):
    """Apply filters from URL query params on load and when the URL changes.

    Recognized params: budget_id, viewby, spending_type, unit.
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
        unit = first("unit")
        language = first("language")

        budget_id = int(budget_id_raw) if budget_id_raw and budget_id_raw.isdigit() else None

        # If none provided, avoid overwriting by returning PreventUpdate
        outputs: list[Any] = []
        outputs.append(budget_id if budget_id is not None else no_update)
        outputs.append(viewby if viewby else no_update)
        outputs.append(spending_type if spending_type else no_update)
        outputs.append(unit if unit else no_update)
        outputs.append(language if language else no_update)
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
    ctx = callback_context

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


_viewby_labels = {v: l for l, v in VIEWBY_OPTIONS}
_spending_type_labels = {v: l for l, v in SPENDING_TYPE_OPTIONS}
_unit_labels = {v: l for l, v in UNIT_OPTIONS}
_period_labels = {v: l for l, v in PERIOD_OPTIONS}


def _item_span(label: str, selected: bool) -> html.Span:
    style = {"fontWeight": "bold"} if selected else {}
    return html.Span(label, title=label, style=style)


@callback(
    Output({"type": "viewby-item", "value": ALL}, "children"),
    Input("store-viewby", "data"),
    State({"type": "viewby-item", "value": ALL}, "id"),
)
def highlight_viewby(current, ids):
    return [_item_span(_viewby_labels[item["value"]], item["value"] == current) for item in ids]


@callback(
    Output({"type": "spending-type-item", "value": ALL}, "children"),
    Input("store-spending-type", "data"),
    State({"type": "spending-type-item", "value": ALL}, "id"),
)
def highlight_spending_type(current, ids):
    return [
        _item_span(_spending_type_labels[item["value"]], item["value"] == current) for item in ids
    ]


@callback(
    Output({"type": "unit-item", "value": ALL}, "children"),
    Input("store-unit", "data"),
    State({"type": "unit-item", "value": ALL}, "id"),
)
def highlight_unit(current, ids):
    return [_item_span(_unit_labels[item["value"]], item["value"] == current) for item in ids]


@callback(
    Output({"type": "period-item", "value": ALL}, "children"),
    Input("store-period", "data"),
    State({"type": "period-item", "value": ALL}, "id"),
)
def highlight_period(current, ids):
    return [_item_span(_period_labels[item["value"]], item["value"] == current) for item in ids]


@callback(
    Output({"type": "budget-item", "value": ALL}, "children"),
    Input("store-budget-id", "data"),
    State({"type": "budget-item", "value": ALL}, "id"),
    State("store-budget-options", "data"),
)
def highlight_budget(current, ids, options):
    if not options:
        raise PreventUpdate
    label_map = {opt["value"]: opt["label"] for opt in options}
    return [_item_span(label_map[item["value"]], item["value"] == current) for item in ids]


@callback(
    Output("menu-budget", "label"),
    Input("store-budget-id", "data"),
    State("store-budget-options", "data"),
)
def show_selected_budget_label(budget_id: int | None, options: list[dict[str, Any]] | None) -> str:
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
    Output("menu-unit", "label"),
    Output("menu-period", "label"),
    Input("store-viewby", "data"),
    Input("store-spending-type", "data"),
    Input("store-unit", "data"),
    Input("store-period", "data"),
)
def update_menu_labels(
    viewby: str | None, spending_type: str | None, unit: str | None, period: str | None
):
    return (
        viewby_map.get(viewby or "", "View by"),
        spending_type_map.get(spending_type or "", "Spending type"),
        unit_map.get(unit or "", "Unit"),  # type: ignore
        period_map.get(period or "", "Period"),
    )


@callback(
    Output("timeseries-resize-interval", "disabled"),
    Input("url", "pathname"),
)
def toggle_resize_interval(pathname: str | None) -> bool:
    return pathname != "/timeseries"


if __name__ == "__main__":
    app.run(debug=True, use_reloader=False)
