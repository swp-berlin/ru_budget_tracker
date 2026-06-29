#!/usr/bin/env python3
"""
Sanity check for budget data integrity.

Checks:
1. Each expense has multiple dimensions associated (flags those with 0 or 1)
2. Dimension coverage per budget (MINISTRY, CHAPTER, SUBCHAPTER, PROGRAM, EXPENSE_TYPE)
3. Generates reproducible summary statistics for data verification

Output:
- data/import_files/sanity_check_YYYYMMDD_HHMMSS.log  (detailed issues)
- data/import_files/sanity_check_YYYYMMDD_HHMMSS.json (summary statistics)

Usage:
    cd src && uv run python sanity_check_dimensions.py

    # Or with custom output directory:
    cd src && uv run python sanity_check_dimensions.py --output-dir /path/to/dir
"""

import sys
import json
import hashlib
import logging
import argparse
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Tuple
from collections import defaultdict

import pandas as pd
from sqlalchemy import select, func, text

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from database.sessions import get_sync_session
from models import Budget, Expense, Dimension, assoc_table

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


# =============================================================================
# DATABASE QUERIES
# =============================================================================


def get_all_budgets(session) -> pd.DataFrame:
    """Get all budgets from the database."""
    stmt = select(
        Budget.id,
        Budget.original_identifier,
        Budget.name,
        Budget.type,
        Budget.scope,
        Budget.published_at,
    ).order_by(Budget.published_at, Budget.original_identifier)

    result = session.execute(stmt)
    rows = result.fetchall()

    return pd.DataFrame(
        rows, columns=["id", "original_identifier", "name", "type", "scope", "published_at"]
    )


def get_expense_dimension_counts(session) -> pd.DataFrame:
    """
    Get dimension count for each expense.

    Returns DataFrame with: expense_id, budget_id, budget_identifier, value, dimension_count
    """
    stmt = text("""
        SELECT
            e.id as expense_id,
            e.budget_id,
            b.original_identifier as budget_identifier,
            b.type as budget_type,
            e.value,
            COUNT(a.dimension_id) as dimension_count
        FROM expenses e
        JOIN budgets b ON e.budget_id = b.id
        LEFT JOIN association_table a ON e.id = a.expense_id
        GROUP BY e.id, e.budget_id, b.original_identifier, b.type, e.value
        ORDER BY b.original_identifier, e.id
    """)

    result = session.execute(stmt)
    rows = result.fetchall()

    return pd.DataFrame(
        rows,
        columns=[
            "expense_id",
            "budget_id",
            "budget_identifier",
            "budget_type",
            "value",
            "dimension_count",
        ],
    )


def get_expense_dimension_types(session) -> pd.DataFrame:
    """
    Get dimension types for each expense.

    Returns DataFrame with: expense_id, budget_identifier, dimension_types (comma-separated)
    """
    stmt = text("""
        SELECT
            e.id as expense_id,
            b.original_identifier as budget_identifier,
            e.value,
            GROUP_CONCAT(DISTINCT d.type) as dimension_types
        FROM expenses e
        JOIN budgets b ON e.budget_id = b.id
        LEFT JOIN association_table a ON e.id = a.expense_id
        LEFT JOIN dimensions d ON a.dimension_id = d.id
        GROUP BY e.id, b.original_identifier, e.value
        ORDER BY b.original_identifier, e.id
    """)

    result = session.execute(stmt)
    rows = result.fetchall()

    return pd.DataFrame(
        rows, columns=["expense_id", "budget_identifier", "value", "dimension_types"]
    )


