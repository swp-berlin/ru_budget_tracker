"""
Data fetching utilities for budget visualization.

This module provides classes for fetching and preparing budget data
for treemap and bar chart visualizations.
"""

from typing import Any, Sequence
from datetime import date
from functools import lru_cache

from sqlalchemy import RowMapping, Select, and_, extract, func, or_, select
from sqlalchemy.orm import aliased

from database import get_sync_session
from models import Budget, Dimension, Expense
from utils.definitions import SpendingTypeLiteral, QUARTERLY_MONTHS

# =============================================================================
# Constants
# =============================================================================

# Valid dimension types for treemap hierarchy
TREEMAP_DIMENSION_TYPES = ["MINISTRY", "CHAPTER", "SUBCHAPTER", "PROGRAM"]

# Quarterly months for execution budget filtering
QUARTERLY_MONTHS = [3, 6, 9, 12]


# =============================================================================
# Helper Functions
# =============================================================================


def _execute_query(stmt: Select, unique: bool = True) -> Sequence[RowMapping]:
    """
    Execute a select statement and return mappings.

    Args:
        stmt: The SQLAlchemy select statement to execute.
        unique: If True, apply .unique() for queries with ORM relationships.
                Set to False for expression-only queries (aggregates, labels).

    Returns:
        Sequence of row mappings from the query result.
    """
    with get_sync_session() as session:
        result = session.execute(stmt)
        if unique:
            result = result.unique()
        return result.mappings().all()


def _build_dimension_name_column(translated: bool = False):
    """
    Build the concatenated dimension name column expression.

    Args:
        translated: If True, use translated name; otherwise use original name.

    Returns:
        SQLAlchemy column expression for concatenated dimension name.
    """
    name_field = Dimension.name_translated if translated else Dimension.name
    return func.CONCAT(Dimension.original_identifier, " - ", name_field)


@lru_cache(maxsize=1)
def fetch_budgets_for_dropdown() -> list[dict[str, Any]]:
    """
    Load all non-TOTAL budgets for the dropdown selector.

    Returns:
        List of budget dictionaries with id, original_identifier, and type.
    """
    stmt = (
        select(Budget.id, Budget.original_identifier, Budget.type)
        .where(Budget.type.not_like("TOTAL%"))
        .order_by(Budget.published_at.desc(), Budget.original_identifier.desc())
    )
    return [dict(budget) for budget in _execute_query(stmt)]


# =============================================================================
# Treemap Data Fetcher
# =============================================================================


