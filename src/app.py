"""Dash Plotly App."""

from dash import Dash, html, page_container
import dash_bootstrap_components as dbc

app = Dash(
    __name__,
    use_pages=True,
    external_stylesheets=[dbc.themes.BOOTSTRAP],
)
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
    # Run the server without the Werkzeug reloader to avoid Python 3.13 DummyThread __del__ shutdown errors
    # Debug can stay on; use_reloader=False prevents the extra thread that triggers the exception
    app.run(debug=True, use_reloader=False)
