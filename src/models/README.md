# Data Model

The current database schema is visualized in the
[Database Schema Overview](../../README.md#database-schema-overview)
using a Mermaid ER diagram.

All models use SQLAlchemy 2.0-style `Mapped` / `mapped_column()` declarations. View-backed models carry `__table_args__ = {"info": {"is_view": True}}` so they are excluded from `Base.metadata.create_all()`; their underlying views are managed by Alembic.

---

## Writable Table Models

### Budgets

`Budget` (`budgets` table) represents a budget entry. Key fields:

| Field | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `original_identifier` | str | Identifier from the source data; indexed |
| `name` / `name_translated` | str | Russian name and English translation |
| `description` / `description_translated` | text (nullable) | |
| `type` | str | `DRAFT`, `LAW`, `REPORT`, or `TOTAL`; indexed |
| `scope` | str (nullable) | `YEARLY`, `QUARTERLY`, or `MONTHLY` |
| `published_at` | date | First day of the relevant period; indexed |
| `planned_at` | date (nullable) | First day of the period the budget was planned in |
| `created_at` / `updated_at` | datetime | Audit timestamps |

The `expenses` relationship is declared with `lazy="noload"` (not auto-loaded).

#### TOTAL Budgets

A `TOTAL` budget represents actual spending published retrospectively. Differences between planned, published and actual figures are computed by comparing `TOTAL` budgets with `LAW` or `REPORT` budgets of the same period.

#### Usage

- **Import / upsert:** `src/scripts/import.py` — budgets are merged into the session via `session.merge()`.
- **Queries:**
  - `src/utils/fetch_treemap.py` — fetches budgets for dropdown menus (filtered by type, excluding `TOTAL`), and looks up the corresponding `TOTAL` budget for a given year/month.
  - `src/utils/fetch_timeseries.py` — fetches `LAW` and `REPORT` budgets filtered by `published_at`.
- **Sanity checks:** `src/scripts/sanity_check.py`, `src/scripts/sanity_check_dimensions.py`.
- **Test data:** `src/scripts/mock_data/populate_database.py`.

---

### Expenses

`Expense` (`expenses` table) represents a single line-item in Russian rubles.

| Field | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `budget_id` | int FK → `budgets.id` | `CASCADE` delete; indexed |
| `value` | float | Amount in Russian rubles |
| `created_at` / `updated_at` | datetime | Audit timestamps |

Relationships:
- `dimensions` — many-to-many via `association_table`; `lazy="noload"`.
- `budget` — many-to-one back to `Budget`; `lazy="selectin"`, `viewonly=True`.

Helper property `expense_type` returns the `name` of the first dimension with `type == "EXPENSE_TYPE"`, or `None`.

#### Usage

- **Insert:** `src/scripts/import.py` — expenses are created with a `budget_id` and a list of `Dimension` objects attached via the association table.
- **Aggregation queries:**
  - `src/utils/fetch_treemap.py` — `func.sum(Expense.value)` grouped by dimension to build treemap data.
  - `src/utils/fetch_timeseries.py` — summed per budget and dimension for time-series charts.
- **Sanity checks:** `src/scripts/sanity_check.py`, `src/scripts/sanity_check_dimensions.py` — counts and sums joined through the association table.
- **Test data:** `src/scripts/mock_data/populate_database.py`.

---

### Dimensions

`Dimension` (`dimensions` table) describes one axis of an expense (e.g., ministry, chapter, program, expense type).

| Field | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `parent_id` | int FK → `dimensions.id` (nullable) | `SET NULL` on delete; indexed |
| `original_identifier` | str | Identifier from the source data |
| `type` | str | `MINISTRY`, `CHAPTER`, `PROGRAM`, `EXPENSE_TYPE`, etc.; indexed |
| `name` / `name_translated` | str | Russian name and English translation |

Unique constraint: `(name, type, original_identifier, parent_id)`.

Relationships:
- `parent` — self-referential to parent `Dimension`; `lazy="noload"`.
- `expenses` — many-to-many via `association_table`; `lazy="noload"`.

#### Usage

- **Upsert (three-step):** `src/scripts/import.py` — for each incoming dimension:
  1. Exact match on `(name, type, original_identifier, parent_id)` → skip.
  2. Match with `parent_id = NULL` → update to set correct parent.
  3. No match → insert new row.
- **Hierarchical queries:** `src/utils/fetch_timeseries.py` — recursive CTE to traverse ancestor/descendant chains.
- **Treemap queries:** `src/utils/fetch_treemap.py` — filtered by `type` and joined with expenses.
- **Test data:** `src/scripts/mock_data/populate_database.py`.

---

### Association Table (`association_table`)

`expense_dimension_association_table` is a SQLAlchemy `Table` object (not a mapped class) that backs the many-to-many relationship between `Expense` and `Dimension`.

| Column | Type | Notes |
|---|---|---|
| `expense_id` | int FK → `expenses.id` | Indexed |
| `dimension_id` | int FK → `dimensions.id` | Indexed |

A composite index `ix_assoc_expense_dimension` covers `(expense_id, dimension_id)` for efficient joins.

#### Usage

- **Implicit (via ORM):** accessed automatically when `Expense.dimensions` or `Dimension.expenses` is loaded.
- **Explicit JOINs:** `src/scripts/sanity_check.py`, `src/scripts/sanity_check_dimensions.py`, and `src/utils/fetch_timeseries.py` join against the table directly in complex aggregation queries.

---

### ConversionRates

`ConversionRate` (`conversion_rates` table) stores currency and GDP/PPP conversion factors.

| Field | Type | Notes |
|---|---|---|
| `name` | str PK | Format: `FROM_TO` (e.g., `RUB_USD`) or `gdp_YYYY_qN` / `ppp_YYYY` |
| `value` | float | Conversion factor |
| `started_at` / `ended_at` | date (nullable) | Validity period |
| `created_at` / `updated_at` | datetime | Audit timestamps |

#### Usage

- **Insert / upsert:** `src/scripts/import.py` — queries by `name` (PK), updates `value` if found, otherwise inserts.
- **Parsers:** `src/scripts/parsers/gdp_parser.py`, `src/scripts/parsers/ppp_parser.py` — construct `ConversionRate` objects that are later passed to the importer.

---

## View-Backed Read-Only Models

These models map to pre-computed database views managed by Alembic. They should never be written to directly.

### LawClassifiedSpendingPerChapter

View: `v_law_classified_spending_per_chapter`
Migration: `0004_add_view_law_classified_spending_per_chapter`

Classified spending per chapter for `LAW` budgets:

```
classified_spending = total_spending (TOTAL-LAW × 1000) − open_spending (LAW per chapter)
```

Primary key: `(year, original_identifier)`

Key columns: `chapter_name`, `chapter_name_translated`, `open_spending`, `total_spending`, `classified_spending`, `classified_share_of_budget`.

**Usage:** `src/utils/fetch_treemap.py` — queried by `year`, filtered to rows with `classified_spending > 0`, then LEFT-JOINed with `Dimension` to resolve the chapter dimension ID for treemap rendering.

---

### ReportClassifiedSpendingPerChapter

View: `v_report_classified_spending_per_chapter`
Migration: `0005_add_view_report_classified_spending_per_chapter`

Estimated classified spending per chapter for `REPORT` budgets. Only quarter-end months (3, 6, 9, 12) are included because `TOTAL` budgets are cumulative and only quarter boundaries are meaningful.

```
estimated_classified = total_budget_classified × law_classified_share
```

Primary key: `(year, month, original_identifier)`

Key columns: `quarter`, `open_spending`, `total_budget_classified`, `law_classified_share`, `chapter_classified_spending` (direct, NULL from 2022+), `estimated_classified_spending` (fallback).

**Usage:** `src/utils/fetch_treemap.py` — filtered by `(year, month)` with `.scalar_one_or_none()` to retrieve the total classified budget for a given reporting period.

---

### LawMilitaryOpenSpendingPerChapter

View: `v_law_military_open_spending_per_chapter`
Migration: `0006_add_view_law_military_open_spending_per_chapter`

Aggregates military open spending from `LAW` budgets per `(budget_id, chapter)`. Military expenses are identified by:
- `CHAPTER = '02'`
- `PROGRAM LIKE '31%'`
- `MINISTRY = '187'`
- `CHAPTER = '03' AND MINISTRY = '180'`

The 2018–2019 halving correction is applied.

Primary key: `(budget_id, original_identifier)`

Key columns: `open_spending`, `classified_spending` (chapters 02 and 10 only), `classified_share_of_budget`.

**Usage:** Imported in `src/utils/fetch_timeseries.py`.

---

### ReportMilitaryOpenSpendingPerChapter

View: `v_report_military_open_spending_per_chapter`
Migration: `0007_add_view_report_military_open_spending_per_chapter`

Same military filter as `LawMilitaryOpenSpendingPerChapter` but for `REPORT` budgets. Classified spending is estimated as:

```
classified_spending = total_budget_classified × law_classified_share
```

Primary key: `(budget_id, original_identifier)`

Key columns: `open_spending`, `classified_spending`, `classified_share_of_budget`.

**Usage:** `src/utils/fetch_treemap.py` — SUM aggregation by `budget_id` to compute total military classified spending and military share for the military-mode treemap visualization.

---

### MilitaryClassifiedSpendingPerChapter

View: `v_military_classified_spending_per_chapter`

Unified view combining `LAW` and `REPORT` military data, filtered to chapters 02 (National Defense) and 10 (Social Policy).

Primary key: `(budget_id, original_identifier)`

Key columns: `budget_type`, `published_at`, `open_spending`, `classified_spending` (direct; always set for LAW, set for REPORT 2018–2021), `estimated_classified_spending` (LAW-share fallback for REPORT 2022+).

**Usage:** Defined but not yet used in application code; available for future reporting and analytics.
