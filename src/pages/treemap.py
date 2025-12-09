from typing import Any
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
    html,
    register_page,
)

from models import ViewByDimensionTypeLiteral
from utils import TreemapTransformer, TremapDataFetcher, fetch_budgets
from utils.definitions import (
    LanguageTypeLiteral,
    SpendingScopeLiteral,
    SpendingTypeLiteral,
)
from utils.calculate import Calculator
from utils.helper import add_breaks

import logging

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

register_page(__name__, path="/")

TREEMAP_CONFIG = dcc.Graph.Config(
    displayModeBar=False,
    displaylogo=False,
    responsive=True,
)


def fetch_treemap_data(
    budget_id: int | None = None,
    spending_type: SpendingTypeLiteral = "ALL",
    spending_scope: SpendingScopeLiteral = "ABSOLUTE",
    character_limit: int = 30,
) -> tuple[list[str], list[str], list[float], list[str]]:
    """
    Fetch treemap data based on the provided filters.

    Args:
        budget_id (int | None): The budget dataset ID to filter by.
        viewby (ViewByDimensionTypeLiteral): The dimension to view by.
        spending_type (SpendingTypeLiteral): The type of spending to filter by.
        spending_scope (SpendingScopeLiteral): The scope of spending to filter by.

    Returns:
        list[dict[str, Any]]: The fetched treemap data.
    """
    data_fetcher = TremapDataFetcher()
    dimensions, programs, sum_mapping = data_fetcher.fetch_data(
        budget_id=budget_id,
        spending_type=spending_type,
        spending_scope=spending_scope,
    )
    transformer = TreemapTransformer()
    labels, parents, values, metadata = transformer.transform_data(
        dimensions, programs, sum_mapping, translated_names=False
    )
    calculator = Calculator(spending_scope=spending_scope)
    values = [calculator.calculate(value) if value is not None else 0.0 for value in values]
    labels = [add_breaks(label, interval=character_limit) for label in labels]
    parents = [add_breaks(parent, interval=character_limit) for parent in parents]
    return labels, parents, values, metadata


def generate_figure(
    labels: list[str],
    parents: list[str],
    values: list[float],
    metadata: list[str],
    viewby: ViewByDimensionTypeLiteral = "MINISTRY",
    language: LanguageTypeLiteral = "EN",
) -> go.Figure:
    fig = px.treemap(
        names=labels,
        parents=parents,
        values=values,
        hover_data={"level": metadata},
    )
    fig.update_layout(margin=dict(t=50, b=10, l=25, r=25))
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
    # Load budget data from database to populate dropdown options
    budgets = fetch_budgets()

    # Create dropdown options from budget data
    # Using name_translated for display label and type for value
    budget_options = []
    for budget in budgets:
        budget_options.append(
            {
                "label": budget["name_translated"]
                or budget["name"],  # Use translated name if available, fallback to name
                "value": budget["id"],  # Use budget type as the value
            }
        )
    return html.Div(
        [
            # dcc.Location is used to read the URL from the browser's address bar.
            # Its 'search' property (the query string) is used to get the 'focus' parameter.
            dcc.Location(id="url"),
            # This dummy div is the target for our clientside callback. It's required for the
            # callback to have an Output, but it doesn't need to be visible.
            html.Div(id="dummy-treemap-output", style={"display": "none"}),
            # Add Buttons and dropdowns for filtering by budget type
            html.Div(
                [
                    html.Div(
                        [
                            dcc.Dropdown(
                                id="budget-dataset-dropdown",
                                options=budget_options,
                                clearable=False,
                                value=budget_options[0]["value"] if budget_options else None,
                                placeholder=budget_options[0]["label"]
                                if budget_options
                                else "Select Budget",
                                searchable=True,
                                style={"width": "100px"},
                            ),
                            dcc.Dropdown(
                                id="viewby-dropdown",
                                options=[
                                    {"label": "Ministry", "value": "MINISTRY"},
                                    {"label": "Chapter", "value": "CHAPTER"},
                                    {"label": "Program", "value": "PROGRAM"},
                                ],
                                clearable=False,
                                value="MINISTRY",
                                placeholder="Ministry",
                                style={"width": "150px"},
                            ),
                            dcc.Dropdown(
                                id="spending-type-dropdown",
                                options=[
                                    {"label": "All", "value": "ALL"},
                                    {"label": "Military Only", "value": "MILITARY"},
                                ],
                                clearable=False,
                                placeholder="All",
                                value="ALL",
                                style={"width": "150px"},
                            ),
                            dcc.Dropdown(
                                id="spending-scope-dropdown",
                                options=[
                                    {"label": "Billion RUB", "value": "ABSOLUTE"},
                                    {"label": "% full-year GDP", "value": "PERCENT_GDP_FULL_YEAR"},
                                    {
                                        "label": "% year-to-year GDP",
                                        "value": "PERCENT_GDP_YEAR_TO_YEAR",
                                    },
                                    {
                                        "label": "% full-year spending",
                                        "value": "PERCENT_FULL_YEAR_SPENDING",
                                    },
                                    {
                                        "label": "% year-to-year spending",
                                        "value": "PERCENT_YEAR_TO_YEAR_SPENDING",
                                    },
                                    {
                                        "label": "% year-to-year revenue",
                                        "value": "PERCENT_YEAR_TO_YEAR_REVENUE",
                                    },
                                ],
                                clearable=False,
                                value="ABSOLUTE",
                                placeholder="Billion RUB",
                                style={"width": "200px"},
                            ),
                        ],
                        style={
                            "display": "flex",
                            "flex-wrap": "wrap",
                            "justify-content": "flex-start",
                            "gap": "10px",
                        },
                    ),
                    html.Div(
                        [
                            # html.Div(
                            #     [
                            #         html.Button("Share", id="btn-share-view"),
                            #         dcc.Clipboard(id="clipboard-treemap-link"),
                            #     ]
                            # ),
                            html.Div(
                                [
                                    html.Button(
                                        html.Img(
                                            src="/assets/icons/photo_camera.svg",
                                            style={"width": "2em", "height": "2em"},
                                        ),
                                        id="btn-download-image",
                                        title="Download Treemap Plot as PNG",
                                    ),
                                    dcc.Download(id="download-treemap-image"),
                                ]
                            ),
                            html.Div(
                                [
                                    html.Button(
                                        html.Img(
                                            src="/assets/icons/download.svg",
                                            style={"width": "2em", "height": "2em"},
                                        ),
                                        id="btn-download-csv",
                                        title="Download Treemap Data as CSV",
                                    ),
                                    dcc.Download(id="download-treemap-data"),
                                ]
                            ),
                            dcc.Link(
                                html.Button(
                                    html.Img(
                                        src="/assets/icons/stacked_bar_chart.svg",
                                        style={"width": "2em", "height": "2em"},
                                    ),
                                    title="Switch to Time Series View",
                                ),
                                href="/timeseries",
                            ),
                            dcc.Link(
                                html.Button(
                                    html.Img(
                                        src="/assets/icons/info.svg",
                                        style={"width": "2em", "height": "2em"},
                                    ),
                                    title="About This Project",
                                ),
                                href="/about",
                            ),
                        ],
                        style={
                            "display": "flex",
                            "flex-wrap": "wrap",
                            "justify-content": "flex-end",
                            "gap": "10px",
                        },
                    ),
                ],
                style={
                    "display": "flex",
                    "flex-wrap": "wrap",
                    "justify-content": "space-between",
                    "gap": "10px",
                    "margin-bottom": "10px",
                    "margin-top": "20px",
                    "margin-left": "2.5vw",
                    "margin-right": "2.5vw",
                },
            ),
            html.Div(
                # Graph to display the treemap
                [
                    dcc.Store(id="treemap-store"),
                    dcc.Graph(id="treemap-graph", config=TREEMAP_CONFIG),
                ],
                style={"width": "100%", "height": "90vh"},
            ),
        ]
    )


