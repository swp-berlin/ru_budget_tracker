# Customization Guide

A task-oriented guide for changing the dashboard's look — colors, fonts, theme, and toolbar
layout — without needing a deep background in Dash or Python. Each section names the exact
file and the value to edit. For a developer-oriented reference of the asset folder structure
itself, see [`docs/assets.md`](assets.md).

After any change described here, restart the dev server (`cd src && uv run python app.py`) and
reload the browser to see the result — there is no automated visual check for styling, so a
manual look is the only way to confirm a change is correct before committing it.

## Change a chapter's color in the treemap

Chapter colors (Education, Military, Healthcare, etc.) are defined in one place:
[`src/utils/definitions.py`](../src/utils/definitions.py), in the `_ColorsConfig` class
(starting around line 213). Each named constant is a hex color:

```python
MILITARY_GREEN: str = "#949d85"
EDUCATION_PURPLE: str = "#cdb4db"
```

Change the hex value to recolor that chapter everywhere it appears (treemap, legends, exports).
The mapping from official chapter code to color name lives just below, in
`color_mapping_chapters` (around line 264) — you only need to touch this if you're
reassigning which chapter uses which named color, not for a plain color swap.

There's also a `filler_colors` list (around line 242) used for lower-level program nodes that
don't have a fixed chapter color — edit that list the same way if you want to change the
"unassigned" palette.

## Change button and menu text colors

Text color for the toolbar (filter dropdowns, action buttons) is set in
[`src/assets/css/typography.css`](../src/assets/css/typography.css). The color `#333333`
appears in several rules (menu text around line 41, button text around line 84) — search and
replace it with a new hex value to recolor all toolbar text consistently.

The muted/disabled-button color (`#adb5bd`) is set separately, also in `typography.css`
(around line 105 and 113).

The loading spinner shown over the treemap while data loads has its own accent color, set in
[`src/assets/css/menu.css`](../src/assets/css/menu.css) around line 273:

```css
border-top-color: #6c757d;
```

## Switch the whole app between light and dark theme

The app currently uses the default Bootstrap 5 light theme. This is a single line in
[`src/app.py`](../src/app.py) (line 18):

```python
external_stylesheets=[dbc.themes.BOOTSTRAP],
```

Swap `dbc.themes.BOOTSTRAP` for another Dash Bootstrap Components theme constant, e.g.
`dbc.themes.DARKLY` for a dark theme, or `dbc.themes.CYBORG`. The full list of available themes
is in the [Dash Bootstrap Components theme gallery](https://www.dash-bootstrap-components.com/docs/themes/explorer/).
Note this changes app-wide styling (buttons, dropdowns, borders) — it does not affect the
treemap chapter colors above, which are controlled separately.

## Reorder or relabel toolbar buttons

The toolbar buttons (Timeseries, Share, Download image, Download CSV, Language toggle, About)
are defined as a list in [`src/layout.py`](../src/layout.py), inside the action-buttons
`dbc.Stack` (lines 137–231). Each button is one `dbc.Button(...)` block in that list — reorder
the blocks to change button order, or edit a button's `title=` text to change its tooltip.
Visible button labels (e.g. "Timeseries", "EN") are set via `html.Span(...)` inside the
button's children.

## Change the font

The app loads "Source Sans 3" from a local font file, declared in
[`src/assets/css/typography.css`](../src/assets/css/typography.css) (the `@font-face` block at
the top, lines 6–11). To use a different font:

1. Add the new font file under `src/assets/fonts/`.
2. Update the `@font-face` `src: url(...)` path to point to it.
3. Update the `font-family` value in the `* { font-family: ... }` rule (line 21) to match.

Note: Source Sans 3 is licensed under the SIL Open Font License — see
`src/assets/fonts/Source_Sans_3/OFL.txt` for the terms if you keep using it elsewhere.