class TreemapDataFetcher:
    """Fetches and prepares data for treemap visualization."""

    @lru_cache(maxsize=10)
    def get_published_at_date(self, budget_id: int) -> date:
        """
        Fetch the published_at date for a given budget ID.

        Args:
            budget_id: The ID of the budget to fetch.
        Returns:
            The published_at date
        """
        stmt = select(Budget.published_at).where(Budget.id == budget_id)
        with get_sync_session() as session:
            date = session.execute(stmt).scalar_one_or_none()
        if date is None:
            raise ValueError(f"Budget with ID {budget_id} not found.")
        return date

    def fetch_relevant_budgets(self, budget_id: int) -> tuple[Budget, Budget]:
        """
        Fetch the initial budget and any corresponding TOTAL budgets.

        Args:
            budget_id: The ID of the primary budget to fetch.

        Returns:
            List containing the initial budget followed by related TOTAL budgets.

        Raises:
            ValueError: If the budget with the given ID is not found.
        """
        # Fetch the initial budget
        with get_sync_session() as session:
            initial_budget = session.scalars(
                select(Budget).where(Budget.id == budget_id)
            ).one_or_none()

        if initial_budget is None:
            raise ValueError(f"Budget with ID {budget_id} not found.")

        # Fetch related TOTAL budgets from the same year/month
        total_budgets_stmt = (
            select(Budget)
            .where(Budget.type == "TOTAL")
            .where(extract("year", Budget.published_at) == initial_budget.published_at.year)
            .where(extract("month", Budget.published_at) == initial_budget.published_at.month)
        )

        if initial_budget.type == "LAW":
            total_budgets_stmt = total_budgets_stmt.where(Budget.original_identifier.like("%LAW%"))
        elif initial_budget.type == "REPORT":
            total_budgets_stmt = total_budgets_stmt.where(
                Budget.original_identifier.like("%EXPENSE%")
            )

        with get_sync_session() as session:
            total_budget = session.execute(total_budgets_stmt).scalar_one_or_none()
        if total_budget is None:
            raise ValueError(
                f"No corresponding TOTAL budget found for budget ID {budget_id} with published_at {initial_budget.published_at}."
            )

        # Return initial budget first, then related TOTAL budgets (excluding duplicates)
        return initial_budget, total_budget

    def _fetch_treemap_dimensions(self, budget_id: int) -> Sequence[RowMapping]:
        """
        Fetch all dimensions associated with expenses for the given budget.

        Args:
            budget_id: The budget ID to fetch dimensions for.

        Returns:
            Sequence of dimension row mappings with budget and dimension info.

        Raises:
            ValueError: If no relevant budgets are found.
        """
        initial_budget, totals_budget = self.fetch_relevant_budgets(budget_id=budget_id)

        parent_dimension = aliased(Dimension)
        stmt = (
            select(
                Expense.id,
                Expense.value,
                Budget.id.label("budget_id"),
                Budget.original_identifier.label("budget_original_identifier"),
                Budget.type.label("budget_type"),
                Dimension.id.label("dimension_id"),
                Dimension.original_identifier.label("dimension_original_identifier"),
                Dimension.parent_id.label("dimension_parent_id"),
                Dimension.type.label("dimension_type"),
                parent_dimension.id.label("parent_dimension_id"),
                parent_dimension.original_identifier.label("parent_dimension_original_identifier"),
                parent_dimension.type.label("parent_dimension_type"),
                _build_dimension_name_column(translated=False).label("dimension_name"),
                _build_dimension_name_column(translated=True).label("dimension_name_translated"),
            )
            .join(Expense.dimensions, isouter=True)
            .join(Expense.budget, isouter=True)
            .join(parent_dimension, Dimension.parent_id == parent_dimension.id, isouter=True)
        )

        if initial_budget.type == "LAW":
            stmt = stmt.where(
                or_(
                    and_(
                        Budget.id == initial_budget.id, Dimension.type.in_(TREEMAP_DIMENSION_TYPES)
                    ),
                    and_(
                        Budget.id == totals_budget.id,
                        Dimension.type.in_(["CHAPTER"]),
                    ),
                )
            )

        elif initial_budget.type == "REPORT":
            stmt = stmt.where(
                or_(
                    and_(
                        Budget.id == initial_budget.id, Dimension.type.in_(TREEMAP_DIMENSION_TYPES)
                    ),
                    and_(Budget.id == totals_budget.id, Dimension.type.is_(None)),
                )
            )

        return _execute_query(stmt)

    def _fetch_treemap_programs_recursive(
        self, leaf_program_ids: list[int]
    ) -> Sequence[RowMapping]:
        """
        Fetch all programs in the hierarchy using a recursive CTE.

        Traverses from leaf programs up to their parent programs to build
        the complete program hierarchy.

        Args:
            leaf_program_ids: List of leaf-level program dimension IDs.

        Returns:
            Sequence of program dimension row mappings.
        """
        if not leaf_program_ids:
            return []

        # Base columns for the CTE
        base_columns = [
            Dimension.id.label("dimension_id"),
            Dimension.parent_id.label("dimension_parent_id"),
            Dimension.original_identifier.label("dimension_original_identifier"),
            _build_dimension_name_column(translated=False).label("dimension_name"),
            _build_dimension_name_column(translated=True).label("dimension_name_translated"),
        ]

        # Base case: start with leaf programs
        base_stmt = select(*base_columns).where(Dimension.id.in_(leaf_program_ids))
        programs_cte = base_stmt.cte("program_hierarchy", recursive=True)

        # Recursive case: join to get parent programs
        recursive_stmt = (
            select(*base_columns)
            .select_from(Dimension)
            .join(programs_cte, Dimension.id == programs_cte.c.dimension_parent_id)
            .where(Dimension.type == "PROGRAM")
        )

        # Union base and recursive parts
        full_cte = programs_cte.union_all(recursive_stmt)

        # Final select from the CTE
        final_stmt = select(
            full_cte.c.dimension_id,
            full_cte.c.dimension_parent_id,
            full_cte.c.dimension_original_identifier,
            full_cte.c.dimension_name,
            full_cte.c.dimension_name_translated,
        )

        return _execute_query(final_stmt)

    @lru_cache(maxsize=10)
    def fetch_data(
        self,
        budget_id: int | None = None,
    ) -> tuple[Sequence[RowMapping], Sequence[RowMapping]]:
        """
        Fetch all data needed for treemap visualization.

        Args:
            budget_id: The budget ID to fetch data for.
            unit: The unit type (currently unused, reserved for future use).

        Returns:
            Tuple of (dimensions, programs, sum_mapping).
        """
        if budget_id is None:
            return [], []

        # Fetch dimensions and calculate sums
        dimensions = self._fetch_treemap_dimensions(budget_id=budget_id)

        # Fetch program hierarchy - extract program IDs inline to avoid extra iteration.
        program_ids = [r["dimension_id"] for r in dimensions if r["dimension_type"] == "PROGRAM"]
        programs = self._fetch_treemap_programs_recursive(program_ids)

        return dimensions, programs


