import pandas as pd
import plotly.express as px
from dash import dcc, html, register_page
from plotly.graph_objects import Figure
from sqlalchemy import select

from database import get_sync_session
from models import Budget, Expense, Dimension

register_page(__name__, path="/details")


def load_data(original_identifier: str | None = None) -> pd.DataFrame:
    """
    Load budget and expense data from the database and return as a DataFrame.
    Takes an optional original_identifier to filter budgets.
    """
    # Parse original_identifier to filter budgets if provided
    original_identifier_filter = (
        # Parsing logic here
        str(original_identifier) if original_identifier is not None else None
    )
    # Build the select statement
    # We need to fetch budgets along with their (summed) expenses and the
    select_stmt = (
        select(
            Budget.id.label("budget_id"),
            Budget.original_identifier.label("original_identifier"),
            Budget.published_at.label("published_at"),
            Budget.type.label("type"),
            Expense.id.label("expense_id"),
            Dimension.id.label("dimension_id"),
            Dimension.type.label("dimension_type"),
            Dimension.name.label("dimension_name"),
            Dimension.name_translated.label("dimension_name_translated"),
            Expense.value.label("expense_value"),
        )
        .join(Dimension.expenses, isouter=True)
        .join(Expense.budget, isouter=True)
    )

    if original_identifier_filter is not None:
        select_stmt = select_stmt.where(Budget.original_identifier == original_identifier_filter)

    with get_sync_session() as session:
        budgets = session.execute(select_stmt).unique().mappings().all()

    expenses = [
        budget["expense_value"] if budget["type"] != "TOTAL" else -budget["expense_value"]
        for budget in budgets
    ]
    dates = [budget["published_at"] for budget in budgets]
    types = [budget["type"] for budget in budgets]

    df = pd.DataFrame({"expenses": expenses, "dates": dates, "types": types})
    # Parse dates to datetime
    df["dates"] = pd.to_datetime(df["dates"])
    # Truncate dates to years
    df["dates"] = df["dates"].dt.to_period("Y").dt.to_timestamp()

    return df


def update_figure(dataframe: pd.DataFrame) -> Figure:
    fig = px.histogram(
        data_frame=dataframe,
        x="dates",
        y="expenses",
        color="types",
        barmode="relative",
    )
    fig.update_layout(margin=dict(t=50, l=25, r=25, b=25))
    return fig


def layout(**other_unknown_query_strings: str | None) -> html.Div:
    df = load_data()
    len(df)
    fig = update_figure(df)
    return html.Div(
        [
            html.H1("This is our Barchart page"),
            html.Div(f"Data points: {len(df)}"),
            dcc.Graph(figure=fig),
        ]
    )
