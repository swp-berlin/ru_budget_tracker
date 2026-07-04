"""Frozen per-budget totals: expense count and total value for EVERY budget in the DB.

Complements test_frozen_db.py (7 hand-picked dimension-join checks) with full
coverage: any budget whose imported content changes — or that appears/disappears —
fails a named test. Regenerate deliberately via `make test-regen-frozen`.
"""

import json
import sqlite3
from pathlib import Path

import pytest

pytestmark = pytest.mark.db

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "frozen_budget_totals.json"

QUERY = """
    SELECT COUNT(e.id), COALESCE(SUM(e.value), 0)
    FROM budgets b LEFT JOIN expenses e ON e.budget_id = b.id
    WHERE b.original_identifier = ?
"""


def _load_fixture() -> dict[str, dict]:
    with FIXTURE_PATH.open(encoding="utf-8") as f:
        return json.load(f)


FROZEN_TOTALS = _load_fixture()


def test_budget_set_matches_fixture(db_connection: sqlite3.Connection) -> None:
    """The exact set of budgets is pinned — imports may not silently add or drop one."""
    db_identifiers = {
        row[0] for row in db_connection.execute("SELECT original_identifier FROM budgets")
    }
    fixture_identifiers = set(FROZEN_TOTALS)
    assert db_identifiers == fixture_identifiers, (
        f"in DB but not fixture: {sorted(db_identifiers - fixture_identifiers)}; "
        f"in fixture but not DB: {sorted(fixture_identifiers - db_identifiers)} "
        f"(if intended, run `make test-regen-frozen`)"
    )


@pytest.mark.parametrize("identifier", sorted(FROZEN_TOTALS), ids=str)
def test_budget_totals_match_fixture(db_connection: sqlite3.Connection, identifier: str) -> None:
    expected = FROZEN_TOTALS[identifier]
    count, total = db_connection.execute(QUERY, (identifier,)).fetchone()
    assert count == expected["expense_count"], f"{identifier}: expense count changed"
    assert f"{total:.2f}" == expected["total_value"], f"{identifier}: total value changed"
