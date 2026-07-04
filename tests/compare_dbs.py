"""Diff two budget.db versions: per-budget expense counts/totals and per-chapter sums.

Usage (from repo root):

    make test-compare-db prior=/tmp/prior.db
    # or directly:
    uv run --group dev python tests/compare_dbs.py <current.db> <prior.db>

Extract a prior version from git history with:

    git show <rev>:src/data/budget.db > /tmp/prior.db

Exits 1 if the databases differ, with a report naming each diverging budget.
"""

import sqlite3
import sys
from pathlib import Path

BUDGET_TOTALS_QUERY = """
    SELECT b.original_identifier, COUNT(e.id), COALESCE(SUM(e.value), 0)
    FROM budgets b LEFT JOIN expenses e ON e.budget_id = b.id
    GROUP BY b.original_identifier
"""

CHAPTER_SUMS_QUERY = """
    SELECT b.original_identifier, d.original_identifier, SUM(e.value)
    FROM expenses e
    JOIN budgets b ON b.id = e.budget_id
    JOIN association_table a ON a.expense_id = e.id
    JOIN dimensions d ON d.id = a.dimension_id
    WHERE d.type = 'CHAPTER'
    GROUP BY b.original_identifier, d.original_identifier
"""


def log(message: str) -> None:
    print(message)  # noqa: T201


def load(db_path: Path) -> tuple[dict, dict]:
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        totals = {
            budget: (count, round(total, 2))
            for budget, count, total in connection.execute(BUDGET_TOTALS_QUERY)
        }
        chapters = {
            (budget, chapter): round(total, 2)
            for budget, chapter, total in connection.execute(CHAPTER_SUMS_QUERY)
        }
    finally:
        connection.close()
    return totals, chapters


def diff_dicts(current: dict, prior: dict, label: str) -> int:
    differences = 0
    for key in sorted(current.keys() - prior.keys()):
        log(f"{label} only in current: {key} = {current[key]}")
        differences += 1
    for key in sorted(prior.keys() - current.keys()):
        log(f"{label} only in prior:   {key} = {prior[key]}")
        differences += 1
    for key in sorted(current.keys() & prior.keys()):
        if current[key] != prior[key]:
            log(f"{label} changed: {key}: prior {prior[key]} -> current {current[key]}")
            differences += 1
    return differences


def main() -> int:
    if len(sys.argv) != 3:
        log(__doc__ or "")
        return 2

    current_path, prior_path = Path(sys.argv[1]), Path(sys.argv[2])
    for path in (current_path, prior_path):
        if not path.exists():
            log(f"no such file: {path}")
            return 2

    current_totals, current_chapters = load(current_path)
    prior_totals, prior_chapters = load(prior_path)

    differences = diff_dicts(current_totals, prior_totals, "budget (count, total)")
    differences += diff_dicts(current_chapters, prior_chapters, "chapter sum")

    if differences:
        log(f"\n{differences} difference(s) between {current_path} and {prior_path}")
        return 1
    log(f"databases agree: {len(current_totals)} budgets, {len(current_chapters)} chapter sums")
    return 0


if __name__ == "__main__":
    sys.exit(main())
