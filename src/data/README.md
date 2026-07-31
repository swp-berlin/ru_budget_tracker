# Data

This directory holds the application database and the import pipeline inputs.

## Adding new data

See [`import_files/Readme.md`](import_files/Readme.md) for the full guide: how to obtain source files, where to place them, naming conventions, and which scripts to run.

## Database

**`budget.db` is not version-controlled.** It is a build artifact: a fresh clone has no
database and must build one from the source files hosted on Nextcloud:

```bash
make download-and-bootstrap-data
```

This needs a `.env.importer` file with `NEXTCLOUD_DOWNLOAD_LINK` and `DEEPL_API_KEY`
(see [`../importer/README.md`](../importer/README.md)); the same target runs inside the
importer container (`Dockerfile.importer`) in deployment.

The application uses **SQLite**. Three files make up the live database:

| File | Purpose |
|---|---|
| `budget.db` | Main database file — contains all tables, indexes, and stored data. |
| `budget.db-wal` | Write-Ahead Log — new writes are staged here before being checkpointed into the main file. Present whenever the database was last opened in WAL mode. |
| `budget.db-shm` | Shared-memory index for the WAL file — used by SQLite to coordinate concurrent readers. Always paired with `budget.db-wal`. |

WAL mode (`PRAGMA journal_mode=WAL`) is SQLite's recommended journal mode for applications with concurrent reads. The `-shm` and `-wal` files are created automatically and are part of the same logical database as `budget.db` — all three belong together and must be copied or moved as a set. All three are gitignored.

The `-shm` and `-wal` files are safe to delete when no process has the database open; SQLite will checkpoint and recreate them as needed.
