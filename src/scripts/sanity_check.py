#!/usr/bin/env python3
"""
Calculate expense sums by ministry and chapter for each budget.

Output: For each unique ministry/chapter original_identifier, show the sum per budget_id.

Usage:
    cd src && uv run python scripts/calculate_expense_sums.py
"""

import sys
from pathlib import Path
from datetime import datetime

import pandas as pd
from sqlalchemy import select, func

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from settings import settings
from database.sessions import get_sync_session
from models import Budget, Expense, Dimension, expense_dimension_association_table


def get_expenses_by_dimension_type(session, dimension_type: str) -> pd.DataFrame:
    """
    Get sum of expenses grouped by dimension original_identifier and budget_id.
    
    Args:
        session: SQLAlchemy session
        dimension_type: Type of dimension (e.g., "CHAPTER", "MINISTRY")
    
    Returns:
        DataFrame with columns: budget_id, budget_original_identifier, 
                                dimension_original_identifier, dimension_name, total_value
    """
    stmt = (
        select(
            Expense.budget_id,
            Budget.original_identifier.label("budget_original_identifier"),
            Dimension.original_identifier.label("dimension_original_identifier"),
            Dimension.name.label("dimension_name"),
            func.sum(Expense.value).label("total_value"),
        )
        .select_from(Expense)
        .join(Budget, Expense.budget_id == Budget.id)
        .join(
            expense_dimension_association_table,
            Expense.id == expense_dimension_association_table.c.expense_id,
        )
        .join(
            Dimension,
            expense_dimension_association_table.c.dimension_id == Dimension.id,
        )
        .where(Dimension.type == dimension_type)
        .group_by(
            Expense.budget_id,
            Budget.original_identifier,
            Dimension.original_identifier,
            Dimension.name,
        )
        .order_by(Dimension.original_identifier, Budget.original_identifier)
    )
    
    result = session.execute(stmt)
    rows = result.fetchall()
    
    if not rows:
        return pd.DataFrame(columns=[
            "budget_id", "budget_original_identifier", 
            "dimension_original_identifier", "dimension_name", "total_value"
        ])
    
    return pd.DataFrame(rows, columns=[
        "budget_id", "budget_original_identifier",
        "dimension_original_identifier", "dimension_name", "total_value"
    ])


def get_all_budgets(session) -> pd.DataFrame:
    """Get all budgets from the database."""
    stmt = select(
        Budget.id,
        Budget.original_identifier,
        Budget.name,
        Budget.type,
        Budget.published_at,
    ).order_by(Budget.published_at, Budget.original_identifier)
    
    result = session.execute(stmt)
    rows = result.fetchall()
    
    return pd.DataFrame(rows, columns=["id", "original_identifier", "name", "type", "published_at"])


def format_value(value: float) -> str:
    """Format value in rubles with thousands separator."""
    return f"{value:,.2f}"


def write_log(log_file: Path, lines: list[str]):
    """Write lines to log file with UTF-8 encoding."""
    with open(log_file, "w", encoding="utf-8") as f:
        for line in lines:
            f.write(line + "\n")