def get_dimension_coverage_by_budget(session) -> pd.DataFrame:
    """
    Get dimension type coverage statistics per budget.

    Returns: budget_identifier, dimension_type, expense_count, total_value
    """
    stmt = text("""
        SELECT
            b.original_identifier as budget_identifier,
            b.type as budget_type,
            d.type as dimension_type,
            COUNT(DISTINCT e.id) as expense_count,
            SUM(e.value) as total_value
        FROM expenses e
        JOIN budgets b ON e.budget_id = b.id
        JOIN association_table a ON e.id = a.expense_id
        JOIN dimensions d ON a.dimension_id = d.id
        GROUP BY b.original_identifier, b.type, d.type
        ORDER BY b.original_identifier, d.type
    """)

    result = session.execute(stmt)
    rows = result.fetchall()

    return pd.DataFrame(
        rows,
        columns=[
            "budget_identifier",
            "budget_type",
            "dimension_type",
            "expense_count",
            "total_value",
        ],
    )


def get_expense_sums_by_dimension(session, dimension_type: str) -> pd.DataFrame:
    """
    Get expense sums grouped by budget and dimension.

    Returns: budget_identifier, dimension_identifier, dimension_name, total_value
    """
    stmt = (
        select(
            Budget.original_identifier.label("budget_identifier"),
            Dimension.original_identifier.label("dimension_identifier"),
            Dimension.name.label("dimension_name"),
            func.sum(Expense.value).label("total_value"),
        )
        .select_from(Expense)
        .join(Budget, Expense.budget_id == Budget.id)
        .join(
            assoc_table,
            Expense.id == assoc_table.c.expense_id,
        )
        .join(
            Dimension,
            assoc_table.c.dimension_id == Dimension.id,
        )
        .where(Dimension.type == dimension_type)
        .group_by(
            Budget.original_identifier,
            Dimension.original_identifier,
            Dimension.name,
        )
        .order_by(Budget.original_identifier, Dimension.original_identifier)
    )

    result = session.execute(stmt)
    rows = result.fetchall()

    return pd.DataFrame(
        rows, columns=["budget_identifier", "dimension_identifier", "dimension_name", "total_value"]
    )


def get_total_counts(session) -> dict[str, int | dict[str, int]]:
    """Get total counts of budgets, expenses, dimensions."""
    budget_count = session.execute(select(func.count(Budget.id))).scalar()
    expense_count = session.execute(select(func.count(Expense.id))).scalar()
    dimension_count = session.execute(select(func.count(Dimension.id))).scalar()

    # Count dimensions by type
    dim_type_stmt = select(Dimension.type, func.count(Dimension.id)).group_by(Dimension.type)
    dim_type_counts = dict(session.execute(dim_type_stmt).fetchall())

    return {
        "budgets": budget_count,
        "expenses": expense_count,
        "dimensions": dimension_count,
        "dimensions_by_type": dim_type_counts,
    }


# =============================================================================
# ANALYSIS FUNCTIONS
# =============================================================================


def find_problematic_expenses(expense_dims_df: pd.DataFrame) -> Dict[str, List[Dict]]:
    """
    Find expenses with insufficient dimensions.

    Returns dict with:
    - zero_dimensions: expenses with no dimensions
    - one_dimension: expenses with only one dimension
    - missing_types: expenses missing expected dimension types
    """
    problems: Dict[str, List[Dict]] = {
        "zero_dimensions": [],
        "one_dimension": [],
        "missing_types": [],
    }

    # Expected dimension types for a complete expense
    expected_types = {"MINISTRY", "CHAPTER", "EXPENSE_TYPE"}

    for _, row in expense_dims_df.iterrows():
        dim_count = row["dimension_count"]
        expense_id = row["expense_id"]
        budget_id = row["budget_identifier"]
        value = row["value"]

        if dim_count == 0:
            problems["zero_dimensions"].append(
                {
                    "expense_id": int(expense_id),
                    "budget_identifier": budget_id,
                    "value": float(value),
                    "dimension_count": int(dim_count),
                }
            )
        elif dim_count == 1:
            problems["one_dimension"].append(
                {
                    "expense_id": int(expense_id),
                    "budget_identifier": budget_id,
                    "value": float(value),
                    "dimension_count": int(dim_count),
                }
            )

    return problems


