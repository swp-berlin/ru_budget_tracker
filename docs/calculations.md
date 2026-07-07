# Calculations

`src/utils/calculate.py` converts raw expense values (stored in RUB) into
whatever unit the user picked in the unit selector. This document describes
the workflow behind each unit and the denominators it depends on.

## Entry point

Callbacks (`callbacks/callback_treemap.py`, `callbacks/callback_timeseries.py`)
build one `Calculator` per `(unit, budget_id, date, budget_type)` and call
either:

- `calculate(value)` — a single float (treemap uses this per parent/child sum).
- `calculate_series(series)` — a whole `pd.Series` at once (used for
  timeseries bar values and treemap `VALUE` columns).

`date` and `budget_type` matter because the denominators below (GDP, total
spending, total revenue) are looked up per year, and REPORT budgets need
special year-to-date handling that LAW budgets don't.

## Units

### `ABSOLUTE`

No lookup. Divides the raw RUB value by `1_000_000_000` to get billions of RUB.

### `DOLLARS`

Divides the raw value by a RUB→PPP conversion rate (`ConversionRate` rows
named `ppp_%`, valid for the `date`'s year), then by `1_000_000_000` to get
billions of PPP dollars.

### `PERCENT_GDP_FULL_YEAR` / `PERCENT_GDP_YEAR_TO_DATE`

Percentage of GDP for the year. The denominator is fetched from
`ConversionRate` rows named `gdp%`:

- **Full year**: sums the full-year GDP entries (`started_at`/`ended_at`
  span Jan 1–Dec 31) for the date's year.
- **Year-to-date**: sums only the quarterly GDP entries (`%_q_%`) up to the
  current period. LAW budgets always use all four quarters (LAW budgets are
  yearly, published at the start of the year). REPORT budgets use the
  quarters implied by the period's month (e.g. a June REPORT uses Q1+Q2).

### `PERCENT_FULL_YEAR_SPENDING` / `PERCENT_YEAR_TO_DATE_SPENDING`

Percentage of total government spending. The denominator comes from the
`TOTAL`/`EXPENSE` budget (`Budget.original_identifier LIKE '%-EXPENSE-%'`),
excluding rows with dimensions (so only the grand total is counted):

- **LAW**: uses the `YEARLY`-scope total for the date's year, scaled by
  `budget_config.law_total_value_multiplier` (LAW totals are stored in
  thousands in the source data).
- **REPORT**: uses `MONTHLY`-scope totals published in quarter-end months
  (`budget_config.quarterly_months`). `PERCENT_FULL_YEAR_SPENDING` takes the
  latest available cumulative total. `PERCENT_YEAR_TO_DATE_SPENDING` matches
  the total by month and, for Q2 onward, subtracts the previous quarter's
  cumulative total so the result reflects only that quarter's spending
  rather than the year-to-date cumulative figure. Matching is done by month
  rather than exact date because REPORT and `TOTAL`/`EXPENSE` budgets for
  the same quarter can be published on different dates.

### `PERCENT_YEAR_TO_DATE_REVENUE`

Percentage of year-to-date government revenue. The denominator comes from
the `TOTAL`/`REVENUE` budget (`Budget.original_identifier LIKE '%-REVENUE-%'`),
restricted to quarter-end publications, excluding rows with dimensions:

- **LAW**: uses the latest available quarter's cumulative total for the
  date's year.
- **REPORT**: matches by month and, for Q2 onward, subtracts the previous
  quarter's cumulative total (same de-cumulation logic as spending, and for
  the same reason — matching by exact date would miss rows).

If no revenue budgets exist for the year at all, the denominator is `0.0` and
callers treat that as "no revenue data" (`_percentage_revenue` raises
`ValueError`, which the timeseries callback catches and drops those rows —
see `_calculate_values` in `callbacks/callback_timeseries.py`).

## Caching

Every denominator lookup (conversion rate, GDP, spending, revenue) is cached
in a `ClassVar` dict on `Calculator`, keyed by the relevant subset of
`(unit, budget_type, date)`. This means repeated calculations across a
chart's many data points — same year, same budget type — hit the database
once per unique key instead of once per row. `Calculator.clear_caches()`
resets all four caches (used in tests, or when underlying data changes).

`_fetch_spending_budgets()` and `_fetch_revenue_budgets()` (the raw DB
queries backing the spending/revenue caches) are additionally wrapped in
`functools.lru_cache`, since they're called once per unique `budget_scope`
regardless of date.
