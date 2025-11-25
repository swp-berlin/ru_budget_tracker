from typing import Any
from urllib.parse import parse_qs, urlparse, unquote

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dash import (
    ClientsideFunction,
    Input,
    NoUpdate,
    Output,
    callback,
    callback_context,
    clientside_callback,
    dcc,
    html,
    no_update,
    register_page,
)
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from database import get_sync_session
from models import Budget, Dimension, Expense
from scripts.transform_treemap.transform import transform_data

import logging

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

register_page(__name__, path="/")


def load_data(type_filter: str | None) -> pd.DataFrame:
    select_stmt = (
        select(
            Budget.id.label("budget_id"),
            Expense.id.label("expense_id"),
            Dimension.id.label("dimension_id"),
            Dimension.parent_id.label("dimension_parent_id"),
            Dimension.type.label("dimension_type"),
            Dimension.name.label("dimension_name"),
            Dimension.name_translated.label("dimension_name_translated"),
            Expense.value.label("expense_value"),
        )
        .join(Dimension.expenses, isouter=True)
        .join(Expense.budget, isouter=True)
    )

    # if type_filter:
    #     select_stmt = select_stmt.where(Budget.type == type_filter)

    with get_sync_session() as session:
        result = session.execute(select_stmt).unique().mappings().all()

    df = transform_data(result)

    return df


def generate_figure(df: pd.DataFrame, language: str) -> go.Figure:
    fig = px.treemap(
        df,
        path=[df.columns[i] for i in range(df.shape[1] - 1)],
        values="expense_value",
    )
    fig.update_layout(margin=dict(t=50, l=25, r=25, b=25))
    return fig


