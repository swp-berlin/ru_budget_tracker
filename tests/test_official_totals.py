"""Validate every REPORT-* budget in budget.db against the official grand total
printed inside its own source Excel file ("Расходы федерального бюджета - всего"
row, executed column).

This is the strongest report-import source-of-truth check: if any spending were
lost (or double-counted) by the parser, the DB sum would deviate from the file's
printed total. As of 2026-07-03 (detailed-VR import) all 33 files match to the
cent; the previous aggregate-VR import overcounted in 22 of them.

Reports only: law files' printed "ВСЕГО" legitimately differs from the
ved-structure leaf sum (~445M ₽ in law_2025 — a property of the file, confirmed
by an independent parse), so there is no analogous law check.

Ported from .claude/validation/official_totals.py (untracked).
"""

import re
import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from tests.golden_utils import report_files

# Needs both the local DB and the real report Excel files.
pytestmark = [pytest.mark.db, pytest.mark.golden]

DB_SUM_QUERY = """
    SELECT SUM(e.value) FROM expenses e JOIN budgets b ON b.id = e.budget_id
    WHERE b.original_identifier = ?
"""


def parse_ru_number(value) -> float | None:
    """Parse numbers as printed in the files, e.g. '10 252 219 858 668,72'."""
    if pd.isna(value):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    normalized = str(value).replace("\xa0", " ").replace(" ", "").replace(",", ".")
    try:
        return float(normalized)
    except ValueError:
        return None


def printed_official_total(path: Path) -> float | None:
    """Grand total from the file's own 'Расходы ... - всего' row (executed column)."""
    engine = "xlrd" if path.suffix == ".xls" else "openpyxl"
    df = pd.read_excel(path, sheet_name="2.1", header=None, engine=engine)
    df = df.replace(r"^\s*$", pd.NA, regex=True).dropna(axis=1, how="all")
    for idx in range(min(30, len(df))):
        name = str(df.iloc[idx, 0]).lower()
        if "всего" in name and "расходы" in name:
            return parse_ru_number(df.iloc[idx, 8])
    return None


@pytest.mark.parametrize("source", report_files(), ids=lambda p: p.stem)
def test_db_sum_matches_printed_official_total(
    db_connection: sqlite3.Connection, source: Path
) -> None:
    match = re.match(r"report_(\d{4})_(\d{2})", source.name)
    assert match, f"unexpected report filename: {source.name}"
    budget_identifier = f"REPORT-{match.group(1)}-{match.group(2)}"

    official = printed_official_total(source)
    assert official is not None, f"could not find printed grand total in {source.name}"

    db_sum = db_connection.execute(DB_SUM_QUERY, (budget_identifier,)).fetchone()[0]
    assert db_sum is not None, f"no expenses in DB for {budget_identifier}"

    # Policy: deviations below 0.1% of the printed total are acceptable source
    # noise (they surface as WARNINGs in the quality report); >= 0.1% fails.
    # All 33 current files are exact to the cent.
    tolerance = max(1.0, 0.001 * abs(official))
    assert abs(db_sum - official) < tolerance, (
        f"{budget_identifier}: DB sum {db_sum:,.2f} deviates from the total printed in "
        f"{source.name} ({official:,.2f}) by {db_sum - official:+,.2f} ₽ (>= 0.1%)"
    )
