from dash import dcc, html, register_page

register_page(__name__, path="/", title="Russian Federal Budget Dashboard - Treemap")

# Graph config kept simple and explicit for production clarity
TREEMAP_CONFIG = dcc.Graph.Config(
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

    return html.Div(
        className="plot-page",
        children=[
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
