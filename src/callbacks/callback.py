"""App-level callbacks (toolbar, filters, menus, spinners, share/download)."""

from typing import Any
from urllib.parse import unquote_plus, parse_qs, urlencode

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
    BudgetTypeLiteral,
    PeriodTypeLiteral,
    LanguageTypeLiteral,
    ViewByDimensionTypeLiteral,
    UnitTypeLiteral,
    SpendingTypeLiteral,
)

# Dropdown labels differ from chart-title maps for unit and spending type,
# so derive them separately from the options lists.
_spending_type_labels = {v: l for l, v in spending_type_config.options}
_unit_labels = {v: l for l, v in unit_config.options}


def _triggered_value(item_type: str):
    """Return the `value` from a pattern-matched triggered component, or raise PreventUpdate."""
    trig = getattr(callback_context, "triggered_id", None)
    if isinstance(trig, dict) and trig.get("type") == item_type:
        return trig.get("value")
    raise PreventUpdate


def _item_span(label: str, selected: bool) -> html.Span:
    style = {"fontWeight": "bold"} if selected else {}
    return html.Span(label, title=label, style=style)


def _parse_search(search: str | None) -> dict:
    return parse_qs((search or "").lstrip("?"))


def _update_search_param(current_search: str | None, key: str, value: str) -> str:
    """Return a new URL search string with one key replaced, preserving all other params."""
    params = _parse_search(current_search)
    params[key] = [value]
    return "?" + urlencode(params, doseq=True)


def _focus_from_compact_map(selected_id: str | None, compact_node_map: dict | None) -> str | None:
    """Encode the semantic node behind a transient Plotly id for URL sharing."""
    if not selected_id or not compact_node_map:
        return None
    entry = compact_node_map.get(str(selected_id))
    if not isinstance(entry, dict):
        return None
    leaf = str(entry.get("leaf", ""))
    if not leaf:
        return None
    context = entry.get("ctx", []) or []
    return ",".join([str(value) for value in context] + [leaf])


def _build_switch_query(
    current_search: str | None,
    *,
    destination: str,
    budget_id: int | None,
    viewby: str | None,
    period: str | None,
    spending_type: str | None,
    unit: str | None,
    language: str | None,
    selected_id: str | None,
    compact_node_map: dict | None,
) -> str:
    """Serialize the current shared stores for a Treemap/Time Series switch.

    The entry URL initializes the stores once. After that, store values are
    authoritative so a page switch cannot resurrect stale URL parameters.
    """
    params = _parse_search(current_search)
    shared_values = {
        "budget_id": budget_id,
        "spending_type": spending_type,
        "unit": unit,
        "language": language,
    }
    for key, value in shared_values.items():
        if value is not None:
            params[key] = [str(value)]

    focus = _focus_from_compact_map(selected_id, compact_node_map)
    if focus:
        params["focus"] = [focus]
    elif selected_id:
        # A selected Plotly id without a semantic match is stale. Falling back
        # to the root must also remove a stale focus from the destination URL.
        params.pop("focus", None)

    if destination == "treemap":
        params.pop("period", None)
        if viewby is not None:
            params["viewby"] = [str(viewby)]
    else:
        params.pop("viewby", None)
        if period is not None:
            params["period"] = [str(period)]

    return urlencode(params, doseq=True)


# --- Navigation ---


@callback(
    Output("store-previous-path", "data"),
    Input("url", "pathname"),
)
def track_previous_path(pathname: str | None):
    """Remember the last non-about pathname so the back button can return to it."""
    if pathname == get_relative_path("/about"):
        raise PreventUpdate
    return pathname


@callback(
    Output("btn-about", "href"),
    Output("btn-about", "children"),
    Output("btn-about", "title"),
    Input("url", "pathname"),
    State("store-previous-path", "data"),
    State("store-budget-id", "data"),
    State("url", "search"),
)
def update_about_button(
    pathname: str | None,
    previous_path: str | None,
    budget_id: int | None,
    current_search: str | None,
):
    """Swap icon and destination for the about/back button based on current page."""
    if pathname == get_relative_path("/about"):
        back_path = previous_path or get_relative_path("/")
        params = _parse_search(current_search)
        if budget_id is not None:
            params["budget_id"] = [str(budget_id)]
        query = "?" + urlencode(params, doseq=True) if params else ""
        return (
            f"{back_path}{query}",
            html.Img(src=get_asset_url("icons/arrow_back.svg"), alt="Back icon"),
            "Go Back",
        )
    return (
        get_relative_path("/about"),
        html.Img(src=get_asset_url("icons/info.svg"), alt="Info icon"),
        "About This Project",
    )