# =============================================================================
# Bar Chart Data Fetcher
# =============================================================================


class BarChartDataFetcher:
    """Fetches and prepares data for bar chart (timeseries) visualization."""

    def __init__(self, spending_type: SpendingTypeLiteral = "ALL") -> None:
        self.spending_type: SpendingTypeLiteral = spending_type

    def get_published_at_date(self, budget_id: int) -> date:
        """
        Fetch the published_at date for a given budget ID.

        Args:
            budget_id: The ID of the budget to fetch.
        Returns:
            The published_at date
        """
        stmt = select(Budget.published_at).where(Budget.id == budget_id)
        with get_sync_session() as session:
            date = session.execute(stmt).scalar_one_or_none()
        if date is None:
            raise ValueError(f"Budget with ID {budget_id} not found.")
        return date

    def _fetch_budget(self, budget_id: int) -> Budget:
        """
        Fetch a single budget by ID.

        Args:
            budget_id: The ID of the budget to fetch.

        Returns:
            The Budget object.

        Raises:
            ValueError: If the budget is not found.
        """
        with get_sync_session() as session:
            budget = session.scalars(select(Budget).where(Budget.id == budget_id)).one_or_none()

        if budget is None:
            raise ValueError(f"Budget with ID {budget_id} not found.")

        return budget

    def _get_budget_expense_columns(self) -> list:
        """Get common columns for budget expense queries."""
        return [
            Budget.id,
            Budget.original_identifier,
            Budget.published_at,
            Budget.type,
        ]

    def _fetch_descendant_dimension_ids(self, dimension_id: int) -> list[int]:
        """Return the selected dimension id plus all descendant ids."""
        base_stmt = select(
            Dimension.id.label("dimension_id"),
            Dimension.parent_id.label("parent_id"),
        ).where(Dimension.id == dimension_id)
        dim_cte = base_stmt.cte("dimension_tree", recursive=True)
        recursive_stmt = select(
            Dimension.id.label("dimension_id"),
            Dimension.parent_id.label("parent_id"),
        ).where(Dimension.parent_id == dim_cte.c.dimension_id)
        full_cte = dim_cte.union_all(recursive_stmt)
        stmt = select(full_cte.c.dimension_id)
        rows = _execute_query(stmt, unique=False)
        return [row["dimension_id"] for row in rows]

    def _fetch_budget_expenses_for_dimensions(
        self,
        budget_types: list[str],
        dimension_ids: list[int],
        quarterly_only: bool,
    ) -> Sequence[RowMapping]:
        """Fetch summed expenses for budgets filtered by dimension ids."""
        from models.budget import expense_dimension_association_table as assoc_table

        base_columns = self._get_budget_expense_columns()

        # Select distinct expenses to avoid double counting across multiple dimensions.
        expenses_subquery = (
            select(
                Expense.id.label("expense_id"),
                Expense.budget_id.label("budget_id"),
                func.abs(Expense.value).label("value"),  # Ensure no negative values in sums.
            )
            .select_from(Expense)
            .join(assoc_table, Expense.id == assoc_table.c.expense_id)
            .join(Dimension, assoc_table.c.dimension_id == Dimension.id)
            .where(Dimension.id.in_(dimension_ids))
            .distinct(Expense.id)
            .subquery()
        )

        stmt = (
            select(*base_columns, func.sum(expenses_subquery.c.value).label("total_value"))
            .select_from(Budget)
            .join(expenses_subquery, Budget.id == expenses_subquery.c.budget_id)
            .where(Budget.type.in_(budget_types))
            .group_by(*base_columns)
        )

        if quarterly_only:
            stmt = stmt.where(extract("month", Budget.published_at).in_(QUARTERLY_MONTHS))

        with get_sync_session() as session:
            return session.execute(stmt).mappings().all()

    def _fetch_law_budget_expenses(self) -> Sequence[RowMapping]:
        """
        Fetch LAW budgets and their corresponding TOTAL budgets.

        Returns a union of:
        - LAW budgets with MINISTRY dimension expenses (summed)
        - TOTAL budgets with CHAPTER dimension expenses (summed * 1000)

        Returns:
            Sequence of budget expense row mappings.
        """
        from models.budget import expense_dimension_association_table as assoc_table

        base_columns = self._get_budget_expense_columns()

        # LAW budgets with MINISTRY dimensions
        law_ministry_stmt = (
            select(*base_columns, func.sum(func.abs(Expense.value)).label("total_value"))
            .select_from(Budget)
            .join(Expense, Budget.id == Expense.budget_id, isouter=True)
            .join(assoc_table, Expense.id == assoc_table.c.expense_id, isouter=True)
            .join(Dimension, assoc_table.c.dimension_id == Dimension.id, isouter=True)
            .where(Budget.type == "LAW")
            .where(Dimension.type == "MINISTRY")
            .group_by(Budget.id, Budget.original_identifier, Budget.type)
        )

        if self.spending_type == "MILITARY":
            law_ministry_stmt = law_ministry_stmt.where(Dimension.original_identifier.like("187%"))

        # TOTAL budgets with CHAPTER dimensions (values stored in thousands)
        total_chapter_stmt = (
            select(
                *base_columns,
                (func.sum(func.abs(Expense.value))).label("total_value"),
            )
            .select_from(Budget)
            .join(Expense, Budget.id == Expense.budget_id, isouter=True)
            .join(assoc_table, Expense.id == assoc_table.c.expense_id, isouter=True)
            .join(Dimension, assoc_table.c.dimension_id == Dimension.id, isouter=True)
            .where(Budget.type == "TOTAL")
            .where(Budget.original_identifier.like("%LAW%"))
            .where(Dimension.type == "CHAPTER")
            .group_by(Budget.id, Budget.original_identifier, Budget.type)
        )

        if self.spending_type == "MILITARY":
            total_chapter_stmt = total_chapter_stmt.where(Dimension.original_identifier.like("02%"))

        union_stmt = law_ministry_stmt.union(total_chapter_stmt)

        with get_sync_session() as session:
            return session.execute(union_stmt).mappings().all()

    def _fetch_execution_budget_expenses(self) -> Sequence[RowMapping]:
        """
        Fetch REPORT budgets and their corresponding TOTAL budgets.

        Includes:
        - REPORT budgets with MINISTRY dimension
        - TOTAL budgets with NULL dimension (expense totals)

        Only includes quarterly data (months 3, 6, 9, 12).

        Returns:
            Sequence of budget expense row mappings.
        """
        base_columns = self._get_budget_expense_columns()

        stmt = (
            select(*base_columns, func.sum(func.abs(Expense.value)).label("total_value"))
            .select_from(Budget)
            .join(Expense, Budget.id == Expense.budget_id, isouter=True)
            .join(Expense.dimensions, isouter=True)
            .where(Budget.type.in_(["REPORT", "TOTAL"]))
            .where(
                or_(
                    # REPORT budgets with MINISTRY dimension
                    and_(Dimension.type == "MINISTRY", Budget.type == "REPORT"),
                    # TOTAL expense budgets (no dimension association)
                    and_(
                        Dimension.type.is_(None),
                        Budget.type == "TOTAL",
                        Budget.original_identifier.like("%EXPENSE%"),
                    ),
                )
            )
            .where(extract("month", Budget.published_at).in_(QUARTERLY_MONTHS))
            .group_by(Budget.id, Budget.original_identifier, Budget.type)
        )

        with get_sync_session() as session:
            results = session.execute(stmt).mappings().all()

        return results

    def fetch_budgets(self, budget_id: int) -> tuple[Sequence[RowMapping], str]:
        """
        Fetch budget expenses based on the budget type.

        Args:
            budget_id: The ID of the budget to determine the fetch type.

        Returns:
            Tuple of (budget expense rows, budget category string).

        Raises:
            ValueError: If the budget type is not supported.
        """
        initial_budget = self._fetch_budget(budget_id)

        if initial_budget.type == "REPORT":
            return self._fetch_execution_budget_expenses(), "EXECUTION"
        elif initial_budget.type == "LAW":
            return self._fetch_law_budget_expenses(), "LAW"
        else:
            raise ValueError(f"Unsupported budget type: {initial_budget.type} for ID {budget_id}")

    def fetch_budgets_filtered(
        self, budget_id: int, dimension_id: int
    ) -> tuple[Sequence[RowMapping], str]:
        """Fetch budget expenses filtered by a selected dimension and its descendants."""
        initial_budget = self._fetch_budget(budget_id)
        dimension_ids = self._fetch_descendant_dimension_ids(dimension_id)

        if initial_budget.type == "REPORT":
            return (
                self._fetch_budget_expenses_for_dimensions(
                    ["REPORT"],
                    dimension_ids,
                    quarterly_only=True,
                ),
                "EXECUTION",
            )
        elif initial_budget.type == "LAW":
            return (
                self._fetch_budget_expenses_for_dimensions(
                    ["LAW"],
                    dimension_ids,
                    quarterly_only=False,
                ),
                "LAW",
            )
        else:
            raise ValueError(f"Unsupported budget type: {initial_budget.type} for ID {budget_id}")

    def fetch_data(
        self,
        budget_id: int | None = None,
        dimension_id: int | None = None,
    ) -> tuple[Sequence[RowMapping], str]:
        """
        Fetch budget and expense data for bar chart visualization.

        Args:
            budget_id: The budget ID to fetch data for.
            unit: The unit type (currently unused, reserved for future use).

        Returns:
            Tuple of (budget expense rows, budget category string).

        Raises:
            ValueError: If budget_id is not provided.
        """
        if budget_id is None:
            raise ValueError("budget_id must be provided to fetch data.")
        # Filter to the selected dimension when provided.
        if dimension_id is not None:
            return self.fetch_budgets_filtered(budget_id=budget_id, dimension_id=dimension_id)

        return self.fetch_budgets(budget_id=budget_id)
