# =============================================================================
# DEFAULT PATHS
# =============================================================================

DB_FILE ?= src/data/budget.db
DB_WAL_FILE ?= $(DB_FILE)-wal
DB_SHM_FILE ?= $(DB_FILE)-shm
TOTALS_REPORT_FILE ?= data/import_files/raw/totals/total_report_2026.xlsx
TOTALS_LAW_FILE ?= data/import_files/raw/totals/total_law_2026.csv

.PHONY: \
	alembic-upgrade \
	alembic-revision \
	alembic-downgrade \
	reset-db \
	rebuild-db \
	import-fix \
	import-budget \
	import-totals \
	import-totals-report \
	import-totals-law \
	import-totals-all \
	import-gdp \
	import-ppp \
	import-translations \
	import-all-core \
	import-all \
	bootstrap-data \
	test-frozen-db

# =============================================================================
# DATABASE MIGRATIONS
# =============================================================================

# Apply all pending Alembic migrations to bring the database up to date.
alembic-upgrade:
	cd src && uv run alembic upgrade head && cd -

# Generate a new Alembic migration revision based on model changes.
# Usage: make alembic-revision m="description" rev-id="0001"
# Example: make alembic-revision m="add conversion rate table" rev-id="0005"
alembic-revision:
	cd src && uv run alembic revision --autogenerate -m "$(m)" --rev-id "$(rev-id)" && cd -

# Roll back the most recent Alembic migration.
alembic-downgrade:
	cd src && uv run alembic downgrade -1 && cd -

# Remove the local SQLite database and WAL sidecars.
# Ensure no app, shell, or container is holding the database open.
reset-db:
	rm -f $(DB_FILE) $(DB_WAL_FILE) $(DB_SHM_FILE)

# Recreate the database schema from scratch via Alembic.
rebuild-db: reset-db alembic-upgrade

# =============================================================================
# DATA IMPORT
# Run steps in order: fix → budget → totals → gdp → ppp → translations
# =============================================================================

# Fix corrupt xlsx/xls files before importing.
# Run this once before any import step.
import-fix:
	cd src && uv run python scripts/fix_corrupt_excel_files.py && cd -

# Import all budget law and report files (auto-discovers files under data/import_files/clean/).
# Optionally filter by year: make import-budget years="2023 2024"
import-budget:
	cd src && uv run python scripts/import.py budget --type all $(if $(years),--years $(years),) && cd -

# Import a specific totals file.
# Example (report totals): make import-totals totals=data/import_files/raw/totals/total_report_2026.xlsx
# Example (law totals):    make import-totals totals=data/import_files/raw/totals/total_law_2026.csv
import-totals:
	@test -n "$(totals)" || (echo "Usage: make import-totals totals=<path>"; exit 1)
	cd src && uv run python scripts/import.py totals $(totals) && cd -

# Import default monthly report totals.
import-totals-report:
	cd src && uv run python scripts/import.py totals $(TOTALS_REPORT_FILE) && cd -

# Import default yearly law totals.
import-totals-law:
	cd src && uv run python scripts/import.py totals $(TOTALS_LAW_FILE) && cd -

# Import both default totals files.
import-totals-all: import-totals-report import-totals-law

# Import GDP conversion data (auto-discovers Rosstat + Minekonom files under data/import_files/raw/).
import-gdp:
	cd src && uv run python scripts/import.py gdp && cd -

# Import PPP conversion data from the World Bank API (falls back to CSV cache on failure).
import-ppp:
	cd src && uv run python scripts/import.py ppp && cd -

# Run the translation pipeline to translate unseen dimension names.
# Translates in batches of 25 by default.
# Requires OPENAI_API_KEY to be set in the environment.
# OPENAI_API_KEY is not loaded from .env when run locally but might work when set explicitly in the environment or in a container.
import-translations:
	cd src && uv run python scripts/translations.py --batch-size 25 && cd -

# Import all required data except translations.
import-all-core: import-fix import-budget import-totals-all import-gdp import-ppp

# Import the full dataset, including translations.
import-all: import-all-core import-translations

# Reset the local database, rerun migrations, then import the full dataset.
bootstrap-data: rebuild-db import-all

# Validate a small set of frozen reference values against the final SQLite database.
test-frozen-db:
	uv run --group dev pytest tests/test_frozen_db.py -q