def calculate_and_log_sums():
    """Main function to calculate and log expense sums."""
    log_file = Path("data") / f"expense_sums_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    
    lines = []
    
    lines.append("=" * 100)
    lines.append("EXPENSE SUMS CALCULATION REPORT")
    lines.append(f"Generated at: {datetime.now().isoformat()}")
    lines.append(f"Database: {settings.database.sync_dsn}")
    lines.append("=" * 100)
    
    with get_sync_session() as session:
        # Get budgets info
        budgets_df = get_all_budgets(session)
        
        if budgets_df.empty:
            lines.append("No budgets found in database.")
            write_log(log_file, lines)
            print(f"Log saved to: {log_file.absolute()}")
            return
        
        lines.append(f"\nFound {len(budgets_df)} budget(s):")
        for _, b in budgets_df.iterrows():
            lines.append(f"  - {b['original_identifier']} (ID: {b['id']}, Type: {b['type']})")
        
        # =====================================================================
        # MINISTRY SUMS
        # =====================================================================
        lines.append("\n" + "=" * 100)
        lines.append("EXPENSES BY MINISTRY")
        lines.append("For each ministry original_identifier: sum per budget")
        lines.append("=" * 100)
        
        ministry_df = get_expenses_by_dimension_type(session, "MINISTRY")
        
        if ministry_df.empty:
            lines.append("No MINISTRY expenses found.")
        else:
            # Group by ministry original_identifier
            for ministry_id in ministry_df["dimension_original_identifier"].unique():
                ministry_data = ministry_df[
                    ministry_df["dimension_original_identifier"] == ministry_id
                ]
                ministry_name = ministry_data.iloc[0]["dimension_name"]
                
                lines.append("")
                lines.append("-" * 100)
                lines.append(f"MINISTRY [{ministry_id}]: {ministry_name}")
                lines.append("-" * 100)
                
                for _, row in ministry_data.iterrows():
                    lines.append(
                        f"  Budget {row['budget_original_identifier']:<20} "
                        f"(ID: {row['budget_id']:>3}): "
                        f"{format_value(row['total_value']):>25} RUB"
                    )
                
                # Ministry total across all budgets
                ministry_total = ministry_data["total_value"].sum()
                lines.append(f"  {'TOTAL':<20} {'':>10}: {format_value(ministry_total):>25} RUB")
        
        # =====================================================================
        # CHAPTER SUMS
        # =====================================================================
        lines.append("\n" + "=" * 100)
        lines.append("EXPENSES BY CHAPTER")
        lines.append("For each chapter original_identifier: sum per budget")
        lines.append("=" * 100)
        
        chapter_df = get_expenses_by_dimension_type(session, "CHAPTER")
        
        if chapter_df.empty:
            lines.append("No CHAPTER expenses found.")
        else:
            # Group by chapter original_identifier
            for chapter_id in chapter_df["dimension_original_identifier"].unique():
                chapter_data = chapter_df[
                    chapter_df["dimension_original_identifier"] == chapter_id
                ]
                chapter_name = chapter_data.iloc[0]["dimension_name"]
                
                lines.append("")
                lines.append("-" * 100)
                lines.append(f"CHAPTER [{chapter_id}]: {chapter_name}")
                lines.append("-" * 100)
                
                for _, row in chapter_data.iterrows():
                    lines.append(
                        f"  Budget {row['budget_original_identifier']:<20} "
                        f"(ID: {row['budget_id']:>3}): "
                        f"{format_value(row['total_value']):>25} RUB"
                    )
                
                # Chapter total across all budgets
                chapter_total = chapter_data["total_value"].sum()
                lines.append(f"  {'TOTAL':<20} {'':>10}: {format_value(chapter_total):>25} RUB")
        
        # =====================================================================
        # SUMMARY TABLE
        # =====================================================================
        lines.append("\n" + "=" * 100)
        lines.append("SUMMARY BY BUDGET")
        lines.append("=" * 100)
        
        for _, budget in budgets_df.iterrows():
            budget_ministry = ministry_df[ministry_df["budget_id"] == budget["id"]]
            budget_chapter = chapter_df[chapter_df["budget_id"] == budget["id"]]
            
            ministry_sum = budget_ministry["total_value"].sum() if not budget_ministry.empty else 0
            chapter_sum = budget_chapter["total_value"].sum() if not budget_chapter.empty else 0
            
            lines.append(f"\n{budget['original_identifier']} (ID: {budget['id']}):")
            lines.append(f"  Sum by Ministries: {format_value(ministry_sum):>25} RUB")
            lines.append(f"  Sum by Chapters:   {format_value(chapter_sum):>25} RUB")
    
    lines.append("\n" + "=" * 100)
    lines.append("END OF REPORT")
    lines.append("=" * 100)
    
    # Write to file
    write_log(log_file, lines)
    print(f"Log saved to: {log_file.absolute()}")


if __name__ == "__main__":
    calculate_and_log_sums()