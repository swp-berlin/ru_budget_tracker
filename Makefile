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

# Import a totals file (monthly or annual aggregates).
# Requires: totals=<path to xlsx or csv>
# Example (report totals): make import-totals totals=data/import_files/raw/totals/total_report_2026.xlsx
# Example (law totals):    make import-totals totals=data/import_files/raw/totals/total_law_2026.csv
import-totals:
	@test -n "$(totals)" || (echo "Usage: make import-totals totals=<path>"; exit 1)
	cd src && uv run python scripts/import.py totals $(totals) && cd -

# Import GDP conversion data (auto-discovers Rosstat + Minekonom files under data/import_files/raw/).
import-gdp:
	cd src && uv run python scripts/import.py gdp && cd -

# Import PPP conversion data from the World Bank API (falls back to CSV cache on failure).
import-ppp:
	cd src && uv run python scripts/import.py ppp && cd -

# Run the translation pipeline to translate unseen dimension names.
# Translates in batches of 25 by default.
import-translations:
	cd src && uv run python scripts/translations.py --batch-size 25 && cd -
