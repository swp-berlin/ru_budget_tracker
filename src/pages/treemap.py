from typing import Any
from dash import html, register_page, dcc, callback, Output, Input
import plotly.express as px
from plotly.graph_objects import Figure
import pandas as pd
from database import get_sync_session
from sqlalchemy import select, func
from sqlalchemy.orm import joinedload, selectinload
from models import Dimension, Budget, Expense

register_page(__name__, path="/")

ROOT_NODE_NAME = "root"


def load_data(type_filter: str | None) -> pd.DataFrame:
    select_stmt = (
        select(Dimension)
        .join(Dimension.expenses)  # Join dimensions with expenses
        .join(Expense.budget)  # Join expenses with budgets
        .options(selectinload(Dimension.parent))  # Eagerly load parent relationships
        .options(
            selectinload(Dimension.expenses).selectinload(Expense.budget)
        )  # Eagerly load expense-budget data
    )

    # Apply budget type filter if provided
    if type_filter:
        select_stmt = select_stmt.where(Budget.type == type_filter)

    with get_sync_session() as session:
        dimensions = session.execute(select_stmt).scalars().all()

    values = [0] + [sum(exp.value for exp in dim.expenses) for dim in dimensions]
    labels = [ROOT_NODE_NAME] + [dim.name for dim in dimensions]
    parents = [""] + [dim.parent.name if dim.parent else ROOT_NODE_NAME for dim in dimensions]

    df = pd.DataFrame({"labels": labels, "parents": parents, "values": values})

    return df


def generate_figure(dataframe: pd.DataFrame) -> Figure:
    fig = px.treemap(
        data_frame=dataframe,
        path=[px.Constant(ROOT_NODE_NAME), "labels", "parents"],
        values="values",
    )
    fig.update_layout(margin=dict(t=50, l=25, r=25, b=25))
    return fig


def layout(budgettype: Any = None, **other_unknown_query_strings: str | None) -> html.Div:
    df = load_data(budgettype)
    len(df)
    fig = generate_figure(df)
    return html.Div(
        [
            html.H1("This is our Treemap page"),
            html.Div(f"Budget type: {budgettype}"),
            html.Div(f"Data points: {len(df)}"),
            dcc.Graph(figure=fig),
        ]
    )