@callback(
    Output("btn-switch-graphs", "href"),
    Output("btn-switch-graphs", "children"),
    Output("btn-switch-graphs", "title"),
    Input("url", "pathname"),
    Input("url", "search"),
    Input("store-budget-id", "data"),
    Input("store-selected-id", "data"),
    Input("store-treemap-node-map", "data"),
    Input("store-viewby", "data"),
    Input("store-period", "data"),
    Input("store-spending-type", "data"),
    Input("store-unit", "data"),
    Input("store-language", "data"),
    prevent_initial_call="initial_duplicate",
)
def switch_graphs(
    url_pathname: str | None,
    current_search: str | None,
    budget_id: int | None,
    selected_id: str | None,
    compact_node_map: dict | None,
    viewby: str | None,
    period: str | None,
    spending_type: str | None,
    unit: str | None,
    language: str | None,
):
    """Swap destination and serialize the authoritative current dashboard state."""
    treemap_path = get_relative_path("/")
    timeseries_path = get_relative_path("/timeseries")

    if url_pathname == timeseries_path:
        query_string = _build_switch_query(
            current_search,
            destination="treemap",
            budget_id=budget_id,
            viewby=viewby,
            period=period,
            spending_type=spending_type,
            unit=unit,
            language=language,
            selected_id=selected_id,
            compact_node_map=compact_node_map,
        )
        href = f"{treemap_path}?{query_string}" if query_string else treemap_path
        return (
            href,
            [
                html.Img(src=get_asset_url("icons/dashboard.svg"), alt="Treemap icon"),
                html.Span("Treemap", className="btn-label"),
            ],
            "Switch to Treemap View",
        )

    query_string = _build_switch_query(
        current_search,
        destination="timeseries",
        budget_id=budget_id,
        viewby=viewby,
        period=period,
        spending_type=spending_type,
        unit=unit,
        language=language,
        selected_id=selected_id,
        compact_node_map=compact_node_map,
    )
    href = f"{timeseries_path}?{query_string}" if query_string else timeseries_path
    return (
        href,
        [
            html.Img(src=get_asset_url("icons/stacked_bar_chart.svg"), alt="Timeseries icon"),
            html.Span("Timeseries", className="btn-label"),
        ],
        "Switch to Time Series View",
    )


@callback(
    Output("menu-viewby", "style"),
    Output("menu-period", "style"),
    Output("menu-period", "disabled"),
    Input("url", "pathname"),
    Input("store-budget-type", "data"),
)
def toggle_viewby_period_menu(pathname: str | None, budget_type: str | None):
    """Toggle visibility/style of View By and Period menus, and disable Period for LAW budgets."""
    is_law = budget_type == "LAW"
    if pathname == get_relative_path("/timeseries"):
        return {"display": "none"}, {"cursor": "not-allowed"} if is_law else {}, is_law
    return {}, {"display": "none"}, False


@callback(
    Output("timeseries-resize-interval", "disabled"),
    Input("url", "pathname"),
)
def toggle_resize_interval(pathname: str | None) -> bool:
    return pathname != get_relative_path("/timeseries")


@callback(
    Output("timeseries-title", "hidden"),
    Input("url", "pathname"),
)
def hide_timeseries_title(pathname: str | None) -> bool:
    """Keep the global Time Series title hidden on every other page."""
    return pathname != get_relative_path("/timeseries")


# --- Budget ---


@callback(
    Output("store-budget-options", "data"),
    Output("store-budget-id", "data"),
    Output("menu-budget", "children"),
    Input("url", "pathname"),  # fire once on load
    State("url", "search"),
    State("store-budget-id", "data"),
    prevent_initial_call=False,
)
def init_budgets(_, url_search: str | None, store_budget_id: int | None):
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

    # On page switches the store is already set — don't overwrite it.
    if store_budget_id is not None:
        return options, no_update, items

    default_value = options[0]["value"] if options else None
    if url_search:
        params = _parse_search(url_search)
        budget_id_raw = params.get("budget_id", [None])[0]
        if budget_id_raw:
            budget_id_raw = unquote_plus(budget_id_raw).strip()
            if budget_id_raw.isdigit():
                budget_id_int = int(budget_id_raw)
                if any(opt["value"] == budget_id_int for opt in options):
                    default_value = budget_id_int

    return options, default_value, items


