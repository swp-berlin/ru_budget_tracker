"""
Data-quality report for the imported budget database.

Combines two inputs:
1. Per-file parse-issue JSONs written by `scripts.import` to
   <db-dir>/quality/issues/ (row-level findings recorded during parsing).
2. SQL checks against budget.db (cross-source consistency, dimension
   integrity, census).

Writes <db-dir>/quality/report.md (human-readable) and report.json (machine-
readable). Both are deterministic — no timestamps — so re-import diffs are
reviewable in git. Exit code 1 iff any ERROR-severity finding exists;
WARNINGs (e.g. known source inconsistencies) are displayed but do not fail.

Usage (from src/):
    uv run python -m scripts.quality_report

Unit conventions checked/documented here (see also parser docstrings):
    LAW files          thousands of ₽ → converted to ₽ at parse (×1000)
    REPORT files       ₽ (with kopecks) → stored as-is
    TOTAL-REPORT xlsx  billions of ₽ → converted to ₽ at parse (×1e9)
    TOTAL-LAW csv      thousands of ₽ → stored RAW; the app compensates with
                       budget_config.law_total_value_multiplier (×1000)
"""

import argparse
import json
import logging
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from settings import settings  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# TOTAL-LAW values are stored in thousands of ₽ (raw CSV values); detail
# expenses are ₽. Mirrors budget_config.law_total_value_multiplier
# (src/utils/definitions.py) used by the LawClassifiedSpendingPerChapter view.
LAW_TOTAL_MULTIPLIER = 1000.0

# Excess tolerances for "detail exceeds official total" checks: half a unit of
# the coarser source's precision, so pure rounding differences are not flagged
# (law totals are published to 0.1 bn ₽; report totals to 0.1 bn ₽ as well).
LAW_EXCESS_TOLERANCE = 50_000_000.0
REPORT_EXCESS_TOLERANCE = 50_000_000.0

# By-design baseline for TOTAL-* budgets: each of the 209 totals budgets has
# one undimensioned grand-total expense; chapter expenses carry exactly one
# CHAPTER dimension (798 as of 2026-07). Anything beyond that is a finding.
EXPECTED_ZERO_DIM_BUDGET_TYPES = {"TOTAL"}
EXPECTED_ONE_DIM_BUDGET_TYPES = {"TOTAL"}

UNIT_TABLE = [
    ("LAW files (law_YYYY.xlsx)", "thousands of ₽", "×1000 at parse → DB stores ₽"),
    ("REPORT files (report_YYYY_MM.xlsx)", "₽ with kopecks", "stored as-is"),
    ("TOTAL-REPORT (total_report_YYYY.xlsx)", "billions of ₽", "×1e9 at parse → DB stores ₽"),
    (
        "TOTAL-LAW (total_law_YYYY.csv)",
        "thousands of ₽",
        "stored RAW — app view multiplies ×1000 (budget_config.law_total_value_multiplier)",
    ),
]


@dataclass
class Check:
    name: str
    severity: str  # severity applied to findings: "ERROR" | "WARNING" | "INFO"
    description: str
    findings: list[dict] = field(default_factory=list)

    @property
    def status(self) -> str:
        if not self.findings:
            return "ok"
        return {"ERROR": "error", "WARNING": "warning"}.get(self.severity, "info")


# =============================================================================
# DB CHECKS
# =============================================================================


def check_census(con: sqlite3.Connection) -> Check:
    check = Check(
        "census",
        "INFO",
        "Row counts by table and budget type (documentation; tests/test_db_invariants.py enforces)",
    )
    budgets = dict(con.execute("SELECT type, COUNT(*) FROM budgets GROUP BY type"))
    expenses = con.execute("SELECT COUNT(*) FROM expenses").fetchone()[0]
    dimensions = con.execute("SELECT COUNT(*) FROM dimensions").fetchone()[0]
    rates = con.execute("SELECT COUNT(*) FROM conversion_rates").fetchone()[0]
    check.findings.append(
        {
            "budgets_by_type": dict(sorted(budgets.items())),
            "expenses": expenses,
            "dimensions": dimensions,
            "conversion_rates": rates,
        }
    )
    return check


