# Adding a page

Step-by-step guide for adding a new route to the Dash app. Covers the three
things a new page touches: a layout module in `src/pages/`, callbacks in
`src/callbacks/`, and (optionally) CSS in `src/assets/css/`.

See [`pages.md`](pages.md) for what the existing pages do and
[`callbacks.md`](callbacks.md) for the full callback package reference — this
doc is the procedure for adding to both.

## 1. Layout — `src/pages/<name>.py`

`app.py` creates the app with `use_pages=True` and no explicit `pages_folder`,
so Dash auto-discovers any module in `src/pages/` that calls `register_page`
— there is nothing to wire up in `app.py` itself.

```python
from dash import html, register_page

register_page(__name__, path="/your-path", title="Your Page Title")

def layout(**other_kwargs) -> html.Div:
    return html.Div(
        className="plot-page",  # or "about-page" — see step 3
        children=[...],
    )
```

Points that matter, based on the existing three pages:

- **Layout as a function vs. a static variable.** Use a `def layout(**other_kwargs):`
  function (like `treemap.py`/`timeseries.py`) if the page reads query-string
  filters or needs anything evaluated per-request. Use a plain `layout = html.Div(...)`
  variable (like `about.py`) only for fully static content.
- **Hidden stub components for cross-page callbacks.** Every page currently
  includes hidden copies of components owned by other pages —
  e.g. `about.py` and `timeseries.py` both render a hidden
  `dcc.Graph(id="treemap-graph", style={"display": "none"})`. This is required
  because `suppress_callback_exceptions=True` is set precisely so
  callbacks can output to components that live on a *different* page, but
  Dash still needs each `Output`/`Input` id to exist in whatever layout is
  currently rendered. If your new page is targeted by an existing callback
  (most will be, since the shared toolbar's filters/stores apply everywhere),
  add hidden stubs for whichever ids that callback touches.
- **Don't hardcode paths.** Anywhere you need the app's own path (a link,
  an href, a pathname comparison), use `get_relative_path("/your-path")`
  from `dash`, never a raw string. The app's `url_base_pathname` can be
  non-root, and `get_relative_path` is the only thing that accounts for it.
- **Register the page's ids in `validation_layout`.** `src/layout.py` defines
  a `validation_layout` used only for Dash's startup callback-id validation
  (it's never rendered to users). If your callbacks reference an id that
  doesn't already appear in the shared `toolbar` or in another page's stub,
  add it there too, following the existing entries.
- **No callbacks in the page file.** Every existing page file contains only
  `register_page(...)` and `layout` — see step 2.

## 2. Callbacks — `src/callbacks/`

Callback logic never lives in `src/pages/`; it lives in `src/callbacks/`,
one module per page (`callback_treemap.py`, `callback_timeseries.py`) plus
`callback.py` for page-agnostic/shared logic and `helper.py` for pure
rendering helpers.

Steps:

1. Add a new module, e.g. `src/callbacks/callback_yourpage.py`, containing
   your page's `@callback`/`@clientside_callback` definitions.
2. **Import it in `src/callbacks/__init__.py`.** This is the only
   registration mechanism — Dash's `@callback` decorator writes into a
   process-wide registry at import time, so a callback that is never
   imported never registers, silently. `__init__.py` currently reads:
   ```python
   from callbacks import callback, callback_treemap, callback_timeseries
   ```
   Add your new module to this line.
3. **Extend the pathname-driven toolbar toggles in `callback.py`** if your
   page needs different filter-menu visibility, button states, or navigation
   behavior than the existing pages. These are hardcoded if/else branches
   keyed on `pathname == get_relative_path(...)`, not a generic per-page
   config table, so a third page means adding a branch, not filling in a
   table:
   - `toggle_viewby_period_menu` — shows/hides the View By and Period menus.
   - `toggle_resize_interval` — enables the timeseries tick-resize interval.
   - `switch_graphs` — computes the "switch view" button's href/icon/label;
     currently a straight two-way swap between treemap and timeseries, so
     adding a third page here needs it generalized into a lookup rather than
     a simple `if`/`else`.
   - `update_about_button` / `track_previous_path` — About page's back-button
     behavior.
   - `toggle_action_buttons_disabled` — disables toolbar filters/buttons on
     pages where they don't apply (currently just `/about`).

   If your page is a static/content page like About, follow
   `toggle_action_buttons_disabled`'s pattern to disable the filter toolbar
   on it. If it's a chart page like treemap/timeseries, it likely wants the
   filters left active and just needs its own figure-rendering callback.
4. If your page needs its own cached data-fetch function (like
   `fetch_treemap_data`/`fetch_timeseries_data`), define it in your new
   callback module and, if it should be warmed at startup, import it into
   `app.py`'s prewarming thread the same way the existing two are.
5. Reuse `helper.py` for shared shaping/rendering logic rather than
   duplicating it. Watch for the circular-import trap already worked around
   there: `helper.py` is imported at module level by the page-specific
   callback modules, so anything `helper.py` needs back from a page-specific
   module must be a lazy (in-function) import, as `build_server_node_map`
   already does for `transform_treemap_data`.

## 3. CSS — `src/assets/css/`

Dash serves everything under `src/assets/` automatically at `/assets/<path>`
— no `<link>` tags to add. CSS here is split by concern, not one global
file (see [`assets.md`](assets.md) for the full breakdown):

| File | Scope |
|---|---|
| `menu.css` | Shared toolbar/dropdown styles — applies to every page automatically. |
| `typography.css` | Global font loading and text styles — applies everywhere automatically. |
| `plot.css` | Full-height flex layout keyed off the `.plot-page` class (used by `#app-layout:has(.plot-page)`). |
| `about.css` | About-page-only styles keyed off `.about-page`. |

The convention: **each page picks one top-level `className`** on its root
`html.Div` (`"plot-page"` for treemap/timeseries, `"about-page"` for about),
and any page-specific CSS is scoped to that class in its own file. For a new
page:

- If it's a full-height chart like treemap/timeseries, reuse
  `className="plot-page"` and you get the existing layout rules for free —
  no new CSS file needed.
- If it's a static/content page like about, either reuse `"about-page"` (if
  the look should match) or add a new `src/assets/css/yourpage.css` file
  scoped to a new `"yourpage-page"` class name. New CSS files need no manual
  registration — Dash picks up everything in `assets/css/` automatically.
- Toolbar/menu styling (`menu.css`) and typography apply globally already;
  you only need new CSS for content unique to your page.
- If your page adds a new toolbar icon, add it under `src/assets/icons/` and
  add a row to [`assets-icons.md`](assets-icons.md).
