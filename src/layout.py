"""Layout definitions for the Dash app (toolbar, stores, page container)."""

import dash_bootstrap_components as dbc
from dash import dcc, html, page_container, get_asset_url, get_relative_path

from utils.definitions import (
    unit_config,
    period_config,
    spending_type_config,
    viewby_config,
)

viewby_items = [
    dbc.DropdownMenuItem(
        html.Span(label, title=label),
        id={"type": "viewby-item", "value": value},
    )
    for label, value in viewby_config.options
]

spending_type_items = [
    dbc.DropdownMenuItem(
        html.Span(label, title=label),
        id={"type": "spending-type-item", "value": value},
    )
    for label, value in spending_type_config.options
]

unit_items = [
    dbc.DropdownMenuItem(
        html.Span(label, title=label),
        id={"type": "unit-item", "value": value},
    )
    for label, value in unit_config.options
]

period_items = [
    dbc.DropdownMenuItem(
        html.Span(label, title=label),
        id={"type": "period-item", "value": value},
    )
    for label, value in period_config.options
]

toolbar = html.Div(
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
        dcc.Store(id="store-previous-path"),
        # Timeseries page: tick metadata and window width for responsive tick labels
        dcc.Store(id="store-timeseries-ticks"),
        dcc.Store(id="store-window-width", data=1280),
        dcc.Interval(id="timeseries-resize-interval", interval=300, disabled=True),
        # Location component to access URL parameters
        dcc.Location(id="url"),
        # Dummy div target for clientside callbacks (requires an Output but is invisible).
        html.Div(id="dummy-output", style={"display": "none"}),
        html.Div(id="dummy-restore-zoom", style={"display": "none"}),
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
            html.Div(id="timeseries-title"),
            html.Div(page_container, id="pages-wrapper"),
        ],
    )


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