def check_undimensioned_expenses(con: sqlite3.Connection) -> Check:
    check = Check(
        "undimensioned_expenses",
        "ERROR",
        "LAW/REPORT expenses must carry dimensions; only TOTAL-* budgets have "
        "undimensioned (grand total) and single-dimension (chapter) expenses by design",
    )
    rows = con.execute("""
        SELECT b.type, b.original_identifier,
               (SELECT COUNT(*) FROM association_table a WHERE a.expense_id = e.id) AS dims,
               COUNT(*) AS n
        FROM expenses e JOIN budgets b ON b.id = e.budget_id
        GROUP BY b.type, b.original_identifier, dims
        HAVING dims <= 1
    """).fetchall()
    for budget_type, identifier, dims, n in rows:
        expected = (dims == 0 and budget_type in EXPECTED_ZERO_DIM_BUDGET_TYPES) or (
            dims == 1 and budget_type in EXPECTED_ONE_DIM_BUDGET_TYPES
        )
        if not expected:
            check.findings.append({"budget": identifier, "dimension_count": dims, "expenses": n})
    check.findings.sort(key=lambda f: f["budget"])
    return check


def check_dimension_integrity(con: sqlite3.Connection) -> Check:
    check = Check(
        "dimension_integrity",
        "ERROR",
        "No dangling parent links, no duplicate dimensions per dedup key "
        "(type, identifier, parent, name), no dangling association rows",
    )
    dangling_parents = con.execute("""
        SELECT c.id, c.type, c.original_identifier FROM dimensions c
        LEFT JOIN dimensions p ON p.id = c.parent_id
        WHERE c.parent_id IS NOT NULL AND p.id IS NULL ORDER BY c.id
    """).fetchall()
    for dim_id, dim_type, identifier in dangling_parents:
        check.findings.append(
            {
                "kind": "dangling_parent",
                "dimension_id": dim_id,
                "type": dim_type,
                "identifier": identifier,
            }
        )

    duplicates = con.execute("""
        SELECT type, original_identifier, parent_id, name, COUNT(*) FROM dimensions
        GROUP BY type, original_identifier, parent_id, name HAVING COUNT(*) > 1
        ORDER BY type, original_identifier
    """).fetchall()
    for dim_type, identifier, parent_id, name, n in duplicates:
        check.findings.append(
            {
                "kind": "duplicate_dimension",
                "type": dim_type,
                "identifier": identifier,
                "parent_id": parent_id,
                "name": name[:80],
                "count": n,
            }
        )

    for label, query in [
        (
            "dangling_assoc_expense",
            "SELECT COUNT(*) FROM association_table a LEFT JOIN expenses e ON e.id = a.expense_id "
            "WHERE e.id IS NULL",
        ),
        (
            "dangling_assoc_dimension",
            "SELECT COUNT(*) FROM association_table a LEFT JOIN dimensions d ON d.id = a.dimension_id "
            "WHERE d.id IS NULL",
        ),
    ]:
        count = con.execute(query).fetchone()[0]
        if count:
            check.findings.append({"kind": label, "count": count})
    return check


def check_law_detail_exceeds_total(con: sqlite3.Connection) -> Check:
    check = Check(
        "law_detail_exceeds_total",
        "WARNING",
        "LAW ved-structure chapter sums must not exceed the official chapter totals "
        "from the PDF appendix (TOTAL-LAW-EXPENSE, thousands ×1000). Positive gaps are "
        "classified spending; an EXCESS means the two official sources disagree "
        "(or a totals-CSV transcription slip) and shows as negative classified "
        "spending in the app",
    )
    rows = con.execute(f"""
        WITH law AS (
          SELECT substr(b.original_identifier, 5, 4) AS year, d.original_identifier AS ch,
                 SUM(e.value) AS detail
          FROM expenses e JOIN budgets b ON b.id = e.budget_id
          JOIN association_table a ON a.expense_id = e.id
          JOIN dimensions d ON d.id = a.dimension_id
          WHERE b.type = 'LAW' AND d.type = 'CHAPTER' GROUP BY 1, 2),
        tot AS (
          SELECT substr(b.original_identifier, -4) AS year, d.original_identifier AS ch,
                 SUM(e.value) * {LAW_TOTAL_MULTIPLIER} AS total
          FROM expenses e JOIN budgets b ON b.id = e.budget_id
          JOIN association_table a ON a.expense_id = e.id
          JOIN dimensions d ON d.id = a.dimension_id
          WHERE b.original_identifier LIKE 'TOTAL-LAW-EXPENSE-%' AND d.type = 'CHAPTER'
          GROUP BY 1, 2)
        SELECT law.year, law.ch, law.detail, tot.total
        FROM law JOIN tot ON tot.year = law.year AND tot.ch = law.ch
        ORDER BY law.year, law.ch
    """).fetchall()
    for year, chapter, detail, total in rows:
        excess = detail - total
        if excess > LAW_EXCESS_TOLERANCE:
            check.findings.append(
                {
                    "year": year,
                    "chapter": chapter,
                    "law_detail_rub": round(detail, 2),
                    "official_total_rub": round(total, 2),
                    "excess_rub": round(excess, 2),
                }
            )
    return check


