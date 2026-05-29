import json
import math
import sqlite3
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = REPO_ROOT / "src" / "data" / "budget.db"
FIXTURE_PATH = REPO_ROOT / "src" / "scripts" / "fixtures" / "frozen_db_values.json"


def _load_checks() -> list[dict]:
    with FIXTURE_PATH.open("r", encoding="utf-8") as fixture_file:
        return json.load(fixture_file)["checks"]


def _matches(actual, expected, tolerance: float | None) -> bool:
    if tolerance is None:
        return actual == expected
    if actual is None or expected is None:
        return actual == expected
    return math.isclose(float(actual), float(expected), abs_tol=tolerance, rel_tol=0.0)


def _case_id(check: dict) -> str:
    return str(check["name"])


@pytest.fixture(scope="session")
def db_connection() -> sqlite3.Connection:
    if not DB_PATH.exists():
        pytest.fail(f"Database file not found: {DB_PATH}")

    connection = sqlite3.connect(DB_PATH)
    try:
        yield connection
    finally:
        connection.close()


@pytest.mark.parametrize("check", _load_checks(), ids=_case_id)
def test_frozen_db_values(db_connection: sqlite3.Connection, check: dict) -> None:
    row = db_connection.execute(check["sql"]).fetchone()
    actual = row[0] if row else None
    expected = check["expected"]
    tolerance = check.get("tolerance")

    assert _matches(actual, expected, tolerance), (
        f"{check['name']} failed: expected {expected}, got {actual}"
    )