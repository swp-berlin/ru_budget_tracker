# Data

This directory holds the application database and the import pipeline inputs.

## Adding new data

See [`data-import-files.md`](data-import-files.md) for the full guide: how to obtain source files, where to place them, naming conventions, and which scripts to run.

## Database

The application uses **SQLite**. Three files make up the live database:

| File | Purpose |
|---|---|
| `budget.db` | Main database file — contains all tables, indexes, and stored data. |
| `budget.db-wal` | Write-Ahead Log — new writes are staged here before being checkpointed into the main file. Present whenever the database was last opened in WAL mode. |
| `budget.db-shm` | Shared-memory index for the WAL file — used by SQLite to coordinate concurrent readers. Always paired with `budget.db-wal`. |

WAL mode (`PRAGMA journal_mode=WAL`) is SQLite's recommended journal mode for applications with concurrent reads. The `-shm` and `-wal` files are created automatically and are part of the same logical database as `budget.db` — all three must be kept together and committed together if the database is under version control.

The `-shm` and `-wal` files are safe to delete when no process has the database open; SQLite will checkpoint and recreate them as needed.

## Why is the database so large?

`budget.db` holds the complete dataset: budget laws and quarterly execution reports
from 2018 onward, RU→EN translations for every budget dimension, plus GDP/PPP and
conversion-rate tables (see [`data-import-files.md`](data-import-files.md) for
what each import step adds). That raw dataset is the baseline size.

On top of that baseline, the database is deliberately made *bigger* by its own
caching layer. Tables like `treemap_expense_hierarchy` and
`timeseries_budget_summary` don't hold source data — they hold precomputed,
denormalized aggregations derived from `expenses` and `dimensions`. Every row in
those tables is redundant with data that already exists elsewhere in the database;
it's stored again so that the app never has to recompute it on the fly. This is a
deliberate size-for-speed tradeoff: disk space is cheap, so the database is allowed
to grow in exchange for turning expensive multi-table joins and aggregations into a
single indexed lookup at request time.

## Performance work

Beyond the caching tables above, the dashboard's SQLite setup is tuned end-to-end so
that the growing dataset doesn't translate into slower page loads:

- **Connection-level tuning** (`src/database/sessions.py`): `synchronous=NORMAL`
  relaxes disk-sync guarantees the app doesn't need for read-heavy traffic, a 64MB
  `cache_size` keeps hot pages in memory, `temp_store=MEMORY` keeps SQLite's
  temporary sort/join buffers off disk, and a 256MB `mmap_size` lets SQLite read
  large tables directly from the OS page cache instead of issuing normal file reads.
  `PRAGMA optimize` runs once on first connect so the query planner has fresh
  statistics before serving traffic.
- **WAL mode**: as noted above, `journal_mode=WAL` lets readers keep querying while
  writes are staged in `budget.db-wal`, instead of blocking on a shared lock.
- **Precomputed cache tables**: the `treemap_expense_hierarchy` and
  `timeseries_budget_summary` tables (see above) turn the app's heaviest queries —
  hierarchical treemap aggregation and time-series summarization — into a single
  indexed read instead of a live join/aggregate over the full `expenses` table.
- **In-process cache warming**: on startup, `src/app.py` pre-warms the treemap and
  timeseries caches in background threads and keeps frequently-used lookups (like the
  budget dropdown list) in an `lru_cache`, so the first real user request doesn't pay
  the cold-cache cost. Because the app can run with multiple gunicorn workers, a
  `post_fork` hook coordinates this warming so each worker ends up with a consistent
  cache and database connection state.
- **Response payload size**: independent of the database, the treemap's client-side
  payload and JavaScript were trimmed down, since a large database only helps if the
  browser can also render the result quickly.