def find_missing_dimension_types(expense_types_df: pd.DataFrame) -> List[Dict]:
    """
    Find expenses missing expected dimension types.

    Expected: MINISTRY, CHAPTER, EXPENSE_TYPE (at minimum)
    """
    expected_types = {"MINISTRY", "CHAPTER", "EXPENSE_TYPE"}
    missing = []

    for _, row in expense_types_df.iterrows():
        dim_types_str = row["dimension_types"]
        if pd.isna(dim_types_str) or not dim_types_str:
            actual_types = set()
        else:
            actual_types = set(dim_types_str.split(","))

        missing_types = expected_types - actual_types

        if missing_types:
            missing.append(
                {
                    "expense_id": int(row["expense_id"]),
                    "budget_identifier": row["budget_identifier"],
                    "value": float(row["value"]),
                    "has_types": sorted(actual_types),
                    "missing_types": sorted(missing_types),
                }
            )

    return missing


def calculate_summary_statistics(
    session,
    budgets_df: pd.DataFrame,
    expense_dims_df: pd.DataFrame,
    coverage_df: pd.DataFrame,
) -> Dict[str, Any]:
    """
    Calculate summary statistics for JSON output.

    These statistics can be used to verify data consistency across imports.
    """
    totals = get_total_counts(session)

    # Per-budget statistics
    budget_stats = {}
    for _, budget in budgets_df.iterrows():
        budget_id = budget["original_identifier"]
        budget_expenses = expense_dims_df[expense_dims_df["budget_identifier"] == budget_id]

        budget_stats[budget_id] = {
            "type": budget["type"],
            "expense_count": len(budget_expenses),
            "total_value": float(budget_expenses["value"].sum()),
            "avg_dimensions_per_expense": float(budget_expenses["dimension_count"].mean())
            if len(budget_expenses) > 0
            else 0,
        }

    # Dimension coverage per budget
    coverage_stats = {}
    for budget_id in budgets_df["original_identifier"].unique():
        budget_coverage = coverage_df[coverage_df["budget_identifier"] == budget_id]
        coverage_stats[budget_id] = {
            row["dimension_type"]: {
                "expense_count": int(row["expense_count"]),
                "total_value": float(row["total_value"]),
            }
            for _, row in budget_coverage.iterrows()
        }

    # Ministry sums per budget
    ministry_sums_df = get_expense_sums_by_dimension(session, "MINISTRY")
    ministry_sums: Dict[str, Dict] = defaultdict(dict)
    for _, row in ministry_sums_df.iterrows():
        ministry_sums[row["budget_identifier"]][row["dimension_identifier"]] = {
            "name": row["dimension_name"][:50] if row["dimension_name"] else "",
            "total_value": float(row["total_value"]),
        }

    # Chapter sums per budget
    chapter_sums_df = get_expense_sums_by_dimension(session, "CHAPTER")
    chapter_sums: Dict[str, Dict] = defaultdict(dict)
    for _, row in chapter_sums_df.iterrows():
        chapter_sums[row["budget_identifier"]][row["dimension_identifier"]] = {
            "name": row["dimension_name"][:50] if row["dimension_name"] else "",
            "total_value": float(row["total_value"]),
        }

    return {
        "generated_at": datetime.now().isoformat(),
        "totals": totals,
        "budgets": budget_stats,
        "dimension_coverage": coverage_stats,
        "sums_by_ministry": dict(ministry_sums),
        "sums_by_chapter": dict(chapter_sums),
    }


def compute_checksum(stats: Dict) -> str:
    """
    Compute a checksum of the summary statistics.

    Useful for quick comparison between runs.
    """
    # Create a deterministic string representation
    # Only use numeric values that shouldn't change
    key_values = []

    # Total counts
    key_values.append(f"budgets:{stats['totals']['budgets']}")
    key_values.append(f"expenses:{stats['totals']['expenses']}")
    key_values.append(f"dimensions:{stats['totals']['dimensions']}")

    # Per-budget expense counts and totals
    for budget_id in sorted(stats["budgets"].keys()):
        b = stats["budgets"][budget_id]
        key_values.append(f"{budget_id}:count:{b['expense_count']}")
        key_values.append(f"{budget_id}:total:{b['total_value']:.2f}")

    checksum_str = "|".join(key_values)
    return hashlib.md5(checksum_str.encode()).hexdigest()[:16]


