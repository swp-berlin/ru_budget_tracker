# Pages

Each file in this directory is a Dash multi-page app route registered via `register_page`.

## treemap.py — `/`

The home page. Renders an interactive Plotly treemap of Russia's federal budget. Supports filtering by spending type (all / military), unit (absolute RUB, PPP dollars, % of GDP, % of spending), view-by dimension (ministry / program), and language (RU / EN). Clicking a node stores the selection in a shared Dash store so the timeseries page can drill into the same dimension.

## timeseries.py — `/timeseries`

Renders a stacked bar chart of budget spending over time for the dimension selected in the treemap. Supports the same unit and spending-type filters plus a period filter (full year / Q1–Q4). Provides a CSV download of the currently displayed data.

## about.py — `/about`

Static informational page describing the project, its data sources, methodology (classified spending, military spending definition), and known limitations.