@callback(
    Output("store-budget-type", "data"),
    Input("store-budget-id", "data"),
    State("store-budget-options", "data"),
)
def update_budget_type(budget_id: int | None, options: list[dict] | None) -> str | None:
    if not budget_id or not options:
        return None
    return next((opt.get("type") for opt in options if opt.get("value") == budget_id), None)


@callback(
    Output("url", "search"),
    Output("store-period", "data", allow_duplicate=True),
    Input("store-budget-type", "data"),
    State("url", "search"),
    State("url", "pathname"),
    prevent_initial_call=True,
)
def update_period_on_budget_update(
    budget_type: BudgetTypeLiteral | None, current_search: str | None, current_pathname: str | None
) -> tuple[str | None, PeriodTypeLiteral | None]:
    if not budget_type:
        raise PreventUpdate
    params = _parse_search(current_search)
    is_timeseries: bool = get_relative_path("/timeseries") == current_pathname

    if is_timeseries and budget_type != "REPORT":
        period: PeriodTypeLiteral = "ALL"
        params["period"] = [period]
        return "?" + urlencode(params, doseq=True), period

    raise PreventUpdate


@callback(
    Output("url", "search", allow_duplicate=True),
    Output("store-budget-id", "data", allow_duplicate=True),
    Output("store-selected-id", "data", allow_duplicate=True),
    Input("store-budget-options", "data"),
    Input({"type": "budget-item", "value": ALL}, "n_clicks"),
    State("url", "search"),
    prevent_initial_call=True,
)
def select_budget_dynamic(options, clicks, current_search):
    """Update budget_id in URL and store when a budget menu item is clicked, clearing focus."""
    ctx = callback_context
    if not ctx.triggered:
        raise PreventUpdate
    trig = getattr(ctx, "triggered_id", None)
    if not isinstance(trig, dict) or trig.get("type") != "budget-item":
        raise PreventUpdate
    selected_value = trig.get("value")
    if selected_value is None:
        raise PreventUpdate
    params = _parse_search(current_search)
    params["budget_id"] = [str(selected_value)]
    params.pop("focus", None)
    return "?" + urlencode(params, doseq=True), selected_value, None


# --- Filter stores from URL ---


@callback(
    Output("store-viewby", "data", allow_duplicate=True),
    Output("store-spending-type", "data", allow_duplicate=True),
    Output("store-unit", "data", allow_duplicate=True),
    Output("store-language", "data", allow_duplicate=True),
    Output("store-period", "data", allow_duplicate=True),
    Input("url", "pathname"),
    State("url", "search"),
    State("store-budget-type", "data"),
    prevent_initial_call="initial_duplicate",
)
def init_filters_from_url(
    url_pathname: str | None, url_search: str | None, budget_type: BudgetTypeLiteral | None
):
    """Initialise filter stores from URL params on page load.

    Fires on pathname changes (page navigation), not on filter changes — those
    write both the URL and the store together via write-through callbacks.
    """
    if not url_search:
        raise PreventUpdate
    if not url_pathname:
        raise PreventUpdate
    is_timeseries: bool = url_pathname == get_relative_path("/timeseries")
    if not budget_type:
        budget_type = "LAW"
    try:
        params = _parse_search(url_search)

        def first(key: str):
            vals = params.get(key)
            return unquote_plus(vals[0]).strip() if vals else None

        viewby: ViewByDimensionTypeLiteral = first("viewby")
        spending_type: SpendingTypeLiteral | None = first("spending_type")
        unit: UnitTypeLiteral | None = first("unit")
        language: LanguageTypeLiteral | None = first("language")
        period: PeriodTypeLiteral | None = first("period")

        if not is_timeseries and budget_type != "REPORT":
            period = "ALL"

        return (
            viewby if viewby else no_update,
            spending_type if spending_type else no_update,
            unit if unit else no_update,
            language if language else no_update,
            period if period else no_update,
        )
    except Exception:
        raise PreventUpdate


# --- Filter selections (pattern-matched menu items) ---


