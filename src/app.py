"""Dash Plotly App."""

from dash import Dash, html, page_container

app = Dash(__name__, use_pages=True)
server = app.server


app.layout = html.Div(
    children=[
        page_container,
    ]
)


@app.server.route("/healthz")
def healthz():
    return {"status": "ok"}


if __name__ == "__main__":
    app.run(debug=True)
