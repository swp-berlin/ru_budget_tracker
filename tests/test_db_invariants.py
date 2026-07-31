"""Structural invariants of the imported database.

Where an ideal invariant is violated today, the CURRENT count is pinned
(marked `characterization`) so the suite passes now but screams on change.
Baselines verified 2026-07-03 against budget.db. Zero/one-dim expenses are by
design for totals budgets: one undimensioned grand total + chapter-only
expenses per totals budget.
"""

import hashlib
import re
import sqlite3

import pytest

from tests.golden_utils import law_files, report_files

pytestmark = pytest.mark.db

EXPECTED_DIMENSION_TYPES = ["CHAPTER", "EXPENSE_TYPE", "MINISTRY", "PROGRAM", "SUBCHAPTER"]

# sha256 over sorted "name|value" lines of conversion_rates (2026-07-04 baseline).
CONVERSION_RATES_SHA256 = "5ea0f60402477be923c45eecad364b7873aa7298a06fcbfcae3116171f4c73a2"


def one_value(db_connection: sqlite3.Connection, query: str) -> int:
    return db_connection.execute(query).fetchone()[0]


# ---------------------------------------------------------------------------
# Budget census
# ---------------------------------------------------------------------------


def test_budget_counts_by_type(db_connection: sqlite3.Connection) -> None:
    counts = dict(db_connection.execute("SELECT type, COUNT(*) FROM budgets GROUP BY type"))
    assert counts == {"LAW": 9, "REPORT": 33, "TOTAL": 209}


def test_law_and_report_budgets_match_files_on_disk(db_connection: sqlite3.Connection) -> None:
    """Every data file is imported and no imported budget lacks a source file."""
    expected = {f"LAW-{f.stem.split('_')[1]}" for f in law_files()}
    for f in report_files():
        match = re.match(r"report_(\d{4})_(\d{2})", f.name)
        assert match is not None
        expected.add(f"REPORT-{match.group(1)}-{match.group(2)}")

    in_db = {
        row[0]
        for row in db_connection.execute(
            "SELECT original_identifier FROM budgets WHERE type IN ('LAW', 'REPORT')"
        )
    }
    assert in_db == expected, (
        f"in DB without source file: {sorted(in_db - expected)}; "
        f"source file not imported: {sorted(expected - in_db)}"
    )


def test_global_counts(db_connection: sqlite3.Connection) -> None:
    assert one_value(db_connection, "SELECT COUNT(*) FROM expenses") == 217507
    assert one_value(db_connection, "SELECT COUNT(*) FROM dimensions") == 32351


def test_dimension_counts_by_type(db_connection: sqlite3.Connection) -> None:
    counts = dict(
        db_connection.execute("SELECT type, COUNT(*) FROM dimensions GROUP BY type ORDER BY type")
    )
    assert counts == {
        "CHAPTER": 15,
        "EXPENSE_TYPE": 125,
        "MINISTRY": 207,
        "PROGRAM": 31905,
        "SUBCHAPTER": 99,
    }


# ---------------------------------------------------------------------------
# Expense-dimension completeness
# ---------------------------------------------------------------------------


def test_zero_dimension_expenses_only_in_total_budgets(
    db_connection: sqlite3.Connection,
) -> None:
    counts = dict(
        db_connection.execute("""
            SELECT b.type, COUNT(*) FROM expenses e JOIN budgets b ON b.id = e.budget_id
            WHERE NOT EXISTS (SELECT 1 FROM association_table a WHERE a.expense_id = e.id)
            GROUP BY b.type
        """)
    )
    # characterization: each of the 209 TOTAL budgets has exactly one
    # undimensioned grand-total expense — by design (learnings.md).
    assert counts == {"TOTAL": 209}


def test_one_dimension_expenses_only_in_total_budgets(
    db_connection: sqlite3.Connection,
) -> None:
    counts = dict(
        db_connection.execute("""
            SELECT b.type, COUNT(*) FROM expenses e JOIN budgets b ON b.id = e.budget_id
            WHERE (SELECT COUNT(*) FROM association_table a WHERE a.expense_id = e.id) = 1
            GROUP BY b.type
        """)
    )
    # characterization: totals budgets' chapter expenses carry exactly one
    # CHAPTER dimension — by design (learnings.md baseline: 798).
    assert counts == {"TOTAL": 798}


@pytest.mark.parametrize("dimension_type", EXPECTED_DIMENSION_TYPES)
def test_every_law_and_report_expense_has_dimension_type(
    db_connection: sqlite3.Connection, dimension_type: str
) -> None:
    missing = db_connection.execute(
        """
        SELECT COUNT(*) FROM expenses e JOIN budgets b ON b.id = e.budget_id
        WHERE b.type IN ('LAW', 'REPORT') AND NOT EXISTS (
            SELECT 1 FROM association_table a JOIN dimensions d ON d.id = a.dimension_id
            WHERE a.expense_id = e.id AND d.type = ?
        )
        """,
        (dimension_type,),
    ).fetchone()[0]
    assert missing == 0, f"{missing} LAW/REPORT expenses lack a {dimension_type} dimension"


