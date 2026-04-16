# Scripts

This directory contains various scripts used for development and maintenance of the project,
for example data import scripts.

## Table of Contents
- [Scripts](#scripts)
  - [Table of Contents](#table-of-contents)
  - [Importing Data](#importing-data)
    - [Order of Import](#order-of-import)
    - [Commands](#commands)

## Importing Data

To import data into the database, use [`import.py`](src/scripts/import.py).

Since some of the Excel files can be corrupt, run the fixer first:
[`fix_corrupt_excel_files.py`](src/scripts/fix_corrupt_excel_files.py).

### Order of Import
1. Fix Excel files
2. Import budgets (laws/reports)
3. Import totals (depends on chapter dimensions created by laws)
4. (Optional) Import GDP conversion data
5. Run translations

### Commands

All import steps are available as `make` targets from the project root. Run them in order:

```bash
# 1) Fix corrupt xlsx/xls files before importing
make import-fix

# 2) Import all budget laws and reports
make import-budget

# Optionally filter by year:
make import-budget years="2023 2024"

# 3) Import totals (report totals or law totals) — path is required
# Report totals (monthly budget execution, xlsx):
make import-totals totals=data/import_files/raw/totals/total_report_2026.xlsx

# Law totals (annual budget law, csv):
make import-totals totals=data/import_files/raw/totals/total_law_2026.csv

# 4) Import GDP conversion data (auto-discovers files under raw/conversion_tables/gdp/)
make import-gdp

# 5) Import PPP conversion data from World Bank API
make import-ppp

# 6) Run translation pipeline (translates unseen dimension names)
make import-translations

# translations.py also accepts flags directly:
# --batch-size N   Names per API call (default: 25)
# --workers N      Parallel API calls (default: 4)
# --dry-run        Preview without writing changes
# --force          Re-translate already-translated names
# --skip-db-update Only update CSV, skip database write
# --limit N        Translate only the first N names (for testing)
```

### Data Model
The SQLAlchemy models defining the database schema can be found in the [`src/models/`](src/models/) directory.
They are defined using SQLAlchemy's ORM capabilities, allowing for easy interaction with the database.
When writing import scripts, you can directly use these models to insert data into the database either by creating new instances  and adding them to the session or writing SQL statements.

The current database schema is visualized in the
[Database Schema Overview](../../README.md#database-schema-overview)
using a Mermaid ER diagram.

### SQL Queries
When writing functions to interact with the database, **always** use SQLAlchemy ORM methods to create statements/queries. **Do not** write raw SQL queries unless absolutely necessary. This ensures compatibility across different database backends and prevents SQL injection vulnerabilities.

### Referential Integrity
When importing data, maintain this order to satisfy foreign-key constraints:
1. Budgets
2. Dimensions
3. Expenses with Dimension Mappings

ConversionRates have no dependencies and can be imported at any time.

### Mapping Expenses to Dimensions
- `DimensionTypeLiteral`: Found in the [budget.py file](src/models/budget.py). Use to ensure the correct type is assigned to each dimension. Can be expanded as needed.
- `original_identifier`: Each dimension has a unique `original_identifier` that can be used to reference it when linking expenses.
- Relationships: The relationships between expenses and dimensions are defined in the SQLAlchemy models. Use these relationships to link expenses to their corresponding dimensions. Example can be found in the [`example_import_script.py`](src/scripts/example_import_script.py).
- Session Management: Use the provided SQLAlchemy session to add and commit changes to the database. Example usage is shown in the [`example_import_script.py`](src/scripts/example_import_script.py).
- Error Handling: Implement error handling to manage issues such as missing dimensions or data inconsistencies during the import process using try-except blocks and logging as demonstrated in the [`example_import_script.py`](src/scripts/example_import_script.py).
- Data Validation: Validate the data before importing into the database to ensure it meets the required format and constraints defined in the database schema. This could include directly using the SQLalchemy models for insertion
- Upsert Logic: Implement logic to handle existing records in the database to avoid duplicates. This can be done by using the `on_conflict_do_...` method provided by the sqlite dialect. You need to provide a unique key constraint for the relevant columns in the model definition for this to work. For reference see the [`example_import_script.py`](src/scripts/example_import_script.py).
