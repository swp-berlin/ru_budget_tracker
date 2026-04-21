"""App-level callbacks (toolbar, filters, menus, spinners, share/download)."""

from typing import Any
from urllib.parse import parse_qs, unquote_plus

import dash_bootstrap_components as dbc
from dash import (
    ALL,
    ClientsideFunction,
    Input,
    Output,
    State,
    callback,
    callback_context,
    clientside_callback,
    html,
    no_update,
    get_asset_url,
    get_relative_path,
)
from dash.exceptions import PreventUpdate

from utils.fetch_treemap import fetch_budgets_for_dropdown
from utils.definitions import (
    unit_config,
    spending_type_config,
    viewby_config,
    period_config,
)

# Dropdown labels differ from chart-title maps for unit and spending type,
# so derive them separately from the options lists.
_spending_type_labels = {v: l for l, v in spending_type_config.options}
_unit_labels = {v: l for l, v in unit_config.options}


def _item_span(label: str, selected: bool) -> html.Span:
    style = {"fontWeight": "bold"} if selected else {}
    return html.Span(label, title=label, style=style)


# --- Navigation ---


@callback(
    Output("btn-switch-graphs", "href"),
    Output("btn-switch-graphs", "children"),
    Output("btn-switch-graphs", "title"),
    Input("url", "pathname"),
    Input("store-budget-id", "data"),
)
def switch_graphs(pathname: str | None, budget_id: int | None):
    """Swap destination, icon, and label based on current page."""
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
    """Toggle visibility of View By and Period menus based on current page."""
    if pathname == get_relative_path("/timeseries"):
        period_style: dict[str, Any] = {}
        if budget_id and options:
            budget_type = next(
                (opt.get("type") for opt in options if opt.get("value") == budget_id),
                None,
            )
            if budget_type == "LAW":
                period_style = {"cursor": "not-allowed"}
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
    """Disable the period menu for LAW budgets where quarter selection does not apply."""
    if not budget_id or not options:
        return False
    budget_type = next((opt.get("type") for opt in options if opt.get("value") == budget_id), None)
    return budget_type == "LAW"


@callback(
    Output("timeseries-resize-interval", "disabled"),
    Input("url", "pathname"),
)
def toggle_resize_interval(pathname: str | None) -> bool:
    return pathname != "/timeseries"


# --- Budget ---


@callback(
    Output("store-budget-options", "data"),
    Output("store-budget-id", "data"),
    Output("menu-budget", "children"),
    Input("url", "pathname"),  # fire once on load
    State("url", "search"),
    prevent_initial_call=False,
)
def init_budgets(_, url_search: str | None):
    """Fetch available budgets, build menu items, and resolve the initially selected budget."""
    options = [
        {"label": b["original_identifier"], "value": b["id"], "type": b["type"]}
        for b in fetch_budgets_for_dropdown()
    ]
    items = [
        dbc.DropdownMenuItem(
            html.Span(opt["label"], title=opt["label"]),
            id={"type": "budget-item", "value": opt["value"]},
        )
        for opt in options
    ]

    default_value = options[0]["value"] if options else None
    if url_search:
        params = parse_qs(url_search.replace("?", ""))
        budget_id_raw = params.get("budget_id", [None])[0]
        if budget_id_raw:
            budget_id_raw = unquote_plus(budget_id_raw).strip()
            if budget_id_raw.isdigit():
                budget_id_int = int(budget_id_raw)
                if any(opt["value"] == budget_id_int for opt in options):
                    default_value = budget_id_int

    return options, default_value, items