def test_no_expense_has_two_dimensions_of_same_type(
    db_connection: sqlite3.Connection,
) -> None:
    violations = one_value(
        db_connection,
        """
        SELECT COUNT(*) FROM (
            SELECT a.expense_id FROM association_table a
            JOIN dimensions d ON d.id = a.dimension_id
            GROUP BY a.expense_id, d.type HAVING COUNT(*) > 1
        )
        """,
    )
    assert violations == 0


# ---------------------------------------------------------------------------
# VR (expense type) granularity — protects the 2026-07-03 VR-filter flip
# ---------------------------------------------------------------------------


def test_law_expenses_use_only_aggregate_vr_codes(db_connection: sqlite3.Connection) -> None:
    """Law files carry only aggregate x00 VR codes (verified 2026-07-03)."""
    identifiers = sorted(
        row[0]
        for row in db_connection.execute("""
            SELECT DISTINCT d.original_identifier
            FROM expenses e JOIN budgets b ON b.id = e.budget_id
            JOIN association_table a ON a.expense_id = e.id
            JOIN dimensions d ON d.id = a.dimension_id
            WHERE b.type = 'LAW' AND d.type = 'EXPENSE_TYPE'
        """)
    )
    assert identifiers == ["100", "200", "300", "400", "500", "600", "700", "800"]


def test_report_expenses_use_no_aggregate_vr_codes(db_connection: sqlite3.Connection) -> None:
    """Reports must keep only detailed VR rows: x00 aggregates double-count
    spending in 22 of 33 files (learnings.md, VR-filter flip)."""
    aggregate_links = one_value(
        db_connection,
        """
        SELECT COUNT(*) FROM expenses e JOIN budgets b ON b.id = e.budget_id
        JOIN association_table a ON a.expense_id = e.id
        JOIN dimensions d ON d.id = a.dimension_id
        WHERE b.type = 'REPORT' AND d.type = 'EXPENSE_TYPE'
          AND d.original_identifier GLOB '[1-9]00'
        """,
    )
    assert aggregate_links == 0


# ---------------------------------------------------------------------------
# Referential integrity
# ---------------------------------------------------------------------------


def test_association_table_has_no_dangling_references(
    db_connection: sqlite3.Connection,
) -> None:
    dangling_expenses = one_value(
        db_connection,
        """
        SELECT COUNT(*) FROM association_table a
        LEFT JOIN expenses e ON e.id = a.expense_id WHERE e.id IS NULL
        """,
    )
    dangling_dimensions = one_value(
        db_connection,
        """
        SELECT COUNT(*) FROM association_table a
        LEFT JOIN dimensions d ON d.id = a.dimension_id WHERE d.id IS NULL
        """,
    )
    assert (dangling_expenses, dangling_dimensions) == (0, 0)


def test_no_dangling_dimension_parents(db_connection: sqlite3.Connection) -> None:
    dangling = one_value(
        db_connection,
        """
        SELECT COUNT(*) FROM dimensions c LEFT JOIN dimensions p ON p.id = c.parent_id
        WHERE c.parent_id IS NOT NULL AND p.id IS NULL
        """,
    )
    assert dangling == 0


def test_conversion_rates_frozen(db_connection: sqlite3.Connection) -> None:
    """GDP/PPP imports have no golden tier (network/API sources) — pin the
    resulting table wholesale instead. Baseline verified 2026-07-04."""
    rows = db_connection.execute(
        "SELECT name, value FROM conversion_rates ORDER BY name"
    ).fetchall()
    by_prefix = {"gdp": 0, "ppp": 0}
    for name, _ in rows:
        by_prefix[name.split("_")[0]] += 1
    assert by_prefix == {"gdp": 81, "ppp": 38}

    content = "\n".join(f"{name}|{value:.2f}" for name, value in rows)
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    assert digest == CONVERSION_RATES_SHA256, (
        "conversion_rates content changed — if a GDP/PPP re-import was intended, "
        "update CONVERSION_RATES_SHA256 and explain the change in the commit"
    )


def test_no_duplicate_dimensions_per_dedup_key(db_connection: sqlite3.Connection) -> None:
    """The parser dedup key is (type, original_identifier, parent, name) —
    same identifier with different names is legitimate (helpers.deduplicate_dimensions)."""
    duplicates = one_value(
        db_connection,
        """
        SELECT COUNT(*) FROM (
            SELECT 1 FROM dimensions
            GROUP BY type, original_identifier, parent_id, name HAVING COUNT(*) > 1
        )
        """,
    )
    assert duplicates == 0
