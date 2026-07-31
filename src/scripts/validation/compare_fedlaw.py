"""Cross-validate LAW-2025 in budget.db against Fedlaw.csv.

Fedlaw.csv was parsed from law_2025.xlsx by another person with an independent
parser. Source=1 is the ведомственная структура section. Law values are in
thousands ₽ (multiply by 1000); Budget/Budget2/Budget3 = planning years
2025/2026/2027 — our importer stores only the first year, so rows with an
empty Budget (funded only in 2026/2027) are expected to be absent on our side.

Diagnostic script: prints the top differing keys. The asserting version of this
check is tests/test_crossvalidation_external.py (`pytest -m external`).

Run from anywhere: uv run python src/scripts/validation/compare_fedlaw.py
Expected result (2026-07-03): all 3156 of our keys match, zero value
mismatches, identical total 29,348,621,151,400.00; 108 later-year-only keys
exist only on their side (reported as expected_absent, not a failure).
"""

import sqlite3
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from scripts.parsers.report_parser import parse_program_code  # noqa: E402

CSV = SRC / "data" / "validation" / "Fedlaw.csv"
DB = SRC / "data" / "budget.db"
BUDGET_ID = "LAW-2025"


def log(message: str) -> None:
    print(message)  # noqa: T201


def load_theirs() -> tuple[pd.Series, pd.DataFrame]:
    fl = pd.read_csv(CSV, dtype=str, na_values=["NULL"])
    fl = fl[fl["Source"] == "1"].copy()
    fl["vr_num"] = pd.to_numeric(fl["VR"], errors="coerce")
    leaf = fl[fl["vr_num"].notna() & (fl["vr_num"] > 0)].copy()
    leaf["val"] = pd.to_numeric(leaf["Budget"], errors="coerce") * 1000.0
    leaf["zsr_stripped"] = leaf["ZSR"].map(lambda z: parse_program_code(str(z).strip()))
    leaf["key"] = list(
        zip(
            leaf["Agency"].str.strip(),
            leaf["RZPR"].str.strip(),
            leaf["zsr_stripped"],
            leaf["VR"].str.strip(),
        )
    )
    funded = leaf[leaf["Budget"].notna()]
    later_only = leaf[leaf["Budget"].isna()]
    log(
        f"their leaf rows: {len(leaf)} "
        f"({len(funded)} funded in year 1, {len(later_only)} later-years-only), "
        f"year-1 sum: {funded['val'].sum():,.2f}"
    )
    return funded.groupby("key")["val"].sum(), later_only


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
    theirs, later_only = load_theirs()
    ours = load_ours()
    cmp = pd.concat([theirs.rename("theirs"), ours.rename("ours")], axis=1)
    both = cmp.dropna()
    only_theirs = cmp[cmp["ours"].isna()]
    only_ours = cmp[cmp["theirs"].isna()]
    both = both.assign(diff=(both["theirs"] - both["ours"]).abs())
    # tolerance 0.5 ₽: thousands are stored with one decimal, so ×1000 rounding
    mismatch = both[both["diff"] > 0.5]

    log(f"\nkeys matched: {len(both)}, value-mismatched: {len(mismatch)}")
    log(f"keys only in theirs: {len(only_theirs)} (value {only_theirs['theirs'].sum():,.2f})")
    log(f"keys only in ours:   {len(only_ours)} (value {only_ours['ours'].sum():,.2f})")
    log(f"later-years-only rows on their side (expected absent from DB): {len(later_only)}")
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
