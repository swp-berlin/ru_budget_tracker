from typing import Any, Sequence
from database import get_sync_session
from models import Budget, Dimension, Expense
from sqlalchemy import RowMapping, select

from utils.definitions import HIERARCHY_OBJECTS


def fetch_budgets() -> list[dict[str, Any]]:
    """Load all budgets from the database."""
    with get_sync_session() as session:
        budgets = (
            session.execute(select(Budget.id, Budget.name, Budget.name_translated, Budget.type))
            .unique()
            .mappings()
            .all()
        )
    return [dict(budget) for budget in budgets]


def fetch_treemap_data(**kwargs) -> Sequence[RowMapping]:
    """
    Load data from the database based on provided filters.
    Loads budgets, expenses, and dimensions, applies filters, and returns the result set.
    Query is built dynamically and uses a recursive CTE to fetch the full dimension hierarchy.
    Args:
        **kwargs: Filter parameters such as budget_dataset, viewby, spending_type, spending_scope.
    Returns:
        pd.DataFrame: The loaded and transformed data.
    """
    # Build the base select statement for the CTE
    base_select_stmt = select(
        Dimension.id.label("dimension_id"),
        Dimension.parent_id.label("dimension_parent_id"),
        Dimension.type.label("dimension_type"),
        Dimension.name.label("dimension_name"),
        Dimension.name_translated.label("dimension_name_translated"),
    ).where(Dimension.type.in_(HIERARCHY_OBJECTS))
    # If dataset filter is provided, add a where clause
    cte = base_select_stmt
    if kwargs.get("budget_dataset") is not None:
        cte = cte.where(
            Dimension.id.in_(
                select(Dimension.id)
                .join(Dimension.expenses)
                .where(Expense.budget_id == kwargs.get("budget_dataset"))
            )
        )

    # If spending type filter is provided, add a where clause
    if kwargs.get("spending_type") != "ALL":
        cte = cte.where(
            Dimension.id.in_(
                select(Dimension.id)
                .join(Dimension.expenses)
                .where(Expense.dimensions.any(Dimension.name == kwargs.get("spending_type")))
            )
        )
    # Finalize the CTE
    cte = cte.cte("dimension_hierarchy", recursive=True)
    # Recursive part to get parent dimensions
    parent_dimensions = base_select_stmt.join(cte, Dimension.id == cte.c.dimension_parent_id)
    # Union the base and recursive parts
    cte = cte.union_all(parent_dimensions)

    # Main select statement joining budgets, expenses, and dimensions
    select_stmt = (
        select(
            Budget.id.label("budget_id"),
            Budget.name.label("budget_name"),
            Budget.name_translated.label("budget_name_translated"),
            Expense.id.label("expense_id"),
            Expense.value.label("expense_value"),
            cte,
        )
        .select_from(cte)
        .join(Dimension.expenses, isouter=True)
        .join(Expense.budget, isouter=True)
    )

    with get_sync_session() as session:
        result = session.execute(select_stmt).mappings().all()

    return result


def fetch_barchart_data(**kwargs) -> Sequence[RowMapping]:
    """
    Load budget and expense data from the database and return as a DataFrame.
    Takes an optional original_identifier to filter budgets.
    """
    # Build the select statement
    # We need to fetch budgets along with their (summed) expenses and the
    select_stmt = (
        select(
            Budget.id.label("budget_id"),
            Budget.original_identifier.label("original_identifier"),
            Budget.published_at.label("published_at"),
            Budget.type.label("type"),
            Expense.id.label("expense_id"),
            Dimension.id.label("dimension_id"),
            Dimension.type.label("dimension_type"),
            Dimension.name.label("dimension_name"),
            Dimension.name_translated.label("dimension_name_translated"),
            Expense.value.label("expense_value"),
        )
        .join(Dimension.expenses, isouter=True)
        .join(Expense.budget, isouter=True)
    )

    if kwargs.get("budget_dataset") is not None:
        select_stmt = select_stmt.where(Budget.id == kwargs.get("budget_dataset"))

    if kwargs.get("spending_type") != "ALL":
        select_stmt = select_stmt.where(
            Dimension.id.in_(
                select(Dimension.id)
                .join(Dimension.expenses)
                .where(Expense.dimensions.any(Dimension.name == kwargs.get("spending_type")))
            )
        )

    with get_sync_session() as session:
        budgets = session.execute(select_stmt).unique().mappings().all()

    return budgets
