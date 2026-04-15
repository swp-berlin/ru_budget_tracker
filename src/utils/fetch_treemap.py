"""
Treemap data fetching utilities for budget visualization.

This module provides helpers and the TreemapDataFetcher class for fetching
and preparing budget data for treemap visualization.
"""

from typing import Any, Sequence
from datetime import date
from functools import lru_cache

from sqlalchemy import (
    RowMapping,
    Select,
    and_,
    extract,
    func,
    or_,
    select,
    case,
)
from database import get_sync_session
from models import Budget, Dimension, Expense
from utils.definitions import (
    budget_config,
)

# =============================================================================
# Constants
# =============================================================================

# Valid dimension types for treemap hierarchy
TREEMAP_DIMENSION_TYPES = ["MINISTRY", "CHAPTER", "SUBCHAPTER", "PROGRAM"]


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
    return case(
        (Dimension.type == "PROGRAM", name_field),
        else_=func.CONCAT(Dimension.original_identifier, " ", name_field),
    )


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

        stmt = (
            select(
                Expense.id,
                case(
                    (
                        and_(
                            Budget.type == "LAW",
                            extract("year", Budget.published_at).in_([2018, 2019]),
                        ),
                        Expense.value * budget_config.law_18_19_value_multiplier,
                    ),
                    else_=Expense.value,
                ).label("value"),
                Budget.type.label("budget_type"),
                Dimension.id.label("dimension_id"),
                Dimension.original_identifier.label("dimension_original_identifier"),
                Dimension.type.label("dimension_type"),
                _build_dimension_name_column(translated=False).label("dimension_name"),
                _build_dimension_name_column(translated=True).label("dimension_name_translated"),
            )
            .join(Expense.dimensions, isouter=True)
            .join(Expense.budget, isouter=True)
        )

        if initial_budget.type == "LAW":
            stmt = stmt.where(
                or_(
                    and_(
                        Budget.id == initial_budget.id, Dimension.type.in_(TREEMAP_DIMENSION_TYPES)
                    ),
                    and_(
                        Budget.id == totals_budget.id,
                        Dimension.type == "CHAPTER",
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

        return _execute_query(stmt, unique=False)

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

        return _execute_query(final_stmt, unique=False)

    def fetch_data(
        self,
        budget_id: int | None = None,
    ) -> tuple[Sequence[RowMapping], Sequence[RowMapping]]:
        """
        Fetch all data needed for treemap visualization.

        Args:
            budget_id: The budget ID to fetch data for.

        Returns:
            Tuple of (dimensions, programs).
        """
        if budget_id is None:
            return [], []

        # Fetch dimensions and calculate sums
        dimensions = self._fetch_treemap_dimensions(budget_id=budget_id)

        # Fetch program hierarchy - extract program IDs inline to avoid extra iteration.
        program_ids = [r["dimension_id"] for r in dimensions if r["dimension_type"] == "PROGRAM"]
        programs = self._fetch_treemap_programs_recursive(program_ids)

        return dimensions, programs