def check_law_year_detail_exceeds_total(con: sqlite3.Connection) -> Check:
    check = Check(
        "law_year_detail_exceeds_total",
        "WARNING",
        "LAW ved-structure year totals must not exceed the official grand total "
        "(TOTAL-LAW-EXPENSE undimensioned expense, thousands ×1000)",
    )
    rows = con.execute(f"""
        WITH law AS (
          SELECT substr(b.original_identifier, 5, 4) AS year, SUM(e.value) AS detail
          FROM expenses e JOIN budgets b ON b.id = e.budget_id
          WHERE b.type = 'LAW' GROUP BY 1),
        tot AS (
          SELECT substr(b.original_identifier, -4) AS year,
                 SUM(e.value) * {LAW_TOTAL_MULTIPLIER} AS total
          FROM expenses e JOIN budgets b ON b.id = e.budget_id
          WHERE b.original_identifier LIKE 'TOTAL-LAW-EXPENSE-%'
            AND NOT EXISTS (SELECT 1 FROM association_table a WHERE a.expense_id = e.id)
          GROUP BY 1)
        SELECT law.year, law.detail, tot.total
        FROM law JOIN tot ON tot.year = law.year ORDER BY law.year
    """).fetchall()
    for year, detail, total in rows:
        excess = detail - total
        if excess > LAW_EXCESS_TOLERANCE:
            check.findings.append(
                {
                    "year": year,
                    "law_detail_rub": round(detail, 2),
                    "official_total_rub": round(total, 2),
                    "excess_rub": round(excess, 2),
                }
            )
    return check


def check_report_detail_exceeds_total(con: sqlite3.Connection) -> Check:
    check = Check(
        "report_detail_exceeds_total",
        "WARNING",
        "REPORT chapter sums must not exceed the official monthly chapter totals "
        "(TOTAL-REPORT-EXPENSE; chapter breakdown exists until 2021). "
        "Tolerance: one unit of source precision (1 bn ₽)",
    )
    rows = con.execute("""
        WITH rep AS (
          SELECT substr(b.original_identifier, 8) AS ym, d.original_identifier AS ch,
                 SUM(e.value) AS detail
          FROM expenses e JOIN budgets b ON b.id = e.budget_id
          JOIN association_table a ON a.expense_id = e.id
          JOIN dimensions d ON d.id = a.dimension_id
          WHERE b.type = 'REPORT' AND d.type = 'CHAPTER' GROUP BY 1, 2),
        tot AS (
          SELECT substr(b.original_identifier, -7) AS ym, d.original_identifier AS ch,
                 SUM(e.value) AS total
          FROM expenses e JOIN budgets b ON b.id = e.budget_id
          JOIN association_table a ON a.expense_id = e.id
          JOIN dimensions d ON d.id = a.dimension_id
          WHERE b.original_identifier LIKE 'TOTAL-REPORT-EXPENSE-%' AND d.type = 'CHAPTER'
          GROUP BY 1, 2)
        SELECT rep.ym, rep.ch, rep.detail, tot.total
        FROM rep JOIN tot ON tot.ym = rep.ym AND tot.ch = rep.ch
        ORDER BY rep.ym, rep.ch
    """).fetchall()
    for ym, chapter, detail, total in rows:
        excess = detail - total
        if excess > REPORT_EXCESS_TOLERANCE:
            check.findings.append(
                {
                    "period": ym,
                    "chapter": chapter,
                    "report_detail_rub": round(detail, 2),
                    "official_total_rub": round(total, 2),
                    "excess_rub": round(excess, 2),
                }
            )
    return check


# =============================================================================
# PARSE-ISSUE FILES
# =============================================================================


def load_parse_issues(issues_dir: Path) -> tuple[dict[str, dict[str, int]], int]:
    """Read per-file issue JSONs; returns ({file: counts_by_code}, error_count)."""
    per_file: dict[str, dict[str, int]] = {}
    error_count = 0
    for path in sorted(issues_dir.glob("*.json")):
        with path.open(encoding="utf-8") as f:
            payload = json.load(f)
        counts = payload.get("counts_by_code", {})
        if counts:
            per_file[payload.get("source_file", path.stem)] = counts
        error_count += sum(
            1 for issue in payload.get("issues", []) if issue.get("severity") == "ERROR"
        )
    return per_file, error_count


# =============================================================================
# OUTPUT
# =============================================================================


