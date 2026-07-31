"""Cross-validate imported budgets against an independent third-party parse.

Fedbud.csv (report_2026_03.xlsx) and Fedlaw.csv (law_2025.xlsx) were produced
by another person with a different parser. Comparison is per
(agency, рзпр, ЦСР-stripped, VR) key.

The CSVs live in src/data/validation/ (see the README there for their origin and
column semantics); src/scripts/validation/ holds diagnostic versions of these
comparisons that print the differing keys. Expected results as of 2026-07-03:
report — 4,979 keys, zero mismatches; law — all 3,156 DB keys match (108 keys
exist only in the CSV because they are funded only in planning years 2026/2027).
"""

import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from scripts.parsers.report_parser import parse_program_code

from tests.conftest import VALIDATION_DIR

pytestmark = pytest.mark.external

FEDBUD_CSV = VALIDATION_DIR / "Fedbud.csv"
FEDLAW_CSV = VALIDATION_DIR / "Fedlaw.csv"


def db_expense_keys(db_connection: sqlite3.Connection, budget_identifier: str) -> pd.Series:
    """Sum of DB expense values per (ministry, рзпр, ЦСР-stripped, VR) key.

    RZPR is the SUBCHAPTER identifier, or CHAPTER + "00" for expenses without a
    subchapter; the ЦСР is the PROGRAM identifier without its "-VR" suffix.
    """
    rows = pd.read_sql(
        """
        SELECT e.id, e.value, d.type, d.original_identifier
        FROM expenses e
        JOIN budgets b ON b.id = e.budget_id
        JOIN association_table a ON a.expense_id = e.id
        JOIN dimensions d ON d.id = a.dimension_id
        WHERE b.original_identifier = ?
        """,
        db_connection,
        params=(budget_identifier,),
    )
    pivoted = rows.pivot_table(
        index=["id", "value"], columns="type", values="original_identifier", aggfunc="first"
    ).reset_index()

    def rzpr(row) -> str:
        if isinstance(row.get("SUBCHAPTER"), str):
            return row["SUBCHAPTER"]
        return (row.get("CHAPTER") or "??") + "00"

    pivoted["rzpr"] = pivoted.apply(rzpr, axis=1)
    pivoted["zsr_stripped"] = pivoted["PROGRAM"].str.rsplit("-", n=1).str[0]
    pivoted["key"] = list(
        zip(pivoted["MINISTRY"], pivoted["rzpr"], pivoted["zsr_stripped"], pivoted["EXPENSE_TYPE"])
    )
    return pivoted.groupby("key")["value"].sum()


def csv_expense_keys(csv_path: Path, value_column: str, multiplier: float) -> pd.DataFrame:
    """Third-party rows (Source=1, ведомственная структура) with comparison keys."""
    df = pd.read_csv(csv_path, dtype=str, na_values=["NULL"])
    df = df[df["Source"] == "1"].copy()
    df["vr_num"] = pd.to_numeric(df["VR"], errors="coerce")
    df["val"] = pd.to_numeric(df[value_column], errors="coerce") * multiplier
    df["zsr_stripped"] = df["ZSR"].map(lambda z: parse_program_code(str(z).strip()))
    df["key"] = list(
        zip(
            df["Agency"].str.strip(),
            df["RZPR"].str.strip(),
            df["zsr_stripped"],
            df["VR"].str.strip(),
        )
    )
    return df


def compare(theirs: pd.Series, ours: pd.Series, tolerance: float) -> tuple[int, int, int]:
    """Return (value-mismatched, only-theirs, only-ours) key counts."""
    merged = pd.concat([theirs.rename("theirs"), ours.rename("ours")], axis=1)
    both = merged.dropna()
    mismatched = int(((both["theirs"] - both["ours"]).abs() > tolerance).sum())
    only_theirs = int(merged["ours"].isna().sum())
    only_ours = int(merged["theirs"].isna().sum())
    return mismatched, only_theirs, only_ours


@pytest.mark.skipif(not FEDBUD_CSV.exists(), reason=f"missing third-party CSV: {FEDBUD_CSV}")
def test_report_2026_03_matches_independent_parse(db_connection: sqlite3.Connection) -> None:
    theirs = csv_expense_keys(FEDBUD_CSV, value_column="Executed", multiplier=1.0)
    # Detail rows only (VR not divisible by 100) — matches what we import.
    detail = theirs[
        theirs["vr_num"].notna() & (theirs["vr_num"] % 100 != 0) & (theirs["vr_num"] > 0)
    ]
    ours = db_expense_keys(db_connection, "REPORT-2026-03")

    mismatched, only_theirs, only_ours = compare(detail.groupby("key")["val"].sum(), ours, 0.01)
    assert (mismatched, only_theirs, only_ours) == (0, 0, 0)


@pytest.mark.skipif(not FEDLAW_CSV.exists(), reason=f"missing third-party CSV: {FEDLAW_CSV}")
def test_law_2025_matches_independent_parse(db_connection: sqlite3.Connection) -> None:
    # Law CSV values are thousands ₽; Budget = first planning year (2025), the
    # only one we import. Rows with an empty Budget (funded only in 2026/2027)
    # are expected to be absent from the DB.
    theirs = csv_expense_keys(FEDLAW_CSV, value_column="Budget", multiplier=1000.0)
    leaf = theirs[theirs["vr_num"].notna() & (theirs["vr_num"] > 0)]
    funded = leaf[leaf["Budget"].notna()]
    ours = db_expense_keys(db_connection, "LAW-2025")

    # tolerance 0.5 ₽: thousands are stored with one decimal, so ×1000 rounding.
    mismatched, only_theirs, only_ours = compare(funded.groupby("key")["val"].sum(), ours, 0.5)
    assert (mismatched, only_theirs, only_ours) == (0, 0, 0)
