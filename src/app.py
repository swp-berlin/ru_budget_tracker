"""Dash Plotly App."""

# NOTE
# Use pandas in callback to define data dynamically
# Use plotly.express to create figures
# Update figures using Patch

from dash import Dash, Patch, html, dcc, Input, Output, State, callback, page_container


app = Dash(__name__, use_pages=True)

app.layout = html.Div(
    children=[
        html.H1(children="Title: This text will always be here"),
        page_container,
    ]
)

if __name__ == "__main__":
    app.run(debug=True)