@callback(
    Output("store-budget-id", "data", allow_duplicate=True),
    Input("store-budget-options", "data"),
    Input({"type": "budget-item", "value": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def select_budget_dynamic(options, clicks):
    """Update selected budget_id when a budget menu item is clicked."""
    ctx = callback_context
    if not ctx.triggered:
        raise PreventUpdate
    trig = getattr(ctx, "triggered_id", None)
    if not isinstance(trig, dict) or trig.get("type") != "budget-item":
        raise PreventUpdate
    selected_value = trig.get("value")
    if selected_value is None:
        raise PreventUpdate
    return selected_value


# --- Filter stores from URL ---


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

    Recognized params: budget_id, viewby, spending_type, unit, language.
    Missing params leave the current store values unchanged (no_update).
    """
    if not url_search:
        raise PreventUpdate
    try:
        params = parse_qs(url_search.replace("?", ""))

        def first(key: str):
            vals = params.get(key)
            return unquote_plus(vals[0]).strip() if vals else None

        budget_id_raw = first("budget_id")
        viewby = first("viewby")
        spending_type = first("spending_type")
        unit = first("unit")
        language = first("language")

        budget_id = int(budget_id_raw) if budget_id_raw and budget_id_raw.isdigit() else None

        return (
            budget_id if budget_id is not None else no_update,
            viewby if viewby else no_update,
            spending_type if spending_type else no_update,
            unit if unit else no_update,
            language if language else no_update,
        )
    except Exception:
        raise PreventUpdate


# --- Filter selections (pattern-matched menu items) ---


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


# --- Menu label updates ---


@callback(
    Output("menu-budget", "label"),
    Input("store-budget-id", "data"),
    State("store-budget-options", "data"),
)
def show_selected_budget_label(budget_id: int | None, options: list[dict[str, Any]] | None) -> str:
    if not options or budget_id is None:
        return "Budget"
    for opt in options:
        if opt.get("value") == budget_id:
            return opt.get("label", "Budget")
    return "Budget"


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
        viewby_config.map.get(viewby or "", "View by"),
        spending_type_config.map.get(spending_type or "", "Spending type"),
        unit_config.map.get(unit or "", "Unit"),  # type: ignore
        period_config.map.get(period or "", "Period"),
    )


# --- Menu item highlight ---


@callback(
    Output({"type": "viewby-item", "value": ALL}, "children"),
    Input("store-viewby", "data"),
    State({"type": "viewby-item", "value": ALL}, "id"),
)
def highlight_viewby(current, ids):
    return [_item_span(viewby_config.map[item["value"]], item["value"] == current) for item in ids]


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
    return [_item_span(period_config.map[item["value"]], item["value"] == current) for item in ids]


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


# --- Language toggle ---


@callback(
    Output("btn-switch-data-language", "children"),
    Output("store-language", "data", allow_duplicate=True),
    Input("btn-switch-data-language", "n_clicks"),
    State("store-language", "data"),
    prevent_initial_call=True,
)
def toggle_language(n_clicks: int | None, current_lang: str | None):
    """Toggle the language between RU and EN."""
    if not n_clicks:
        raise PreventUpdate
    new_lang = "EN" if (current_lang or "RU") == "RU" else "RU"
    btn_label = "RU" if new_lang == "EN" else "EN"
    return [html.Span(btn_label, className="btn-label")], new_lang


# --- Share ---


@callback(
    Output("share-toast", "is_open"),
    Input("btn-share-link", "n_clicks"),
    prevent_initial_call=True,
)
def show_share_toast(n_clicks: int | None) -> bool:
    if not n_clicks:
        raise PreventUpdate
    return True


# --- Clientside callbacks (spinners, treemap text, share link, image download) ---

# Hide the treemap loading spinner once the graph becomes visible.
clientside_callback(
    ClientsideFunction(namespace="clientside", function_name="hideTreemapSpinner"),
    Output("dummy-output", "lang"),
    Input("treemap-graph", "figure", allow_optional=True),
    prevent_initial_call=True,
)

# Also hide the treemap spinner when a warning toast opens (callback error path).
clientside_callback(
    ClientsideFunction(namespace="clientside", function_name="hideTreemapSpinnerOnToast"),
    Output("dummy-output", "hidden"),
    Input("warning-toast", "is_open"),
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
    Input("store-selected-id", "data"),
    Input("store-language", "data"),
    prevent_initial_call=True,
)

# Hide the timeseries spinner once the graph becomes visible.
clientside_callback(
    ClientsideFunction(namespace="clientside", function_name="hideTimeseriesSpinner"),
    Output("dummy-output", "accessKey"),
    Input("timeseries-graph", "figure", allow_optional=True),
    prevent_initial_call=True,
)

# Constrain treemap text within tile boundaries via SVG textLength.
clientside_callback(
    ClientsideFunction(namespace="clientside", function_name="applyTreemapTextInset"),
    Output("dummy-output", "className"),
    Input("treemap-graph", "figure", allow_optional=True),
)

# Restore treemap zoom to the previously selected node after a figure update.
# Uses Plotly.restyle so the MutationObserver in applyTreemapTextInset keeps working.
clientside_callback(
    ClientsideFunction(namespace="clientside", function_name="restoreTreemapZoom"),
    Output("dummy-restore-zoom", "children"),
    Input("treemap-graph", "figure", allow_optional=True),
    State("store-selected-id", "data"),
)

# Handle URL focus parameter and click simulation.
clientside_callback(
    ClientsideFunction(namespace="clientside", function_name="findAndClickSlice"),
    Output("dummy-output", "children"),
    Input("url", "search"),
    Input("treemap-graph", "figure", allow_optional=True),
    State("store-treemap-node-map", "data"),
    State("store-language", "data"),
    prevent_initial_call=True,
)

# Build URL with current filters and selected id, copy to clipboard.
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
    State("store-treemap-node-map", "data"),  # compact map: {dim_id: {ru: path, en: path}}
    prevent_initial_call=True,
)

# Download the current graph as PNG using Plotly's client-side export.
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
