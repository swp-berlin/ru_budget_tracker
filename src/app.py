"""Dash Plotly App."""

import dash_bootstrap_components as dbc
from dash import Dash

from settings import settings

# The app must be created before importing layout or callbacks, because
# get_asset_url (used in layout.py) requires the Dash instance to exist.
app = Dash(
    __name__,
    use_pages=True,
    external_stylesheets=[dbc.themes.BOOTSTRAP],
    suppress_callback_exceptions=True,  # Required for pages with callbacks referencing shared stores
    update_title=None,  # type: ignore
    url_base_pathname=settings.app.url_base_pathname,
)

server = app.server


@app.server.route("/healthz")
def healthz():
    return {"status": "ok"}


from layout import serve_layout, validation_layout  # noqa: E402
import callbacks  # noqa: E402, F401 — registers all @callback and clientside_callback decorators

app.layout = serve_layout

# Validation layout includes all components that callbacks might reference.
# This prevents "component not found" warnings during callback validation.
app.validation_layout = validation_layout


# Only for Debugging
if __name__ == "__main__":
    app.run(debug=True, use_reloader=False)
