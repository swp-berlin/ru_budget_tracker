"""Shared helpers for the golden characterization tests and their generator.

A "golden" is a JSON summary of what a parser produces for one real data file:
counts, totals, per-dimension sums (to localize a diff) and a hash over the full
canonical row set (to catch changes the sums cancel out). All money is formatted
as `f"{value:.2f}"` strings so goldens diff byte-exactly with zero tolerance.
"""

import hashlib
from collections import defaultdict
from pathlib import Path

from models import Budget, Dimension, Expense

from tests.conftest import LAWS_DIR, REPORTS_DIR, TOTALS_DIR

DIMENSION_TYPES = ["MINISTRY", "CHAPTER", "SUBCHAPTER", "PROGRAM", "EXPENSE_TYPE"]

TOTALS_FILES = [TOTALS_DIR / "total_report_2026.xlsx", TOTALS_DIR / "total_law_2026.csv"]


def law_files() -> list[Path]:
    return sorted(LAWS_DIR.glob("law_*.xlsx"))


def report_files() -> list[Path]:
    # Two files are legacy .xls (report_2018_03, report_2023_03), the rest .xlsx.
    return sorted(list(REPORTS_DIR.glob("report_*.xlsx")) + list(REPORTS_DIR.glob("report_*.xls")))


def golden_name(source_file: Path) -> str:
    """Golden JSON filename for a data file, e.g. report_2024_03.xlsx -> report_2024_03.json."""
    return f"{source_file.stem}.json"


def _money(value: float) -> str:
    return f"{value:.2f}"


def _dims_by_type(expense: Expense) -> dict[str, str]:
    """Map dimension type -> original_identifier for one expense.

    Parsers link at most one dimension per type; if that ever changes, joining
    with "+" keeps the canonical row deterministic instead of dropping data.
    """
    by_type: dict[str, list[str]] = defaultdict(list)
    for dim in expense.dimensions:
        by_type[dim.type].append(dim.original_identifier)
    return {t: "+".join(sorted(ids)) for t, ids in by_type.items()}


def canonical_rows(expenses: list[Expense]) -> list[str]:
    """One sorted line per expense: ministry|chapter|subchapter|program|expense_type|value."""
    rows = []
    for expense in expenses:
        dims = _dims_by_type(expense)
        fields = [dims.get(t, "") for t in DIMENSION_TYPES] + [_money(expense.value)]
        rows.append("|".join(fields))
    return sorted(rows)


def rows_sha256(expenses: list[Expense]) -> str:
    return hashlib.sha256("\n".join(canonical_rows(expenses)).encode("utf-8")).hexdigest()


def canonical_dimensions(dimensions: list[Dimension]) -> list[str]:
    """One sorted line per dimension: type|identifier|parent|name.

    Covers what canonical_rows cannot see: the parent hierarchy (at parse time
    parent_id holds the parent's original_identifier string) and dimension names
    (which feed translations and display). Verified 2026-07-04: without this,
    breaking _find_parent_program entirely passes every golden test.
    """
    return sorted(
        f"{d.type}|{d.original_identifier}|{d.parent_id or ''}|{d.name or ''}" for d in dimensions
    )


def dimensions_sha256(dimensions: list[Dimension]) -> str:
    return hashlib.sha256("\n".join(canonical_dimensions(dimensions)).encode("utf-8")).hexdigest()


def summarize_parse(
    budget: Budget, dimensions: list[Dimension], expenses: list[Expense], source_file: Path
) -> dict:
    """Summarize a law/report parse result (parse_law_file / parse_report_file output)."""
    sums: dict[str, dict[str, float]] = {t: defaultdict(float) for t in DIMENSION_TYPES}
    coverage: dict[str, int] = dict.fromkeys(DIMENSION_TYPES, 0)
    for expense in expenses:
        dims = _dims_by_type(expense)
        for dim_type, identifier in dims.items():
            coverage[dim_type] += 1
            sums[dim_type][identifier] += expense.value

    dimension_counts: dict[str, int] = dict.fromkeys(DIMENSION_TYPES, 0)
    for dim in dimensions:
        dimension_counts[dim.type] += 1

    return {
        "source_file": f"{source_file.parent.name}/{source_file.name}",
        "budget": {
            "original_identifier": budget.original_identifier,
            "type": budget.type,
            "scope": budget.scope,
            "published_at": budget.published_at.isoformat(),
            "name": budget.name,
        },
        "expense_count": len(expenses),
        "expense_total": _money(sum(e.value for e in expenses)),
        "dimension_counts": dimension_counts,
        "expense_dim_type_coverage": coverage,
        "sum_by_ministry": {k: _money(v) for k, v in sorted(sums["MINISTRY"].items())},
        "sum_by_chapter": {k: _money(v) for k, v in sorted(sums["CHAPTER"].items())},
        "sum_by_expense_type": {k: _money(v) for k, v in sorted(sums["EXPENSE_TYPE"].items())},
        "rows_sha256": rows_sha256(expenses),
        "dimensions_sha256": dimensions_sha256(dimensions),
    }


def summarize_totals_parse(
    budgets: list[Budget],
    chapter_codes: list[str],
    expenses: list[tuple[str, Expense, str | None]],
    source_file: Path,
) -> dict:
    """Summarize a totals parse result (totals_parser.parse_totals_file output).

    Totals expenses are (budget_identifier, Expense, chapter_code-or-None) tuples;
    None marks the undimensioned grand-total expense. Per-budget per-chapter values
    are small (<=15 rows per budget), so they are stored in full instead of hashed.
    """
    per_budget: dict[str, dict[str, str]] = defaultdict(dict)
    for budget_identifier, expense, chapter_code in expenses:
        key = chapter_code if chapter_code is not None else "TOTAL"
        per_budget[budget_identifier][key] = _money(expense.value)

    return {
        "source_file": f"{source_file.parent.name}/{source_file.name}",
        "budget_identifiers": sorted(b.original_identifier for b in budgets),
        "chapter_codes": chapter_codes,
        "expense_count": len(expenses),
        "values_by_budget": {k: dict(sorted(v.items())) for k, v in sorted(per_budget.items())},
    }
