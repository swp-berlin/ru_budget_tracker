# `src/utils/`

Shared utilities for the budget tracker backend. All modules in this folder are pure helpers — no route definitions, no Dash callbacks.

## Files

### `definitions.py`
Central source of truth for types, constants, and configuration.

- **Type literals** — `BudgetTypeLiteral`, `UnitTypeLiteral`, `SpendingTypeLiteral`, etc. Used as type annotations across the codebase.
- **`BudgetConfig`** — immutable constants for data quirks (value multipliers, quarterly months).
- **UI option configs** — `ViewByConfig`, `UnitConfig`, `PeriodConfig`, `SpendingTypeConfig` — each holds dropdown `options` tuples and a `map` dict for label lookups.
- **`MilitarySpending`** — regex patterns (Python and SQL variants) used to classify expenses as military, both for simple single-dimension matches and multi-dimension combination rules.
- **`Colors`** — hex color constants and chapter/program color mappings for charts.

### `calculate.py`
`Calculator` class — converts raw expense values into the unit selected by the user (absolute RUB, PPP dollars, % of GDP, % of spending, % of revenue). Fetches conversion rates, GDP, spending, and revenue denominators from the database with class-level caching. See [`calculations.md`](calculations.md) for the per-unit formulas.

### `fetch_treemap.py`
`TreemapDataFetcher` class — queries the database for a single budget's expenses and dimension hierarchy, classified spending (from pre-computed DB views), and the recursive program hierarchy. Returns the raw rows that `transform_treemap.py` will shape into a DataFrame.

Also exposes `fetch_budgets_for_dropdown()` (used by the sidebar) and `_execute_query()` (shared by `fetch_timeseries.py`).

### `fetch_timeseries.py`
`TimeseriesDataFetcher` class — queries budget expenses across all years for bar-chart (timeseries) visualization. Handles the LAW vs. REPORT split, classified spending via pre-computed military views, and optional dimension-filtered drill-down queries.

### `transform_treemap.py`
`TreemapTransformer` class — converts raw DB rows into a flat Pandas DataFrame suitable for Plotly's treemap figure. Builds the full dimension path hierarchy (ministry → chapter → subchapter → program), assigns military flags, appends synthetic classified-spending rows, and wraps long labels.

### `transform_timeseries.py`
`TimeseriesTransformer` class — converts raw budget rows into a Pandas DataFrame for the bar chart. De-cumulates quarterly REPORT values (Q2 = cumulative Q2 − Q1) and splits each period into open + classified bars.
