# Data

This directory holds the application database and the import pipeline inputs.

## Adding new data

See [`import_files/Readme.md`](import_files/Readme.md) for the full guide: how to obtain source files, where to place them, naming conventions, and which scripts to run.

## Database

The application uses **SQLite**. Three files make up the live database:

| File | Purpose |
|---|---|
| `budget.db` | Main database file — contains all tables, indexes, and stored data. |
| `budget.db-wal` | Write-Ahead Log — new writes are staged here before being checkpointed into the main file. Present whenever the database was last opened in WAL mode. |
| `budget.db-shm` | Shared-memory index for the WAL file — used by SQLite to coordinate concurrent readers. Always paired with `budget.db-wal`. |

WAL mode (`PRAGMA journal_mode=WAL`) is SQLite's recommended journal mode for applications with concurrent reads. The `-shm` and `-wal` files are created automatically and are part of the same logical database as `budget.db` — all three must be kept together and committed together if the database is under version control.

The `-shm` and `-wal` files are safe to delete when no process has the database open; SQLite will checkpoint and recreate them as needed.