# Callback to populate the graph on load and when filters change
@callback(
    Output("treemap-graph", "figure"),
    Input("budget-dataset-dropdown", "value"),
    Input("viewby-dropdown", "value"),
    Input("spending-type-dropdown", "value"),
    Input("spending-scope-dropdown", "value"),
)
def update_figure_from_filters(
    budget_id: int | None = None,
    viewby: ViewByDimensionTypeLiteral = "MINISTRY",
    spending_type: SpendingTypeLiteral = "ALL",
    spending_scope: SpendingScopeLiteral = "ABSOLUTE",
) -> go.Figure:
    """
    This callback is triggered on page load and when the budget type dropdown changes.
    It loads the appropriate data and generates the treemap figure.

    Args:
        budget_type (str | None): The selected value from the budget type dropdown.

    Returns:
        go.Figure: The generated treemap figure to display in the dcc.Graph.
    """
    # Load data based on the selected filter
    labels, parents, values, metadata = fetch_treemap_data(
        budget_id=budget_id,
        spending_type=spending_type,
        spending_scope=spending_scope,
    )

    # Generate and return the figure
    return generate_figure(labels, parents, values, metadata, viewby=viewby, language="EN")


# Callback to handle store
@callback(
    Output("treemap-store", "data"),
    Input("budget-dataset-dropdown", "value"),
    Input("viewby-dropdown", "value"),
    Input("spending-type-dropdown", "value"),
    Input("spending-scope-dropdown", "value"),
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
    prevent_initial_call=True,
)
def download_image(n_clicks, data, figure) -> dict[str, Any]:
    """
    Callback to download the current treemap data as a csv file.
    Returns:
        dict[str, Any]: The data for download.
    """
    figure_bytes = figure.to_image(format="png")
    return dcc.send_bytes(figure_bytes, "treemap_figure.png")  # type: ignore


# Clientside callback to handle URL focus parameter and click simulation
clientside_callback(
    ClientsideFunction(namespace="clientside", function_name="findAndClickSlice"),
    Output("dummy-treemap-output", "children"),
    Input("url", "search"),  # Listen directly to URL changes
    Input("treemap-graph", "figure"),  # Also listen to figure updates to re-trigger focus
    prevent_initial_call=True,  # Only run when inputs change
)
