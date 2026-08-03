"""Layout definitions for the Dash app (toolbar, stores, page container)."""

import dash_bootstrap_components as dbc
from dash import dcc, html, page_container, get_asset_url, get_relative_path

from utils.definitions import (
    unit_config,
    period_config,
    spending_type_config,
    viewby_config,
)

# Dropdown items for the "View by" menu (e.g. Chapter, Section, Article).
# Pattern-matching ids ({"type": ..., "value": ...}) let a single callback
# handle clicks on any item instead of wiring one callback per option.
viewby_items = [
    dbc.DropdownMenuItem(
        html.Span(label, title=label),
        id={"type": "viewby-item", "value": value},
    )
    for label, value in viewby_config.options
]

# Dropdown items for the "Spending type" menu (e.g. Law vs. Report figures).
spending_type_items = [
    dbc.DropdownMenuItem(
        html.Span(label, title=label),
        id={"type": "spending-type-item", "value": value},
    )
    for label, value in spending_type_config.options
]

# Dropdown items for the "Unit" menu (e.g. Absolute, % of GDP, per capita).
unit_items = [
    dbc.DropdownMenuItem(
        html.Span(label, title=label),
        id={"type": "unit-item", "value": value},
    )
    for label, value in unit_config.options
]

# Dropdown items for the "Period" menu (timeseries page only).
period_items = [
    dbc.DropdownMenuItem(
        html.Span(label, title=label),
        id={"type": "period-item", "value": value},
    )
    for label, value in period_config.options
]

toolbar = html.Div(
    [
        # Store currently selected filter values (these replace dcc.Dropdown.value).
        # dcc.Store components hold state in the browser (not rendered) so it
        # can be shared between callbacks and survive page navigation.
        dcc.Store(id="store-budget-options"),
        dcc.Store(id="store-budget-id"),
        dcc.Store(id="store-budget-type"),
        # Store the treemap selection for cross-page filtering.
        dcc.Store(id="store-selected-id"),
        # Default filter values shown on first load.
        dcc.Store(id="store-viewby", data="CHAPTER"),
        dcc.Store(id="store-period", data="ALL"),
        dcc.Store(id="store-spending-type", data="ALL"),
        dcc.Store(id="store-unit", data="ABSOLUTE"),
        dcc.Store(id="store-language", data="RU"),
        # Store treemap node metadata for cross-page selection context.
        dcc.Store(id="store-treemap-node-map"),
        # Remembers the (viewby, spending_type) that produced store-treemap-node-map, so a
        # real hierarchy change can be detected even if it happened while on another page.
        dcc.Store(id="store-treemap-hierarchy-key"),
        # Store for download status (used by clientside callback, not displayed)
        dcc.Store(id="store-download-status"),
        dcc.Store(id="store-previous-path"),
        # Timeseries page: tick metadata and window width for responsive tick labels
        dcc.Store(id="store-timeseries-ticks"),
        dcc.Store(id="store-window-width", data=1280),
        # Fires periodically while disabled=False to re-check window width
        # after a resize, so timeseries tick labels can be recomputed.
        dcc.Interval(id="timeseries-resize-interval", interval=300, disabled=True),
        # Location component to access URL parameters (drives page routing
        # and lets callbacks read/write query-string filters for sharing).
        dcc.Location(id="url", refresh=False),
        # Dummy div target for clientside callbacks (requires an Output but is invisible).
        html.Div(id="dummy-output", style={"display": "none"}),
        html.Div(id="dummy-restore-zoom", style={"display": "none"}),
        # Top-level toolbar row: a "Filters" mega-menu on the left, action
        # buttons on the right.
        dbc.Stack(
            [
                html.Div(
                    [
                        # Nested dropdown: clicking "Filters" reveals a submenu
                        # of the individual filter menus below.
                        dbc.DropdownMenu(
                            label="Filters",
                            id="menu-filters",
                            children=[
                                # Budget dataset menu
                                dbc.DropdownMenu(
                                    label="Budget",
                                    children=[],  # will be set by callback
                                    id="menu-budget",
                                    direction="down",
                                    class_name="scroll-menu",
                                ),
                                # View-by menu (shown on treemap, hidden on timeseries)
                                dbc.DropdownMenu(
                                    label="View by",
                                    children=viewby_items,
                                    id="menu-viewby",
                                    direction="down",
                                    style={},  # controlled by callback
                                ),
                                # Period menu (for timeseries, hidden on treemap)
                                dbc.DropdownMenu(
                                    label="Period",
                                    children=period_items,
                                    id="menu-period",
                                    direction="down",
                                    style={"display": "none"},  # controlled by callback
                                ),
                                # Spending type menu
                                dbc.DropdownMenu(
                                    label="Spending type",
                                    children=spending_type_items,
                                    id="menu-spending-type",
                                    direction="down",
                                ),
                                # Unit menu
                                dbc.DropdownMenu(
                                    label="Unit",
                                    children=unit_items,
                                    id="menu-unit",
                                    direction="down",
                                ),
                            ],
                        ),
                        # Stack for action buttons on the right
                        dbc.Stack(
                            [
                                # Button to switch to the time series view
                                dbc.Button(
                                    [
                                        html.Img(
                                            src=get_asset_url("icons/stacked_bar_chart.svg"),
                                        ),
                                        html.Span("Timeseries", className="btn-label"),
                                    ],
                                    id="btn-switch-graphs",
                                    title="Switch to Time Series View",
                                    href=get_relative_path("/timeseries"),
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
                                # Toast for data warnings (e.g. missing GDP/PPP data)
                                dbc.Toast(
                                    id="warning-toast",
                                    header="Data unavailable",
                                    children="",
                                    is_open=False,
                                    duration=6000,
                                    dismissable=True,
                                    icon="warning",
                                    style={
                                        "position": "fixed",
                                        "bottom": 20,
                                        "left": "50%",
                                        "transform": "translateX(-50%)",
                                        "zIndex": 1060,
                                        "minWidth": "300px",
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
                                # One Download component per page: the callback for
                                # whichever page is active triggers its own target.
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
        # Divider between the toolbar and the page content below it.
        dbc.Row(html.Hr(style={"margin": "0"})),
    ]
)


def serve_layout():
    """Serve the layout as a function to defer component evaluation.

    This ensures callbacks in pages can reference stores defined here.
    """
    return html.Div(
        id="app-layout",
        children=[
            toolbar,
            # Populated by a callback with the current page's title
            # (e.g. selected budget/period) when on the timeseries page.
            html.Div(
                id="timeseries-title",
                style={"marginTop": "0.5rem", "marginBottom": "0.5rem"},
            ),
            # page_container renders whichever page matches the current URL.
            html.Div(page_container, id="pages-wrapper"),
        ],
    )


# Dash validates that every callback's Input/Output/State ids exist somewhere
# in the app layout. Since serve_layout() only renders one page's components
# at a time, this static layout lists components from ALL pages so callbacks
# targeting other pages don't fail validation. It is never rendered to users.
validation_layout = html.Div(
    children=[
        toolbar,
        page_container,
        # Include page-specific components for callback validation
        html.Div(id="dummy-restore-zoom", style={"display": "none"}),
        dcc.Store(id="store-selected-id"),
        dcc.Store(id="store-treemap-node-map"),
        dcc.Graph(id="timeseries-graph"),
        dcc.Graph(id="treemap-graph"),
        dcc.Download(id="download-timeseries-data"),
        html.Div(id="timeseries-spinner"),
        html.Div(id="timeseries-title"),
    ]
)