def build_report(checks: list[Check], parse_issues: dict[str, dict[str, int]]) -> dict:
    return {
        "checks": [
            {
                "name": c.name,
                "status": c.status,
                "severity": c.severity,
                "description": c.description,
                "finding_count": len(c.findings),
                "findings": c.findings,
            }
            for c in checks
        ],
        "parse_issues_by_file": dict(sorted(parse_issues.items())),
        "unit_conventions": [
            {"source": s, "source_unit": u, "handling": h} for s, u, h in UNIT_TABLE
        ],
    }


STATUS_MARK = {"ok": "OK", "warning": "WARN", "error": "FAIL", "info": "info"}


def render_markdown(report: dict) -> str:
    lines = [
        "# Data-quality report",
        "",
        "Generated by `make quality-report` (`scripts/quality_report.py`). "
        "Deterministic output — diffs of this file show how data quality changed "
        "between imports.",
        "",
        "## Summary",
        "",
        "| Check | Status | Findings |",
        "|---|---|---|",
    ]
    for check in report["checks"]:
        lines.append(
            f"| {check['name']} | {STATUS_MARK[check['status']]} | {check['finding_count']} |"
        )
    parse_issue_total = sum(sum(v.values()) for v in report["parse_issues_by_file"].values())
    lines.append(
        f"| parse_issues | {'info' if parse_issue_total else 'OK'} | {parse_issue_total} |"
    )

    lines += [
        "",
        "## Unit conventions",
        "",
        "| Source | Unit in file | Handling |",
        "|---|---|---|",
    ]
    for unit in report["unit_conventions"]:
        lines.append(f"| {unit['source']} | {unit['source_unit']} | {unit['handling']} |")

    for check in report["checks"]:
        if not check["findings"] or check["name"] == "census":
            continue
        lines += [
            "",
            f"## {check['name']} ({STATUS_MARK[check['status']]})",
            "",
            check["description"],
            "",
        ]
        keys = list(check["findings"][0].keys())
        lines.append("| " + " | ".join(keys) + " |")
        lines.append("|" + "---|" * len(keys))
        for finding in check["findings"]:
            lines.append("| " + " | ".join(_fmt(finding.get(k)) for k in keys) + " |")

    census = next(c for c in report["checks"] if c["name"] == "census")
    if census["findings"]:
        lines += ["", "## census", ""]
        for key, value in census["findings"][0].items():
            lines.append(f"- {key}: {value}")

    if report["parse_issues_by_file"]:
        lines += [
            "",
            "## Parse issues by file",
            "",
            "Row-level detail in `quality/issues/<file>.json` (gitignored; regenerated on import).",
            "",
        ]
        for source_file, counts in report["parse_issues_by_file"].items():
            rendered = ", ".join(f"{code}: {n}" for code, n in sorted(counts.items()))
            lines.append(f"- `{source_file}` — {rendered}")

    lines.append("")
    return "\n".join(lines)


def _fmt(value: object) -> str:
    if isinstance(value, float):
        return f"{value:,.2f}"
    return str(value)


# =============================================================================
# MAIN
# =============================================================================


def run_quality_report(db_path: Path, issues_dir: Path, output_dir: Path) -> int:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        checks = [
            check_census(con),
            check_undimensioned_expenses(con),
            check_dimension_integrity(con),
            check_law_detail_exceeds_total(con),
            check_law_year_detail_exceeds_total(con),
            check_report_detail_exceeds_total(con),
        ]
    finally:
        con.close()

    parse_issues, parse_error_count = load_parse_issues(issues_dir)
    report = build_report(checks, parse_issues)

    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "report.json"
    with json_path.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
        f.write("\n")
    md_path = output_dir / "report.md"
    md_path.write_text(render_markdown(report), encoding="utf-8")

    for check in checks:
        logger.info(f"{check.name}: {check.status} ({len(check.findings)} findings)")
    logger.info(f"Parse-issue ERRORs recorded during import: {parse_error_count}")
    logger.info(f"Wrote {md_path} and {json_path}")

    has_errors = parse_error_count > 0 or any(c.status == "error" for c in checks)
    return 1 if has_errors else 0


def main() -> None:
    default_quality_dir = settings.database.directory / "quality"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=settings.database.directory / "budget.db")
    parser.add_argument("--issues-dir", type=Path, default=default_quality_dir / "issues")
    parser.add_argument("--output-dir", type=Path, default=default_quality_dir)
    args = parser.parse_args()
    sys.exit(run_quality_report(args.db, args.issues_dir, args.output_dir))


if __name__ == "__main__":
    main()
