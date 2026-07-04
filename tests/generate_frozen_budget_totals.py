"""Regenerate tests/fixtures/frozen_budget_totals.json from the current budget.db.

Run from the repo root:

    uv run --group dev python tests/generate_frozen_budget_totals.py

The fixture pins expense count and total value for EVERY budget in the DB.
Only regenerate deliberately after a re-import whose changes are understood;
the commit message must explain why the numbers changed (see tests/README.md).
"""

import json
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = REPO_ROOT / "src" / "data" / "budget.db"
FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "frozen_budget_totals.json"

QUERY = """
    SELECT b.original_identifier, COUNT(e.id), COALESCE(SUM(e.value), 0)
    FROM budgets b LEFT JOIN expenses e ON e.budget_id = b.id
    GROUP BY b.original_identifier
    ORDER BY b.original_identifier
"""


def main() -> None:
    connection = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        rows = connection.execute(QUERY).fetchall()
    finally:
        connection.close()

    totals = {
        identifier: {"expense_count": count, "total_value": f"{total:.2f}"}
        for identifier, count, total in rows
    }

    FIXTURE_PATH.parent.mkdir(exist_ok=True)
    with FIXTURE_PATH.open("w", encoding="utf-8") as f:
        json.dump(totals, f, indent=2, ensure_ascii=False, sort_keys=True)
        f.write("\n")
    print(f"wrote {len(totals)} budgets to {FIXTURE_PATH}", file=sys.stderr)  # noqa: T201


if __name__ == "__main__":
    main()
