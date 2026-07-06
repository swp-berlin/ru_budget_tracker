# Assets

Static files served directly by Dash. Dash automatically serves everything under `src/assets/` at `/assets/<path>`.

```
assets/
├── css/
│   ├── about.css          # Styles for the About page
│   ├── menu.css           # Toolbar and dropdown layout
│   └── typography.css     # Font loading and text styles
├── fonts/
│   └── Source_Sans_3/     # Variable font (OFL licence)
├── icons/                 # Material Icons SVGs (see docs/assets-icons.md)
├── javascript/
│   ├── clientside_export.js   # Share link + PNG download
│   ├── clientside_treemap.js  # Treemap deep-link focus + text inset
│   └── clientside_ui.js       # Spinners + timeseries tick labels
└── logo/
    └── logo.svg
```

---

## CSS

### `about.css`

Standalone styles for the About page. Defines CSS custom properties (`--fg`, `--muted`, `--accent`), base `body` typography, a centred `header` / `main` layout (max-width 960 px), and minimal utility classes (`.btn`, `.muted`, `.spacer`).

### `menu.css`

Layout rules for the main toolbar. Covers:

- **Dropdown toggles** — fixed 40 px height, ellipsis truncation with a caret kept visible via `::after` positioning, for all five filter menus (`budget`, `viewby`, `period`, `spending-type`, `unit`).
- **Dropdown lists** — max-height 300 px with `overflow-y: auto`.
- **Action buttons** — uniform 40 px height, fixed widths for `#btn-switch-graphs` (130 px) and `#btn-switch-data-language` (50 px).
- **Responsive breakpoints:**
  - `≤ 1500 px` — toolbar wraps onto two rows.
  - `≤ 600 px` — dropdowns stack full-width vertically; action buttons form a centred horizontal row; timeseries button label hidden.
  - `≤ 480 px` — dropdowns capped at 180 px.
- **Loading spinner** — `.treemap-spinner` CSS animation (`treemap-spin` keyframe, 0.8 s rotation).

### `typography.css`

Loads Source Sans 3 from the local `.ttf` file via `@font-face`. Applies `font-family`, `font-size: 14px`, `font-weight: 600`, and `color: #333333` to all five filter-menu dropdowns and all toolbar action buttons. Overrides inner `<span>` elements (used for tooltip text) with `font-weight: 300`.

---

## Fonts

**Source Sans 3** is SWP's standard brand font and is licensed under the [SIL Open Font Licence 1.1](https://scripts.sil.org/OFL). You are free to use, embed, and redistribute it — including in commercial products — provided that:

- the font files are not sold on their own,
- any modified version is released under the OFL and uses a name distinct from "Source Sans 3", and
- the copyright notice and licence text are retained when redistributing.

The full licence text is included in `src/assets/fonts/Source_Sans_3/OFL.txt`.

Two variable-font files are used:

| File | Axes |
|---|---|
| `SourceSans3-VariableFont_wght.ttf` | `wght` 200–900 |
| `SourceSans3-Italic-VariableFont_wght.ttf` | `wght` 200–900, italic |

Static `.ttf` cuts for all nine weights (ExtraLight → Black) in both upright and italic are included under `static/` but are not referenced in CSS — they exist for completeness and for export use (see `clientside_export.js` below).

Only the upright variable font is loaded by `typography.css`.

---

## Icons

Material Icons SVGs sourced from Google Fonts. See [`assets-icons.md`](assets-icons.md) for the full list.

---

## Logo

`logo/logo.svg` — application logo, referenced in the toolbar layout.

---

## JavaScript

All three files register functions on the shared `window.dash_clientside.clientside` namespace using `Object.assign(...)`. This is the Dash convention for clientside callbacks — Python code in `app.py` / page modules wires up these functions by referencing `ClientsideFunction("clientside", "<functionName>")`.

---

### `clientside_export.js`

#### `copyShareLink(n_clicks, pathname, budgetId, viewby, spendingType, unit, selectedId, nodeMap)`

Builds a shareable URL encoding the current filter state and copies it to the clipboard.

1. Constructs a `URLSearchParams` object from `budget_id`, `viewby`, `spending_type`, `unit`, and optionally `focus`.
2. If a `selectedId` is present, looks it up in `nodeMap` (a dict of `{ [pathId]: { dimension_id, ... } }`) and uses the integer `dimension_id` as the `focus` parameter rather than the full path string. This keeps URLs short and stable across language changes.
3. Writes the URL to the clipboard via `navigator.clipboard.writeText`, falling back to a hidden `<textarea>` + `execCommand('copy')` for environments where the Clipboard API is unavailable.
4. Returns a status string that Dash writes to a dummy output component's `title` attribute.

#### `downloadPlotImage(n_clicks, pathname, budgetId, budgetOptions, unit, spendingType)`

Downloads the currently visible Plotly chart as a high-DPI PNG.

1. **Identifies the target graph** by `pathname`: `/` → `#treemap-graph`, `/timeseries` → `#timeseries-graph`.
2. **Builds a filename** in the format `<prefix>_<YYYYMMDD_HHmmss>_<budgetName>_<unit>[_military].png`.
3. **Clones the Plotly SVG** (`svg.main-svg`), then:
   - Injects a `<style>` element that imports Source Sans 3 from Google Fonts and forces `font-family` on all `text`/`tspan` elements, so the exported image uses the same typeface as the screen.
   - Sets `font-family` attributes directly on every `text`/`tspan` node as a belt-and-suspenders measure.
   - Appends a watermark `<text>` in the bottom-right corner: `Stiftung Wissenschaft und Politik (SWP), <year> | CC BY 4.0`.
