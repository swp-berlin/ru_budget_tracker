# `src/callbacks/`

All Dash callback registrations for the app, plus the rendering/data-shaping helpers they
share. Every `@callback` / `@clientside_callback` in the codebase lives here — page files
in `src/pages/` only contain `register_page(...)` and `layout()`.

Dash's `@callback`/`@clientside_callback` decorators write into a process-wide registry
independent of the `Dash` app instance, so it doesn't matter which file a callback is
defined in — only that its module gets imported once before the server starts. `app.py`
does this with a single `import callbacks`, which runs `__init__.py` and, through it,
every submodule below.

## Files

### `__init__.py`
Imports `callback`, `callback_treemap`, and `callback_timeseries` for their side effects
(registering every `@callback`/`@clientside_callback` they define). No callback logic of
its own.

### `callback.py`
Shared, page-agnostic callbacks: toolbar navigation (About/back button, switch-graphs
button), the budget dropdown, the view-by/period/spending-type/unit filter menus (built
via the `_make_select_callback`/`_make_highlight_callback` factories), the language
toggle, the share toast, and the clientside spinner/zoom/share-link/image-download
bridges.

### `callback_treemap.py`
Callbacks for the treemap page (`pages/treemap.py`, `/`): rendering the figure from the
active filters (`update_figure_from_filters`), immediately storing the clicked node in the
browser (`storeTreemapSelection`), and CSV export (`download_treemap_data`). Also owns the treemap
data pipeline — `fetch_treemap_data` and `transform_treemap_data` (both `@lru_cache`d) —
because `app.py`'s startup cache-prewarming imports them directly from here.

`store-selected-id` holds a short id that's only meaningful relative to the
`store-treemap-node-map` that was current when it was set. `storeTreemapSelection` runs
clientside so a following filter action cannot overtake the selection update, including after
navigation back to the root. When `viewby` or `spending_type` rebuilds the map with new short ids,
`update_figure_from_filters` remaps the selected node by its leaf and ancestor dimension ids, or
clears it when the same subject is unavailable.

### `callback_timeseries.py`
Callbacks for the timeseries page (`pages/timeseries.py`, `/timeseries`): rendering the
bar chart from filters (`update_figure_from_filters`), CSV export
(`download_timeseries_data`), and two clientside callbacks that keep quarterly tick
labels readable across window resizes. Also owns `fetch_timeseries_data` — with its own
in-process cache and private helpers `_calculate_values`/`_shape_for_period` — imported
by `app.py`'s prewarming for the same reason as above.

### `helper.py`
Pure rendering/shaping helpers shared by both page-specific callback modules: unit labels
for CSV headers (`get_unit_label`), deterministic treemap node coloring
(`create_treemap_colors`) and its per-node label colors (`create_treemap_text_colors`),
spending-type/viewby DataFrame shaping
(`shape_for_spending_type`, `shape_for_viewby`, `shape_dataframe`), and two node-id maps —
`build_compact_node_map` (sent to the browser, short integer ids) and
`build_server_node_map` (server-only, full dimension metadata, `@lru_cache`d).

`build_server_node_map` lazily imports `transform_treemap_data` from
`callback_treemap.py` inside its function body rather than at module load time, to avoid
a circular import (`callback_treemap.py` itself imports from `helper.py`).
