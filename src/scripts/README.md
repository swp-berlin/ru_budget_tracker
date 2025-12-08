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

```bash
# 1) Clean up corrupted xlsx/xls files
uv run python scripts/fix_corrupt_excel_files.py

# 2) Import budgets (laws + reports)
uv run python scripts/import.py budget --type all

# 3) Import totals (requires CHAPTER dims from law imports)
uv run python scripts/import.py totals data/import_files/raw/totals/totals_2026.xlsx

# 4) Import GDP (auto-discover from raw/conversion_tables/gdp/...)
uv run python scripts/import.py gdp

# 5) Run translation pipeline (translates unseen dimension names)
uv run python scripts/translations.py --batch-size 25
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

### Order of Import
When importing data, ensure that you import in the following order to maintain referential integrity:
1. Budgets
2. Dimensions
3. Expenses with Dimension Mappings

ConversionRates can be imported at any time as they do not have dependencies on other tables.

### Mapping Expenses to Dimensions
- `DimensionTypeLiteral`: Found in the [budget.py file](src/models/budget.py). Use to ensure the correct type is assigned to each dimension. Can be expanded as needed.
- `original_identifier`: Each dimension has a unique `original_identifier` that can be used to reference it when linking expenses.
- Relationships: The relationships between expenses and dimensions are defined in the SQLAlchemy models. Use these relationships to link expenses to their corresponding dimensions. Example can be found in the [`example_import_script.py`](src/scripts/example_import_script.py).
- Session Management: Use the provided SQLAlchemy session to add and commit changes to the database. Example usage is shown in the [`example_import_script.py`](src/scripts/example_import_script.py).
- Error Handling: Implement error handling to manage issues such as missing dimensions or data inconsistencies during the import process using try-except blocks and logging as demonstrated in the [`example_import_script.py`](src/scripts/example_import_script.py).
- Data Validation: Validate the data before importing into the database to ensure it meets the required format and constraints defined in the database schema. This could include directly using the SQLalchemy models for insertion
- Upsert Logic: Implement logic to handle existing records in the database to avoid duplicates. This can be done by using the `on_conflict_do_...` method provided by the sqlite dialect. You need to provide a unique key constraint for the relevant columns in the model definition for this to work. For reference see the [`example_import_script.py`](src/scripts/example_import_script.py).
