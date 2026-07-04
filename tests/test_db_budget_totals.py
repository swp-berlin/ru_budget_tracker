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


def test_every_frozen_budget_exists_in_db(db_connection: sqlite3.Connection) -> None:
    """One-directional: a blessed (frozen) budget disappearing is a failure.

    Budgets in the DB that are NOT in the fixture are tolerated — unblessed
    new data, listed by the quality report; bless via `make test-regen-frozen`
    after review.
    """
    db_identifiers = {
        row[0] for row in db_connection.execute("SELECT original_identifier FROM budgets")
    }
    missing = set(FROZEN_TOTALS) - db_identifiers
    assert not missing, f"frozen budgets missing from DB: {sorted(missing)}"


@pytest.mark.parametrize("identifier", sorted(FROZEN_TOTALS), ids=str)
def test_budget_totals_match_fixture(db_connection: sqlite3.Connection, identifier: str) -> None:
    expected = FROZEN_TOTALS[identifier]
    count, total = db_connection.execute(QUERY, (identifier,)).fetchone()
    assert count == expected["expense_count"], f"{identifier}: expense count changed"
    assert f"{total:.2f}" == expected["total_value"], f"{identifier}: total value changed"