# =============================================================================
# OUTPUT FUNCTIONS
# =============================================================================


def write_log(log_path: Path, lines: List[str]):
    """Write lines to log file."""
    with open(log_path, "w", encoding="utf-8") as f:
        for line in lines:
            f.write(line + "\n")


def format_value(value: float) -> str:
    """Format value with thousands separator."""
    return f"{value:,.2f}"


def generate_log_content(
    budgets_df: pd.DataFrame,
    expense_dims_df: pd.DataFrame,
    expense_types_df: pd.DataFrame,
    coverage_df: pd.DataFrame,
    problems: Dict,
    missing_types: List[Dict],
    totals: Dict,
) -> List[str]:
    """Generate the log file content."""
    lines = []
    timestamp = datetime.now().isoformat()

    # Header
    lines.append("=" * 100)
    lines.append("BUDGET DATA SANITY CHECK REPORT")
    lines.append(f"Generated at: {timestamp}")
    lines.append("=" * 100)

    # Overview
    lines.append("\n" + "=" * 100)
    lines.append("OVERVIEW")
    lines.append("=" * 100)
    lines.append(f"Total Budgets: {totals['budgets']}")
    lines.append(f"Total Expenses: {totals['expenses']}")
    lines.append(f"Total Dimensions: {totals['dimensions']}")
    lines.append("\nDimensions by type:")
    for dim_type, count in sorted(totals["dimensions_by_type"].items()):
        lines.append(f"  {dim_type}: {count}")

    # Budgets list
    lines.append("\n" + "-" * 100)
    lines.append("BUDGETS IN DATABASE:")
    lines.append("-" * 100)
    for _, b in budgets_df.iterrows():
        lines.append(
            f"  {b['original_identifier']:<25} Type: {b['type']:<10} Scope: {b['scope'] or 'N/A'}"
        )

    # ==========================================================================
    # ISSUE: Expenses with zero dimensions
    # ==========================================================================
    lines.append("\n" + "=" * 100)
    lines.append("ISSUE: EXPENSES WITH ZERO DIMENSIONS")
    lines.append("=" * 100)

    zero_dims = problems["zero_dimensions"]
    if zero_dims:
        lines.append(f"Found {len(zero_dims)} expenses with NO dimensions!")
        lines.append("")

        # Group by budget
        by_budget = defaultdict(list)
        for exp in zero_dims:
            by_budget[exp["budget_identifier"]].append(exp)

        for budget_id, exps in sorted(by_budget.items()):
            lines.append(f"\n  Budget: {budget_id} ({len(exps)} expenses)")
            for exp in exps[:10]:  # Show first 10
                lines.append(
                    f"    - Expense ID: {exp['expense_id']}, Value: {format_value(exp['value'])} RUB"
                )
            if len(exps) > 10:
                lines.append(f"    ... and {len(exps) - 10} more")
    else:
        lines.append("✓ All expenses have at least one dimension.")

    # ==========================================================================
    # ISSUE: Expenses with only one dimension
    # ==========================================================================
    lines.append("\n" + "=" * 100)
    lines.append("ISSUE: EXPENSES WITH ONLY ONE DIMENSION")
    lines.append("=" * 100)

    one_dim = problems["one_dimension"]
    if one_dim:
        lines.append(f"Found {len(one_dim)} expenses with only ONE dimension!")
        lines.append("")

        # Group by budget
        by_budget = defaultdict(list)
        for exp in one_dim:
            by_budget[exp["budget_identifier"]].append(exp)

        for budget_id, exps in sorted(by_budget.items()):
            lines.append(f"\n  Budget: {budget_id} ({len(exps)} expenses)")
            for exp in exps[:10]:
                lines.append(
                    f"    - Expense ID: {exp['expense_id']}, Value: {format_value(exp['value'])} RUB"
                )
            if len(exps) > 10:
                lines.append(f"    ... and {len(exps) - 10} more")
    else:
        lines.append("✓ All expenses have more than one dimension.")

    # ==========================================================================
    # ISSUE: Expenses missing expected dimension types
    # ==========================================================================
    lines.append("\n" + "=" * 100)
    lines.append("ISSUE: EXPENSES MISSING EXPECTED DIMENSION TYPES")
    lines.append("(Expected: MINISTRY, CHAPTER, EXPENSE_TYPE)")
    lines.append("=" * 100)

    if missing_types:
        lines.append(f"Found {len(missing_types)} expenses missing expected dimension types!")
        lines.append("")

        # Group by missing type combination
        by_missing = defaultdict(list)
        for exp in missing_types:
            key = ", ".join(exp["missing_types"])
            by_missing[key].append(exp)

        for missing_key, exps in sorted(by_missing.items()):
            lines.append(f"\n  Missing [{missing_key}]: {len(exps)} expenses")

            # Further group by budget
            by_budget = defaultdict(list)
            for exp in exps:
                by_budget[exp["budget_identifier"]].append(exp)

            for budget_id, budget_exps in sorted(by_budget.items()):
                lines.append(f"    Budget {budget_id}: {len(budget_exps)} expenses")
                for exp in budget_exps[:5]:
                    lines.append(
                        f"      - ID: {exp['expense_id']}, "
                        f"Has: [{', '.join(exp['has_types'])}], "
                        f"Value: {format_value(exp['value'])} RUB"
                    )
                if len(budget_exps) > 5:
                    lines.append(f"      ... and {len(budget_exps) - 5} more")
    else:
        lines.append("✓ All expenses have the expected dimension types.")

    # ==========================================================================
    # DIMENSION COVERAGE BY BUDGET
    # ==========================================================================
    lines.append("\n" + "=" * 100)
    lines.append("DIMENSION COVERAGE BY BUDGET")
    lines.append("=" * 100)

    dimension_types = ["MINISTRY", "CHAPTER", "SUBCHAPTER", "PROGRAM", "EXPENSE_TYPE"]

    for _, budget in budgets_df.iterrows():
        budget_id = budget["original_identifier"]
        budget_expenses = expense_dims_df[expense_dims_df["budget_identifier"] == budget_id]
        total_expenses = len(budget_expenses)

        if total_expenses == 0:
            continue

        lines.append(f"\n{'-' * 100}")
        lines.append(f"Budget: {budget_id} (Type: {budget['type']}, {total_expenses} expenses)")
        lines.append(f"{'-' * 100}")

        budget_coverage = coverage_df[coverage_df["budget_identifier"] == budget_id]

        for dim_type in dimension_types:
            type_coverage = budget_coverage[budget_coverage["dimension_type"] == dim_type]
            if len(type_coverage) > 0:
                count = int(type_coverage.iloc[0]["expense_count"])
                pct = count / total_expenses * 100
                total_val = float(type_coverage.iloc[0]["total_value"])
                status = "✓" if pct >= 99.9 else "⚠" if pct >= 50 else "✗"
                lines.append(
                    f"  {status} {dim_type:<15}: {count:>6}/{total_expenses:<6} "
                    f"({pct:>5.1f}%) | Sum: {format_value(total_val):>25} RUB"
                )
            else:
                lines.append(f"  ✗ {dim_type:<15}: {'0':>6}/{total_expenses:<6} (  0.0%)")

    # ==========================================================================
    # SUMMARY
    # ==========================================================================
    lines.append("\n" + "=" * 100)
    lines.append("SUMMARY")
    lines.append("=" * 100)

    total_issues = len(zero_dims) + len(one_dim) + len(missing_types)
    if total_issues == 0:
        lines.append("✓ No issues found! All expenses have proper dimension associations.")
    else:
        lines.append(f"⚠ Found {total_issues} total issues:")
        lines.append(f"  - Expenses with 0 dimensions: {len(zero_dims)}")
        lines.append(f"  - Expenses with 1 dimension: {len(one_dim)}")
        lines.append(f"  - Expenses missing expected types: {len(missing_types)}")

    lines.append("\n" + "=" * 100)
    lines.append("END OF REPORT")
    lines.append("=" * 100)

    return lines


