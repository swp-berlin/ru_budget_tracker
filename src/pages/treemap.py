from typing import Any
from dash import html, register_page, dcc
import plotly.express as px
from plotly.graph_objects import Figure
import pandas as pd
from database import get_sync_session
from sqlalchemy import select
from models import Dimension, Budget, Expense
from scripts.transform_treemap.transform import transform_data

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


def generate_figure(df: pd.DataFrame) -> Figure:
    fig = px.treemap(
        df,
        path=[df.columns[i] for i in range(df.shape[1] - 1)],
        values="expense_value",
    )
    fig.update_layout(margin=dict(t=50, l=25, r=25, b=25))
    return fig


def layout(budgettype: Any = None, **other_unknown_query_strings: str | None) -> html.Div:
    df = load_data(budgettype)
    fig = generate_figure(df)
    return html.Div(
        [
            html.H1("This is our Treemap page"),
            html.Div(f"Budget type: {budgettype}"),
            html.Div(f"Data points: {len(df)}"),
            dcc.Graph(figure=fig),
        ]
    )
