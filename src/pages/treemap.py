from dash import html, register_page, dcc
import plotly.express as px
import pandas as pd

register_page(__name__, path="/")

df = px.data.tips()
fig = px.treemap(
    df, path=[px.Constant("all"), "sex", "day", "time"], values="total_bill", color="day"
)
fig.update_layout(margin=dict(t=50, l=25, r=25, b=25))


def layout(dimensions: str | None = None, **other_unknown_query_strings: str | None) -> html.Div:
    return html.Div(
        [
            html.H1("This is our Treemap page"),
            html.Div(f"Dimensions: {dimensions}"),
            html.Div(f"Other Query Strings: {other_unknown_query_strings}"),
            html.Div("This is our Treemap page content."),
            dcc.Graph(figure=fig),
        ]
    )