4. **Waits for fonts to load** using `document.fonts.load` (weights 400 and 600), falling back to a 500 ms timeout.
5. **Renders SVG → Canvas → PNG**: serialises the cloned SVG to a data URI, draws it onto a `<canvas>` at 2× scale with a white background, then calls `canvas.toBlob` and triggers a programmatic `<a download>` click.
6. Falls back to `Plotly.downloadImage` if the SVG element cannot be found.

---

### `clientside_treemap.js`

#### `findAndClickSlice(search, figure, nodeMap, language)`

Reads the `?focus=<value>` URL parameter and programmatically navigates the treemap to that node. Called by a Dash clientside callback whenever the URL search string or the figure changes.

**Node resolution:**

1. Parses `focus` from `URLSearchParams`.
2. If `focus` is a numeric string, treats it as a `dimension_id` and reverse-looks it up in `nodeMap`. Prefers the entry whose `.language` tag matches the active figure language (`RU` or `EN`), falling back to any match. This makes deep links work regardless of which language was active when the link was copied.
3. Bails early (no retries) if `figure.data[0].ids` is already populated and does not contain the resolved node — avoids 5 × 500 ms retries for nodes that simply are not present in the current view.

**Focus strategy (tried in order):**

1. `Plotly.restyle(plotDiv, { level: targetId }, [traceIndex])` — sets the treemap's visible root directly; most reliable and closest to a manual click.
2. `Plotly.Fx.click(plotDiv, { points: [...] })` — triggers Plotly's internal click handler.
3. DOM label matching — finds the `<g.slice>` whose `text` (normalised: strip `<br>`, collapse whitespace, lowercase) matches the figure label at the target index; picks the candidate with the smallest `left + top` bounding-box score to avoid nested duplicates.
4. `data-point-number` attribute lookup on `<g.slice>`.
5. DOM order fallback — takes the nth `<g.slice.cursor-pointer>` element.
6. Dispatches a full synthetic mouse sequence (`pointerover` … `click`) at a point well inside the tile's bounding box.

**Ancestor traversal (`focusSliceByIdSequential`):**

For deep nodes, builds a root-to-target ancestor path from the figure's `ids`/`parents` arrays and steps through it node by node, waiting for `plotly_afterplot` (with a 10 ms fallback timer) between each step. This mirrors what a user does when clicking into a nested slice manually.

**Retry loop:** if the DOM is not yet ready, polls up to 5 times at 500 ms intervals after an initial 300 ms delay.

#### `applyTreemapTextInset(figure)`

Prevents Plotly treemap labels from overflowing tile boundaries.

Plotly does not clip tile text — long labels spill into neighbouring tiles. This function runs after each figure update and compresses any label that is wider than `(tile width − 2 × 5 px inset)`.

**Algorithm:**

1. Waits for Plotly to finish rendering by polling for a `path.surface` element with a non-zero `getBBox().width` (up to 30 × 100 ms tries).
2. On first run, attaches a `MutationObserver` to `.treemaplayer` that watches for changes to `path[d]` attributes. Plotly rewrites these on every tile-click animation; the observer re-triggers `scheduleInset` immediately (for early correction) and again after the animation settles (1 ms debounce, for pixel-perfect final state).
3. For each `<g.slice>`:
   - Strips any previously appended `scale(…)` transform (stored in a `data-text-scale` attribute) so measurements are always taken against Plotly's unmodified transform.
   - Compares the text bounding rect against the tile bounding rect.
   - If the text overflows, computes a horizontal scale ratio and builds a `translate(anchor) scale(ratio,1) translate(-anchor)` transform anchored to the text's natural left edge. This compresses the text horizontally while keeping it visually anchored to its starting position.
   - Appends the scale transform to Plotly's existing SVG `transform` attribute (never replaces it).

---

### `clientside_ui.js`

#### `hideTreemapSpinner(style)` / `showTreemapSpinner()`

Show or hide `#treemap-spinner`. Called by Dash clientside callbacks triggered by graph style changes and filter interactions.

#### `hideTimeseriesSpinner(style)` / `showTimeseriesSpinner()`

Same pattern for `#timeseries-spinner`.

#### `adjustTimeseriesTicks(windowWidth, tickInfo, figure)`

Adapts quarterly x-axis tick labels on the timeseries chart to the available viewport width.

Only runs when `tickInfo` is non-null (i.e., a REPORT budget is selected and all periods are shown). Behaviour:

- **≥ 640 px** — every tick shows `YYYY-Qn` (e.g., `2023-Q3`).
- **< 640 px** — only Q1 ticks show the year; all other ticks are hidden (empty string), reducing label clutter on small screens.

To avoid stale `%{x}` hover labels when ticks are suppressed, the function rewrites each trace's `customdata` to store the full `YYYY-Qn` string in `customdata[1]` and replaces `%{x}` with `%{customdata[1]}` in the `hovertemplate`.

A cache key (`isNarrow + '|' + tickvals.join(',')`) prevents redundant figure re-renders when neither the data nor the narrow state has changed.
