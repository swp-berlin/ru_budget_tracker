"""Cross-validate REPORT-2026-03 in budget.db against Fedbud.csv.

Fedbud.csv was parsed from report_2026_03.xlsx by another person with an
independent parser. Source=1 is the ведомственная структура section (what our
importer reads). Detail rows (VR not divisible by 100) are compared per
(agency, рзпр, ЦСР-stripped, VR) key against the DB.

Diagnostic script: prints the top differing keys. The asserting version of this
check is tests/test_crossvalidation_external.py (`pytest -m external`).

Run from anywhere: uv run python src/scripts/validation/compare_fedbud.py
Expected result (2026-07-03): 4979 rows both sides, all keys matched,
zero value mismatches, total 7,928,199,331,557.26.
"""

import sqlite3
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from scripts.parsers.report_parser import parse_program_code  # noqa: E402

CSV = SRC / "data" / "validation" / "Fedbud.csv"
DB = SRC / "data" / "budget.db"
BUDGET_ID = "REPORT-2026-03"


def log(message: str) -> None:
    print(message)  # noqa: T201


def load_theirs() -> pd.Series:
    fb = pd.read_csv(CSV, dtype=str, na_values=["NULL"])
    fb = fb[fb["Source"] == "1"].copy()
    fb["vr_num"] = pd.to_numeric(fb["VR"], errors="coerce")
    det = fb[fb["vr_num"].notna() & (fb["vr_num"] % 100 != 0) & (fb["vr_num"] > 0)].copy()
    det["val"] = pd.to_numeric(det["Executed"], errors="coerce")
    det["zsr_stripped"] = det["ZSR"].map(lambda z: parse_program_code(str(z).strip()))
    det["key"] = list(
        zip(
            det["Agency"].str.strip(),
            det["RZPR"].str.strip(),
            det["zsr_stripped"],
            det["VR"].str.strip(),
        )
    )
    log(f"their detail rows: {len(det)}, total: {det['val'].sum():,.2f}")
    return det.groupby("key")["val"].sum()


def load_ours() -> pd.Series:
    con = sqlite3.connect(DB)
    rows = pd.read_sql(
        """
        SELECT e.id, e.value, d.type, d.original_identifier
        FROM expenses e
        JOIN budgets b ON b.id = e.budget_id
        JOIN association_table a ON a.expense_id = e.id
        JOIN dimensions d ON d.id = a.dimension_id
        WHERE b.original_identifier = ?
        """,
        con,
        params=(BUDGET_ID,),
    )
    con.close()
    piv = rows.pivot_table(
        index=["id", "value"], columns="type", values="original_identifier", aggfunc="first"
    ).reset_index()
    log(f"our expenses: {len(piv)}, total: {piv['value'].sum():,.2f}")

    def rzpr(r):
        if isinstance(r.get("SUBCHAPTER"), str):
            return r["SUBCHAPTER"]
        return (r.get("CHAPTER") or "??") + "00"

    piv["rzpr"] = piv.apply(rzpr, axis=1)
    piv["zsr_stripped"] = piv["PROGRAM"].str.rsplit("-", n=1).str[0]
    piv["key"] = list(zip(piv["MINISTRY"], piv["rzpr"], piv["zsr_stripped"], piv["EXPENSE_TYPE"]))
    return piv.groupby("key")["value"].sum()


def main() -> int:
    cmp = pd.concat([load_theirs().rename("theirs"), load_ours().rename("ours")], axis=1)
    both = cmp.dropna()
    only_theirs = cmp[cmp["ours"].isna()]
    only_ours = cmp[cmp["theirs"].isna()]
    both = both.assign(diff=(both["theirs"] - both["ours"]).abs())
    mismatch = both[both["diff"] > 0.01]

    log(f"\nkeys matched: {len(both)}, value-mismatched: {len(mismatch)}")
    log(f"keys only in theirs: {len(only_theirs)} (value {only_theirs['theirs'].sum():,.2f})")
    log(f"keys only in ours:   {len(only_ours)} (value {only_ours['ours'].sum():,.2f})")
    for label, d in [
        ("mismatches", mismatch.sort_values("diff", ascending=False)),
        ("only-theirs", only_theirs),
        ("only-ours", only_ours),
    ]:
        if len(d):
            log(f"\ntop {label}:")
            log(d.head(10).to_string())
    ok = not len(mismatch) and not len(only_theirs) and not len(only_ours)
    log("\nRESULT: " + ("OK — parsers agree" if ok else "DISCREPANCIES FOUND"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