def _make_select_callback(item_type: str, store: str, url_param: str) -> None:
    @callback(
        Output("url", "search", allow_duplicate=True),
        Output(store, "data"),
        Input({"type": item_type, "value": ALL}, "n_clicks"),
        State("url", "search"),
        prevent_initial_call=True,
    )
    def _cb(_clicks, current_search):
        value = _triggered_value(item_type)
        params = _parse_search(current_search)
        params[url_param] = [str(value)]
        return "?" + urlencode(params, doseq=True), value

    _cb.__name__ = f"select_{item_type.replace('-', '_')}"


_make_select_callback("viewby-item", "store-viewby", "viewby")
_make_select_callback("period-item", "store-period", "period")
_make_select_callback("spending-type-item", "store-spending-type", "spending_type")
_make_select_callback("unit-item", "store-unit", "unit")


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
        unit_config.map.get(unit or "", "Unit"),
        period_config.map.get(period or "", "Period"),
    )


# --- Menu item highlight ---


def _make_highlight_callback(item_type: str, store: str, label_map: dict) -> None:
    @callback(
        Output({"type": item_type, "value": ALL}, "children"),
        Input(store, "data"),
        State({"type": item_type, "value": ALL}, "id"),
    )
    def _cb(current, ids):
        return [_item_span(label_map[item["value"]], item["value"] == current) for item in ids]

    _cb.__name__ = f"highlight_{item_type.replace('-', '_')}"


_make_highlight_callback("viewby-item", "store-viewby", viewby_config.map)
_make_highlight_callback("spending-type-item", "store-spending-type", _spending_type_labels)
_make_highlight_callback("unit-item", "store-unit", _unit_labels)
_make_highlight_callback("period-item", "store-period", period_config.map)


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
    Input("store-language", "data"),
)
def update_language_button_label(current_lang: str | None):
    """Keep the language button label in sync with the store (shows the language you'd switch to)."""
    btn_label = "RU" if current_lang == "EN" else "EN"
    return [html.Span(btn_label, className="btn-label")]


@callback(
    Output("url", "search", allow_duplicate=True),
    Output("store-language", "data", allow_duplicate=True),
    Input("btn-switch-data-language", "n_clicks"),
    State("store-language", "data"),
    State("url", "search"),
    prevent_initial_call=True,
)
def toggle_language(n_clicks: int | None, current_lang: str | None, current_search: str | None):
    """Toggle the language in URL and store between RU and EN on button click."""
    new_lang = "EN" if current_lang == "RU" else "RU"
    return _update_search_param(current_search, "language", new_lang), new_lang


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
    Output("dummy-output", "accessKey", allow_duplicate=True),
    Input("timeseries-graph", "figure", allow_optional=True),
    prevent_initial_call=True,
)

# Restore Treemap zoom after either the figure or its remapped selection changes.
clientside_callback(
    ClientsideFunction(namespace="clientside", function_name="restoreTreemapZoom"),
    Output("dummy-restore-zoom", "children"),
    Input("treemap-graph", "figure", allow_optional=True),
    Input("store-selected-id", "data"),
)

# Handle URL focus parameter and click simulation.
clientside_callback(
    ClientsideFunction(namespace="clientside", function_name="findAndClickSlice"),
    Output("dummy-output", "children"),
    Input("url", "search"),
    Input("treemap-graph", "figure", allow_optional=True),
    State("store-treemap-node-map", "data"),
    State("store-language", "data"),
    State("store-budget-id", "data"),
    State("store-viewby", "data"),
    prevent_initial_call=True,
)

# Copy current URL to clipboard, appending focus param from selected treemap node.
clientside_callback(
    ClientsideFunction(namespace="clientside", function_name="copyShareLink"),
    Output("dummy-output", "title"),
    Input("btn-share-link", "n_clicks"),
    State("store-selected-id", "data"),
    State("store-treemap-node-map", "data"),
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
    State("store-period", "data"),
    prevent_initial_call=True,
)


# Disable share/download buttons and filters that don't apply on the about page.
@callback(
    Output("btn-download-image", "disabled"),
    Output("btn-download-csv", "disabled"),
    Output("btn-share-link", "disabled"),
    Output("btn-switch-data-language", "disabled"),
    Output("menu-budget", "disabled"),
    Output("menu-viewby", "disabled"),
    Output("menu-spending-type", "disabled"),
    Output("menu-unit", "disabled"),
    Input("url", "pathname"),
)
def toggle_action_buttons_disabled(pathname: str | None) -> tuple[bool, ...]:
    """Disable buttons and dropdowns that don't apply on the about page."""
    on_about = pathname == get_relative_path("/about")
    return (on_about,) * 8
