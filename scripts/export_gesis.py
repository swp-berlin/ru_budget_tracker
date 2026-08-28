#!/usr/bin/env python3
"""Export LAW and REPORT expense observations from the built SQLite database."""

import argparse
import csv
import sqlite3
from pathlib import Path


DIMENSION_TYPES = ("MINISTRY", "CHAPTER", "SUBCHAPTER", "PROGRAM", "EXPENSE_TYPE")

COLUMNS = (
    "expense_id",
    "budget_identifier",
    "budget_type",
    "budget_scope",
    "budget_name",
    "budget_description",
    "period_start",
    "year",
    "value_rub",
    "ministry_code",
    "ministry_name",
    "ministry_name_en",
    "chapter_code",
    "chapter_name",
    "chapter_name_en",
    "subchapter_code",
    "subchapter_name",
    "subchapter_name_en",
    "program_code",
    "program_name",
    "program_name_en",
    "expense_type_code",
    "expense_type_name",
    "expense_type_name_en",
)

QUERY = """
SELECT
    e.id,
    b.original_identifier,
    b.type,
    b.scope,
    b.name,
    b.description,
    b.published_at,
    CAST(strftime('%Y', b.published_at) AS INTEGER),
    e.value,
    ministry.original_identifier, ministry.name, ministry.name_translated,
    chapter.original_identifier, chapter.name, chapter.name_translated,
    subchapter.original_identifier, subchapter.name, subchapter.name_translated,
    program.original_identifier, program.name, program.name_translated,
    expense_type.original_identifier, expense_type.name, expense_type.name_translated
FROM expenses AS e
JOIN budgets AS b ON b.id = e.budget_id
JOIN association_table AS ministry_link ON ministry_link.expense_id = e.id
JOIN dimensions AS ministry
    ON ministry.id = ministry_link.dimension_id AND ministry.type = 'MINISTRY'
JOIN association_table AS chapter_link ON chapter_link.expense_id = e.id
JOIN dimensions AS chapter
    ON chapter.id = chapter_link.dimension_id AND chapter.type = 'CHAPTER'
JOIN association_table AS subchapter_link ON subchapter_link.expense_id = e.id
JOIN dimensions AS subchapter
    ON subchapter.id = subchapter_link.dimension_id AND subchapter.type = 'SUBCHAPTER'
JOIN association_table AS program_link ON program_link.expense_id = e.id
JOIN dimensions AS program
    ON program.id = program_link.dimension_id AND program.type = 'PROGRAM'
JOIN association_table AS expense_type_link ON expense_type_link.expense_id = e.id
JOIN dimensions AS expense_type
    ON expense_type.id = expense_type_link.dimension_id AND expense_type.type = 'EXPENSE_TYPE'
WHERE b.type IN ('LAW', 'REPORT')
ORDER BY b.published_at, b.type, e.id
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path("src/data/budget.db"))
    parser.add_argument(
        "--output", type=Path, default=Path("src/data/gesis_export/expenses.csv")
    )
    return parser.parse_args()


def validate_dimensions(connection: sqlite3.Connection) -> None:
    query = """
        SELECT e.id, d.type, COUNT(*)
        FROM expenses AS e
        JOIN budgets AS b ON b.id = e.budget_id
        LEFT JOIN association_table AS a ON a.expense_id = e.id
        LEFT JOIN dimensions AS d ON d.id = a.dimension_id AND d.type = ?
        WHERE b.type IN ('LAW', 'REPORT')
        GROUP BY e.id
        HAVING COUNT(d.id) != 1
        LIMIT 1
    """
    for dimension_type in DIMENSION_TYPES:
        invalid = connection.execute(query, (dimension_type,)).fetchone()
        if invalid:
            raise RuntimeError(
                f"expense {invalid[0]} has {invalid[2]} dimensions of type {dimension_type}"
            )


def export(database: Path, output: Path) -> int:
    if not database.is_file():
        raise FileNotFoundError(f"database not found: {database}")

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = output.with_suffix(output.suffix + ".tmp")
    database_uri = database.resolve().as_uri() + "?mode=ro"

    with sqlite3.connect(database_uri, uri=True) as connection:
        validate_dimensions(connection)
        with temporary_output.open("w", encoding="utf-8", newline="") as csv_file:
            writer = csv.writer(csv_file, lineterminator="\n")
            writer.writerow(COLUMNS)
            row_count = 0
            for row in connection.execute(QUERY):
                writer.writerow(row)
                row_count += 1

    temporary_output.replace(output)
    return row_count


def main() -> None:
    args = parse_args()
    row_count = export(args.database, args.output)
    print(f"Exported {row_count:,} expense rows to {args.output}")  # noqa: T201


if __name__ == "__main__":
    main()