def layout(budgettype: Any = None, **other_unknown_query_strings: str | None) -> html.Div:
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
        [
            # dcc.Location is used to read the URL from the browser's address bar.
            # Its 'search' property (the query string) is used to get the 'focus' parameter.
            dcc.Location(id="url"),
            # dcc.Store is a component for storing data in the user's browser.
            # We use it here to hold the name of the treemap node we want to zoom in on.
            # This allows us to pass the value from the URL to our clientside callback.
            dcc.Store(id="focus-store"),
            # This dummy div is the target for our clientside callback. It's required for the
            # callback to have an Output, but it doesn't need to be visible.
            html.Div(id="dummy-output", style={"display": "none"}),
            # Add Buttons and dropdowns for filtering by budget type
            html.Div(
                [
                    html.H1("Filters: "),
                    dcc.Dropdown(
                        id="budget-type-dropdown-1",
                        options=[
                            {"label": "DRAFT", "value": "DRAFT"},
                            {"label": "LAW", "value": "LAW"},
                            {"label": "REPORT", "value": "REPORT"},
                            {"label": "TOTAL", "value": "TOTAL"},
                        ],
                        value=budgettype,
                        clearable=True,
                        placeholder="Filter by Budget Type",
                        style={"width": "200px"},
                    ),
                    dcc.Dropdown(
                        id="viewby-dropdown",
                        options=[
                            {"label": "Ministry", "value": "ministry"},
                            {"label": "Chapter", "value": "chapter"},
                            {"label": "Program", "value": "program"},
                        ],
                        clearable=True,
                        placeholder="View by",
                        style={"width": "200px"},
                    ),
                    dcc.Dropdown(
                        id="spending-type-dropdown",
                        options=[
                            {"label": "all", "value": "all"},
                            {"label": "military only", "value": "military_only"},
                        ],
                        clearable=True,
                        placeholder="Filter by Spending type",
                        style={"width": "200px"},
                    ),
                    dcc.Dropdown(
                        id="spending-scope-dropdown",
                        options=[
                            {"label": "Billion RUB", "value": "absolut"},
                            {"label": "% full-year GDP", "value": "percent_gdp_full_year"},
                            {"label": "% year-to-year GDP", "value": "percent_gdp_year_to_year"},
                            {
                                "label": "% full-year spending",
                                "value": "percent_full_year_spending",
                            },
                            {
                                "label": "% year-to-year spending",
                                "value": "percent_year_to_year_spending",
                            },
                            {
                                "label": "% year-to-year revenue",
                                "value": "percent_year_to_year_revenue",
                            },
                        ],
                        clearable=True,
                        placeholder="View Spending in",
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
            html.H2("This is our Treemap page"),
            html.Div(f"Budget type: {budgettype}"),
            dcc.Graph(id="treemap-graph"),
        ]
    )


# This callback now populates the graph on load and when the filter changes.
@callback(
    Output("treemap-graph", "figure"),
    Input("budget-type-dropdown-1", "value"),
)
def update_figure_from_filters(budget_type: str | None) -> go.Figure:
    """
    This callback is triggered on page load and when the budget type dropdown changes.
    It loads the appropriate data and generates the treemap figure.

    Args:
        budget_type (str | None): The selected value from the budget type dropdown.

    Returns:
        Figure: The generated treemap figure to display in the dcc.Graph.
    """
    # Load data based on the selected filter.
    df = load_data(budget_type)
    # Generate and return the figure.
    return generate_figure(df, "en")


@callback(
    Output("focus-store", "data"),
    Input("url", "search"),  # Trigger on query string changes
)
def store_focus_node_from_url(search: str | None) -> dict | NoUpdate:
    """
    This callback captures the 'focus' query parameter from the URL's search
    string and stores it in a dcc.Store. It fires whenever the query string changes.
    The focus node is URL-decoded to handle special characters properly.
    """
    if not search:
        return no_update

    # Parse the query string and get the focus parameter
    params = parse_qs(urlparse(search).query)
    focus_node = params.get("focus", [None])[0]

    if focus_node:
        # URL-decode the focus node to handle special characters
        decoded_focus_node = unquote(focus_node).strip()
        logger.info(
            f"URL parameter 'focus={focus_node}' found, decoded as '{decoded_focus_node}'. Storing for clientside."
        )

        # Add a timestamp to ensure the data is always "new", forcing the clientside callback to run
        return {
            "node": decoded_focus_node,
            "timestamp": pd.Timestamp.now().isoformat(),
            "original": focus_node,  # Keep original for debugging
        }

    return no_update


# Callback to re-trigger focus when both the focus store and figure are updated
@callback(
    Output("focus-store", "data", allow_duplicate=True),
    Input("focus-store", "data"),
    Input("treemap-graph", "figure"),
    prevent_initial_call=True,
)
def retrigger_focus_on_figure_update(focus_data: dict | None, figure: go.Figure) -> dict | NoUpdate:
    """
    This callback re-triggers the focus mechanism when the treemap figure updates
    (e.g., when filters change) while there's a focus node in the store.
    This ensures that the focus is maintained even after the treemap re-renders.
    """
    if not focus_data or not focus_data.get("node"):
        return no_update

    # Check which input triggered this callback
    ctx = callback_context
    if not ctx.triggered:
        return no_update

    trigger_id = ctx.triggered[0]["prop_id"]

    # Only re-trigger if the figure was updated (not the focus-store itself)
    if "treemap-graph.figure" in trigger_id:
        logger.info(f"Treemap figure updated, re-triggering focus for '{focus_data['node']}'")
        # Update timestamp to force clientside callback to run again
        return {
            "node": focus_data["node"],
            "timestamp": pd.Timestamp.now().isoformat(),
            "original": focus_data.get("original", focus_data["node"]),
            "retrigger": True,  # Flag to indicate this is a re-trigger
        }

    return no_update


# clientside callback to trigger the click simulation
clientside_callback(
    ClientsideFunction(namespace="clientside", function_name="findAndClickSlice"),
    Output("dummy-output", "children"),
    Input("focus-store", "data"),
    prevent_initial_call=True,  # Only run when the store is updated by the callback above
)
