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
	import-rename \
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
	cd src && uv run python -m scripts.fix_corrupt_excel_files

# Import all budget law and report files (auto-discovers files under data/import_files/clean/).
# Optionally filter by year: make import-budget years="2023 2024"
import-budget:
	cd src && uv run python -m scripts.import budget --type all $(if $(years),--years $(years),) && cd -

# Import a specific totals file.
# Example (report totals): make import-totals totals=data/import_files/raw/totals/total_report_2026.xlsx
# Example (law totals):    make import-totals totals=data/import_files/raw/totals/total_law_2026.csv
import-totals:
	@test -n "$(totals)" || (echo "Usage: make import-totals totals=<path>"; exit 1)
	cd src && uv run python -m scripts.import totals $(totals) && cd -

# Import default monthly report totals.
import-totals-report:
	cd src && uv run python -m scripts.import totals $(TOTALS_REPORT_FILE) && cd -

# Import default yearly law totals.
import-totals-law:
	cd src && uv run python -m scripts.import totals $(TOTALS_LAW_FILE) && cd -

# Import both default totals files.
import-totals-all: import-totals-report import-totals-law

# Import GDP conversion data (auto-discovers Rosstat + Minekonom files under data/import_files/raw/).
import-gdp:
	cd src && uv run python -m scripts.import gdp && cd -

# Import PPP conversion data from the World Bank API (falls back to CSV cache on failure).
import-ppp:
	cd src && uv run python -m scripts.import ppp && cd -

# Run the translation pipeline to translate unseen dimension names.
# Translates missing dimension names via DeepL (cached in clean/translations/).
# Requires DEEPL_API_KEY in the environment. For scoped Pro keys also set
# DEEPL_SERVER_URL=https://api.deepl.com (the client misroutes them otherwise).
import-translations:
	cd src && uv run python -m scripts.translations --batch-size 50 && cd -

# Normalize dimension names for display (strip program prefixes, shorten "Russian Federation").
# Idempotent; run after translations so translated names are present.
import-rename:
	cd src && uv run python -m scripts.rename_dimensions && cd -

# Import all required data except translations.
import-all-core: import-fix import-budget import-totals-all import-gdp import-ppp

# Import the full dataset, including translations and name normalization.
import-all: import-all-core import-translations import-rename

# Reset the local database, rerun migrations, then import the full dataset.
bootstrap-data: rebuild-db import-all quality-report

# Generate the data-quality report (src/data/quality/report.{md,json}).
# Exit 1 only on ERROR-severity findings; WARNINGs (known source
# inconsistencies) are listed but do not fail.
quality-report:
	cd src && uv run python -m scripts.quality_report && cd -

# Download data from Nextcloud
download-data:
	cd src && uv run python -m importer && cd -

# This is a dirty workaround for a permission issue on the server
# It ensures group rw access which is required because differt users of the same group write to budget.db
fix-db-chmod:
	cd src && chmod 664 data/budget.*

# Download data from Nextcloud and bootstrap the database with the full dataset.
download-and-bootstrap-data: download-data bootstrap-data fix-db-chmod

# Validate a small set of frozen reference values against the final SQLite database.
test-frozen-db:
	uv run --group dev pytest tests/test_frozen_db.py -q

# Fast tiers only: pure-function unit tests + checks against the checked-in budget.db.
test-fast:
	uv run --group dev pytest -m "not golden and not e2e and not external" -q

# Everything runnable from a plain checkout (includes slow golden + e2e tiers, ~10 min).
test:
	uv run --group dev pytest -m "not external" -q

# Regenerate golden characterization files from the current parser output.
# Only do this deliberately; commit message must explain why the numbers changed.
test-regen-goldens:
	uv run --group dev python tests/generate_goldens.py

# Regenerate the frozen per-budget totals fixture from the current budget.db.
test-regen-frozen:
	uv run --group dev python tests/generate_frozen_budget_totals.py

# Diff per-budget expense counts/totals between the current budget.db and a prior one.
# Usage: make test-compare-db prior=/tmp/prior.db
# (extract a prior version with: git show <rev>:src/data/budget.db > /tmp/prior.db)
test-compare-db:
	@test -n "$(prior)" || (echo "Usage: make test-compare-db prior=<path-to-prior-db>" && exit 1)
	uv run --group dev python tests/compare_dbs.py src/data/budget.db $(prior)