# =============================================================================
# MAIN
# =============================================================================


def main():
    parser = argparse.ArgumentParser(description="Run sanity checks on budget data")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/import_files"),
        help="Output directory for log and JSON files",
    )
    args = parser.parse_args()

    # Create output directory
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = output_dir / f"sanity_check_{timestamp}.log"
    json_path = output_dir / f"sanity_check_{timestamp}.json"

    logger.info("Running sanity checks...")
    logger.info(f"Output directory: {output_dir.absolute()}")

    with get_sync_session() as session:
        # Fetch data
        logger.info("Fetching budgets...")
        budgets_df = get_all_budgets(session)

        if budgets_df.empty:
            logger.warning("No budgets found in database!")
            return

        logger.info(f"Found {len(budgets_df)} budgets")

        logger.info("Fetching expense dimension counts...")
        expense_dims_df = get_expense_dimension_counts(session)
        logger.info(f"Found {len(expense_dims_df)} expenses")

        logger.info("Fetching expense dimension types...")
        expense_types_df = get_expense_dimension_types(session)

        logger.info("Fetching dimension coverage...")
        coverage_df = get_dimension_coverage_by_budget(session)

        logger.info("Fetching totals...")
        totals = get_total_counts(session)

        # Analyze
        logger.info("Analyzing for issues...")
        problems = find_problematic_expenses(expense_dims_df)
        missing_types = find_missing_dimension_types(expense_types_df)

        # Generate log
        logger.info("Generating log...")
        log_lines = generate_log_content(
            budgets_df,
            expense_dims_df,
            expense_types_df,
            coverage_df,
            problems,
            missing_types,
            totals,
        )
        write_log(log_path, log_lines)
        logger.info(f"Log saved to: {log_path}")

        # Generate JSON summary
        logger.info("Generating summary statistics...")
        summary_stats = calculate_summary_statistics(
            session, budgets_df, expense_dims_df, coverage_df
        )

        # Add issues summary to JSON
        summary_stats["issues"] = {
            "zero_dimensions_count": len(problems["zero_dimensions"]),
            "one_dimension_count": len(problems["one_dimension"]),
            "missing_types_count": len(missing_types),
            "zero_dimensions": problems["zero_dimensions"][:100],  # Limit for JSON size
            "one_dimension": problems["one_dimension"][:100],
            "missing_types": missing_types[:100],
        }

        # Add checksum
        summary_stats["checksum"] = compute_checksum(summary_stats)

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(summary_stats, f, indent=2, ensure_ascii=False)
        logger.info(f"JSON saved to: {json_path}")

        # Summary
        total_issues = (
            len(problems["zero_dimensions"]) + len(problems["one_dimension"]) + len(missing_types)
        )
        logger.info("=" * 60)
        logger.info("SANITY CHECK COMPLETE")
        logger.info("=" * 60)
        logger.info(f"Checksum: {summary_stats['checksum']}")
        logger.info(f"Budgets: {totals['budgets']}")
        logger.info(f"Expenses: {totals['expenses']}")
        logger.info(f"Dimensions: {totals['dimensions']}")

        if total_issues == 0:
            logger.info("No issues found!")
        else:
            logger.warning(f"Found {total_issues} issues:")
            logger.warning(f"  - Expenses with 0 dimensions: {len(problems['zero_dimensions'])}")
            logger.warning(f"  - Expenses with 1 dimension: {len(problems['one_dimension'])}")
            logger.warning(f"  - Missing expected types: {len(missing_types)}")


if __name__ == "__main__":
    main()
