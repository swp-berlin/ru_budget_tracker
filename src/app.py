"""Dash Plotly App."""

from dash import Dash, html, page_container


app = Dash(__name__, use_pages=True)

app.layout = html.Div(
    children=[
        html.H1(children="Title: This text will always be here"),
        page_container,
    ]
)

if __name__ == "__main__":
    app.run(debug=True)
