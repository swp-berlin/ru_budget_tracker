# Customization Guide

A task-oriented guide for changing the dashboard's look — colors, fonts, theme, and toolbar
layout — without needing a deep background in Dash or Python. Each section names the exact
file and the value to edit. For a developer-oriented reference of the asset folder structure
itself, see [`docs/assets.md`](assets.md).

After any change described here, restart the dev server (`cd src && uv run python app.py`) and
reload the browser to see the result — there is no automated visual check for styling, so a
manual look is the only way to confirm a change is correct before committing it.

## Change a chapter's color in the treemap

All chart colors come from the SWP corporate-design palette — six hues (gold, green, teal,
blue, mauve, salmon) at three tints each — defined in one place:
[`src/utils/definitions.py`](../src/utils/definitions.py), in the `_ColorsConfig` class
(starting around line 213). Each slot is a named hex constant:

```python
BRAND_GREEN_DARK: str = "#699470"
BRAND_MAUVE_MID: str = "#C9A6B5"
```

To recolor a chapter, don't edit these hex values — that would change the brand color
everywhere it is used. Instead reassign which slot the chapter points at, in
`color_mapping_chapters` (around line 307), where each entry is annotated with the
chapter's name and its share of total spending:

```python
"07": self.BRAND_MAUVE_MID,  # Education, 5.2%
```

Slots are assigned by spending share rather than chapter number, deliberately. Fourteen
chapters is more than any palette can keep distinguishable by color alone, so the six dark
tints — the most separable steps available — go to the six largest chapters (~77% of
spending) and the light tints go to the smallest. If you reassign slots, keep that
principle: give the darkest tints to the biggest chapters, or large neighbouring areas of
the treemap will become hard to tell apart. Two chapters must never share a slot.

## Change the colors in the treemap's program view

Programs have no fixed color assignment the way chapters do — there are 60–80 top-level
programs in a typical budget year and only 18 palette slots, so colors here separate
neighbouring tiles rather than identify a category. The palette is the `filler_colors` list
in the same file (around line 261): the same six hues, flattened, **dark tints first, then
mid, then light**.

Slots are handed out by spending rank. `create_treemap_colors` in
[`src/callbacks/helper.py`](../src/callbacks/helper.py) ranks the top-level programs by
value, largest first, and gives rank *n* the slot at `n % 18`. Two consequences worth
knowing before you change anything:

- The 18 largest programs always get 18 different colors, and any two programs sharing a
  slot are at least 18 ranks apart — which is what keeps same-colored tiles from landing
  next to each other. (The previous CRC32-hash assignment put 14–19 same-color pairs within
  5 ranks of each other in every budget year.)
- **The order of `filler_colors` is load-bearing.** Reordering or inserting entries
  repaints every program node, and moving a light tint to the front would hand the biggest
  tiles the least separable colors. If you edit the list, keep the dark six first.

A program's whole subtree inherits its top-level color, so each program reads as one block.
Because rank drives the color, a program can change color when you switch budget year or
toggle "Military only" — its rank moved. Colors do *not* change with the EN/RU language
toggle: ranking is keyed on the language-agnostic `orig_id`.

## Change the label text color on treemap tiles

Tile labels are not a single color. `TEXT_ON_LIGHT` (`#444444`) and `TEXT_ON_DARK`
(`#ffffff`) are defined in `_ColorsConfig` (around line 254), and
`create_treemap_text_colors` in [`src/callbacks/helper.py`](../src/callbacks/helper.py)
picks between them per tile: any tile filled with one of the six dark tints gets white
text, everything else gets dark gray.

This is a contrast requirement, not a taste call — `#444444` on the dark tints measures
2.7–2.9:1, below the WCAG 3:1 large-text threshold, while white measures 3.4–3.6:1 and
clears it. The set of fills treated as "dark" is the `dark_fills` property (around line
284); if you promote another slot to a dark tint, add it there too or its labels will stay
gray. The `font=dict(...)` color in
[`src/callbacks/callback_treemap.py`](../src/callbacks/callback_treemap.py) is only the
fallback for the pathbar and title — changing it will not affect tile labels.

## Change the timeseries chart colors

The stacked bars on the timeseries page get their colors from `color_discrete_map` in
[`src/callbacks/callback_timeseries.py`](../src/callbacks/callback_timeseries.py) (around
line 153):

```python
color_discrete_map={
    "OPEN": Colors.BRAND_BLUE_DARK,
    "CLASSIFIED": Colors.CLASSIFIED_GRAY,
},
```

Use a `Colors.BRAND_*` constant rather than a literal hex so the chart stays on brand.
Classified spending deliberately uses the same gray as the treemap's classified tiles —
the grays sit outside the brand palette precisely because they mark nodes with no category
identity, so keep those two in sync if you change either.

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
