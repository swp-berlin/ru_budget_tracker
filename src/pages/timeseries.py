import dash_bootstrap_components as dbc
from dash import dcc, html, register_page

from utils.definitions import unit_config, period_config, spending_type_config

register_page(__name__, path="/timeseries", title="Russian Federal Budget Dashboard - Time Series")

# Graph config kept simple and explicit for production clarity
TIMESERIES_CONFIG = dcc.Graph.Config(
    displayModeBar=False,
    displaylogo=False,
    responsive=True,
)


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

    period_items = [
        dbc.DropdownMenuItem(
            html.Span(label, title=label),
            id={"type": "period-item", "value": value},
        )
        for label, value in period_config.options
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
    return html.Div(
        className="plot-page",
        children=[
            # Hidden treemap graph keeps cross-page callbacks satisfied.
            dcc.Graph(
                id="treemap-graph", style={"display": "none", "height": "100%", "width": "100%"}
            ),
            # Loading spinner overlay, hidden once the graph is ready.
            html.Div(
                html.Div(className="treemap-spinner"),
                id="timeseries-spinner",
                style={
                    "position": "absolute",
                    "top": "50%",
                    "left": "50%",
                    "transform": "translate(-50%, -50%)",
                    "zIndex": 10,
                },
            ),
            dcc.Graph(
                id="timeseries-graph",
                config=TIMESERIES_CONFIG,
                style={"visibility": "hidden", "height": "100%", "width": "100%"},
            ),
        ],
        style={"width": "100%", "height": "100%", "position": "relative"},
    )
