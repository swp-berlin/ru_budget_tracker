import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dash import (
    ClientsideFunction,
    Input,
    Output,
    callback,
    clientside_callback,
    dcc,
    html,
    register_page,
)

from models import ViewByDimensionTypeLiteral
from utils import TreemapTransformer, fetch_budgets, fetch_treemap_data
from utils.definitions import (
    LanguageTypeLiteral,
    SpendingScopeLiteral,
    SpendingTypeLiteral,
)

import logging

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

register_page(__name__, path="/")


def generate_figure(
    df: pd.DataFrame,
    viewby: ViewByDimensionTypeLiteral = "MINISTRY",
    language: LanguageTypeLiteral = "EN",
) -> go.Figure:
    path = [df.columns[i] for i in range(df.shape[1] - 1)]
    if viewby != "MINISTRY":
        path.remove("MINISTRY")
    if viewby == "PROGRAMM":
        path.remove("CHAPTER")

    fig = px.treemap(
        df,
        path=path,
        values="EXPENSE_VALUE",
    )
    fig.update_layout(margin=dict(t=50, l=25, r=25, b=25))
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
                    html.H1("Filters: "),
                    dcc.Dropdown(
                        id="budget-dataset-dropdown",
                        options=budget_options,
                        clearable=False,
                        value=budget_options[0]["value"] if budget_options else None,
                        placeholder=budget_options[0]["label"]
                        if budget_options
                        else "Select Budget",
                        searchable=True,
                        style={"width": "200px"},
                    ),
                    dcc.Dropdown(
                        id="viewby-dropdown",
                        options=[
                            {"label": "Ministry", "value": "MINISTRY"},
                            {"label": "Chapter", "value": "CHAPTER"},
                            {"label": "Programm", "value": "PROGRAMM"},
                        ],
                        clearable=False,
                        value="MINISTRY",
                        placeholder="Ministry",
                        style={"width": "200px"},
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
                        style={"width": "200px"},
                    ),
                    dcc.Dropdown(
                        id="spending-scope-dropdown",
                        options=[
                            {"label": "Billion RUB", "value": "ABSOLUT"},
                            {"label": "% full-year GDP", "value": "PERCENT_GDP_FULL_YEAR"},
                            {"label": "% year-to-year GDP", "value": "PERCENT_GDP_YEAR_TO_YEAR"},
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
                        value="ABSOLUT",
                        placeholder="Billion RUB",
                        style={"width": "250px"},
                    ),
                    # Button to switch to Barchart page
                    dcc.Link(
                        html.Button("Go to Timeseries"),
                        href="/timeseries",
                    ),
                ],
                style={
                    "display": "flex",
                    "gap": "10px",
                    "margin-bottom": "20px",
                    "margin-top": "20px",
                },
            ),
            dcc.Graph(id="treemap-graph"),
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
    budget_dataset: int | None = None,
    viewby: ViewByDimensionTypeLiteral = "MINISTRY",
    spending_type: SpendingTypeLiteral = "ALL",
    spending_scope: SpendingScopeLiteral = "ABSOLUT",
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

    data = fetch_treemap_data(
        budget_dataset=budget_dataset,
        viewby=viewby,
        spending_type=spending_type,
        spending_scope=spending_scope,
    )
    transformer = TreemapTransformer(data, translated=False)
    df = transformer.transform_data()

    # Generate and return the figure
    return generate_figure(df=df, viewby=viewby, language="EN")


# Clientside callback to handle URL focus parameter and click simulation
clientside_callback(
    ClientsideFunction(namespace="clientside", function_name="findAndClickSlice"),
    Output("dummy-treemap-output", "children"),
    Input("url", "search"),  # Listen directly to URL changes
    Input("treemap-graph", "figure"),  # Also listen to figure updates to re-trigger focus
    prevent_initial_call=True,  # Only run when inputs change
)
