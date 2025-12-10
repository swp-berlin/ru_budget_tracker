from typing import Any, Sequence
from database import get_sync_session
from models import Budget, Dimension, Expense
from sqlalchemy import RowMapping, func, select

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


class TremapDataFetcher:
    def _fetch_treemap_dimensions(self, budget_id: int | None = None) -> Sequence[RowMapping]:
        """
        Load data from the database based on provided filters.
        Loads budgets, expenses, and dimensions, applies filters, and returns the result set.
        Query is built dynamically and uses a recursive CTE to fetch the full dimension hierarchy.
        Args:
            **kwargs: Filter parameters such as budget_dataset, viewby, spending_type, spending_scope.
        Returns:
            pd.DataFrame: The loaded and transformed data.
        """
        select_stmt = (
            select(
                Expense.id,
                Dimension.id.label("dimension_id"),
                Dimension.parent_id.label("dimension_parent_id"),
                Dimension.type.label("dimension_type"),
                func.CONCAT(Dimension.original_identifier, " - ", Dimension.name).label(
                    "dimension_name"
                ),
                func.CONCAT(Dimension.original_identifier, " - ", Dimension.name_translated).label(
                    "dimension_name_translated"
                ),
            )
            .where(
                Dimension.type.in_(["MINISTRY", "CHAPTER", "SUBCHAPTER", "PROGRAM"]),
            )
            .join(Expense.dimensions)
        )

        if budget_id is not None:
            select_stmt = select_stmt.where(Expense.budget_id == budget_id)

        with get_sync_session() as session:
            dimensions = session.execute(select_stmt).unique().mappings().all()

        return dimensions

    def _create_treemap_value_sums_mapping(self, budget_id: int) -> dict[int, float]:
        sum_stmt = (
            select(
                Dimension.id.label("dimension_id"),
                func.sum(Expense.value).label("total_expense_value"),
            )
            .where(
                Expense.budget_id == budget_id,
                Dimension.type.in_(["MINISTRY", "CHAPTER", "SUBCHAPTER", "PROGRAM"]),
            )
            .join(Expense.dimensions)
            .group_by(Dimension.id)
        )

        with get_sync_session() as session:
            sums = session.execute(sum_stmt).unique().mappings().all()

        return {sum["dimension_id"]: sum["total_expense_value"] for sum in sums}

    def _fetch_treemap_programs_recursive(
        self, leave_program_ids: list[int]
    ) -> Sequence[RowMapping]:
        # Build the base select statement for the CTE
        child_programs_cte = (
            select(
                Dimension.id.label("dimension_id"),
                Dimension.parent_id.label("dimension_parent_id"),
                func.CONCAT(Dimension.original_identifier, " - ", Dimension.name).label(
                    "dimension_name"
                ),
            ).where(Dimension.id.in_(leave_program_ids))
        ).cte("program_hierarchy", recursive=True)

        # Recursive part to get parent dimensions
        parent_select_stmt = (
            select(
                Dimension.id.label("dimension_id"),
                Dimension.parent_id.label("dimension_parent_id"),
                func.CONCAT(Dimension.original_identifier, " - ", Dimension.name).label(
                    "dimension_name"
                ),
            )
            .select_from(Dimension)
            .join(child_programs_cte, Dimension.id == child_programs_cte.c.dimension_parent_id)
            .where(Dimension.type == "PROGRAM")
        )
        # Union the base and recursive parts to get all programs belonging to the relevant expenses
        union = child_programs_cte.union_all(parent_select_stmt)
        select_stmt = select(
            union.c.dimension_id,
            union.c.dimension_parent_id,
            union.c.dimension_name,
        )

        with get_sync_session() as session:
            programs = session.execute(select_stmt).unique().mappings().all()

        return programs

    def fetch_data(
        self, budget_id: int | None = None, **kwargs
    ) -> tuple[Sequence[RowMapping], Sequence[RowMapping], dict[int, float]]:
        """
        Load data from the database based on provided filters.
        Loads budgets, expenses, and dimensions, applies filters, and returns the result set.
        Query is built dynamically and uses a recursive CTE to fetch the full dimension hierarchy.
        Args:
            **kwargs: Filter parameters such as budget_dataset, viewby, spending_type, spending_scope.
        Returns:
            Sequence[RowMapping]: The loaded dimensions data.
            Sequence[RowMapping]: The loaded programs data. Includes all programs in the hierarchy.
        """
        if budget_id is None:
            return [], [], {}

        dimensions = self._fetch_treemap_dimensions(budget_id=budget_id)
        program_dimension_ids = [
            row["dimension_id"] for row in dimensions if row["dimension_type"] == "PROGRAM"
        ]
        programs = self._fetch_treemap_programs_recursive(program_dimension_ids)

        sum_mapping = self._create_treemap_value_sums_mapping(budget_id=budget_id)

        return dimensions, programs, sum_mapping


# TODO Fix
class BarChartDataFetcher:
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
