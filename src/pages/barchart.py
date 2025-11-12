from dash import html, register_page, dcc, callback, Output, Input
from datetime import datetime
import plotly.express as px
from plotly.graph_objects import Figure
import pandas as pd
from database import get_sync_session
from sqlalchemy import select, func
from sqlalchemy.orm import joinedload, selectinload
from models import Dimension, Budget, Expense

register_page(__name__, path="/details")


def load_data() -> pd.DataFrame:
    select_stmt = (
        select(Budget).join(Budget.expenses)  # Join dimensions with expenses
    )

    with get_sync_session() as session:
        budgets = session.execute(select_stmt).scalars().all()

    expenses = [sum(exp.value for exp in budget.expenses) for budget in budgets]
    dates = [budget.published_at for budget in budgets]
    types = [budget.type for budget in budgets]

    df = pd.DataFrame({"expenses": expenses, "dates": dates, "types": types})
    # Parse dates to datetime
    df["dates"] = pd.to_datetime(df["dates"])
    # Truncate dates to years
    df["dates"] = df["dates"].dt.to_period("Y").dt.to_timestamp()

    return df


def generate_figure(dataframe: pd.DataFrame) -> Figure:
    fig = px.histogram(
        data_frame=dataframe,
        x="dates",
        y="expenses",
        color="types",
        barmode="group",
    )
    fig.update_layout(margin=dict(t=50, l=25, r=25, b=25))
    return fig


def layout(**other_unknown_query_strings: str | None) -> html.Div:
    df = load_data()
    len(df)
    fig = generate_figure(df)
    return html.Div(
        [
            html.H1("This is our Barchart page"),
            html.Div(f"Data points: {len(df)}"),
            dcc.Graph(figure=fig),
        ]
    )
