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
    case,
    extract,
    func,
    select,
)
from pydantic import BaseModel
from database import get_sync_session
from models import (
    Budget,
    Dimension,
    Expense,
    LawClassifiedSpendingPerChapter,
    ReportClassifiedSpendingPerChapter,
)

# =============================================================================
# Constants
# =============================================================================

# Valid dimension types for treemap hierarchy
TREEMAP_DIMENSION_TYPES = ["MINISTRY", "CHAPTER", "SUBCHAPTER", "PROGRAM"]


# =============================================================================
# Models
# =============================================================================


class ClassifiedChapterRow(BaseModel):
    """Classified spending data for a single budget chapter."""

    original_identifier: str
    chapter_name: str
    chapter_name_translated: str | None
    classified_spending: float
    dimension_id: int | None  # Real Dimension.id for click-through; None if no match found.


class ClassifiedSpendingData(BaseModel):
    """Classified spending data ready for treemap rendering.

    For LAW budgets: per-chapter rows are populated.
    For REPORT budgets: only total_classified is set.
    """

    budget_type: str  # "LAW" or "REPORT"
    chapters: list[ClassifiedChapterRow] = []
    total_classified: float = 0.0


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
        """
        stmt = (
            select(
                Expense.id,
                Expense.value.label("value"),
                Budget.type.label("budget_type"),
                Dimension.id.label("dimension_id"),
                Dimension.original_identifier.label("dimension_original_identifier"),
                Dimension.type.label("dimension_type"),
                _build_dimension_name_column(translated=False).label("dimension_name"),
                _build_dimension_name_column(translated=True).label("dimension_name_translated"),
            )
            .join(Expense.dimensions, isouter=True)
            .join(Expense.budget, isouter=True)
            .where(Budget.id == budget_id)
            .where(Dimension.type.in_(TREEMAP_DIMENSION_TYPES))
        )

        return _execute_query(stmt, unique=False)

    def fetch_classified_spending(self, budget_id: int) -> ClassifiedSpendingData:
        """
        Fetch classified spending data from pre-computed views.

        Replaces the Python-side classified spending calculation by reading from
        v_law_classified_spending_per_chapter or v_report_classified_spending_per_chapter.

        Args:
            budget_id: The budget ID to fetch classified spending for.

        Returns:
            ClassifiedSpendingData with per-chapter rows (LAW) or aggregate total (REPORT).
        """
        meta_stmt = select(Budget.type, Budget.published_at).where(Budget.id == budget_id)
        with get_sync_session() as session:
            meta = session.execute(meta_stmt).one_or_none()
        if meta is None:
            raise ValueError(f"Budget with ID {budget_id} not found.")
        budget_type, published_at = meta.type, meta.published_at
        year = published_at.year

        if budget_type == "LAW":
            stmt = (
                select(
                    LawClassifiedSpendingPerChapter.original_identifier,
                    LawClassifiedSpendingPerChapter.chapter_name,
                    LawClassifiedSpendingPerChapter.chapter_name_translated,
                    LawClassifiedSpendingPerChapter.classified_spending,
                    func.min(Dimension.id).label("dimension_id"),
                )
                .join(
                    Dimension,
                    and_(
                        Dimension.original_identifier
                        == LawClassifiedSpendingPerChapter.original_identifier,
                        Dimension.type == "CHAPTER",
                    ),
                    isouter=True,
                )
                .where(LawClassifiedSpendingPerChapter.year == year)
                .where(LawClassifiedSpendingPerChapter.classified_spending > 0)
                .group_by(
                    LawClassifiedSpendingPerChapter.original_identifier,
                    LawClassifiedSpendingPerChapter.chapter_name,
                    LawClassifiedSpendingPerChapter.chapter_name_translated,
                    LawClassifiedSpendingPerChapter.classified_spending,
                )
            )
            rows = _execute_query(stmt, unique=False)
            chapters = [
                ClassifiedChapterRow(
                    original_identifier=r["original_identifier"],
                    chapter_name=r["chapter_name"],
                    chapter_name_translated=r["chapter_name_translated"],
                    classified_spending=float(r["classified_spending"]),
                    dimension_id=r["dimension_id"],
                )
                for r in rows
            ]
            return ClassifiedSpendingData(budget_type="LAW", chapters=chapters)

        # REPORT: read the aggregate total classified for this period from the view.
        month = published_at.month
        total_stmt = (
            select(ReportClassifiedSpendingPerChapter.total_budget_classified)
            .where(ReportClassifiedSpendingPerChapter.year == year)
            .where(ReportClassifiedSpendingPerChapter.month == month)
            .limit(1)
        )
        with get_sync_session() as session:
            total = session.execute(total_stmt).scalar_one_or_none()
        return ClassifiedSpendingData(
            budget_type="REPORT",
            total_classified=float(total) if total is not None else 0.0,
        )

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
    ) -> tuple[Sequence[RowMapping], Sequence[RowMapping], ClassifiedSpendingData]:
        """
        Fetch all data needed for treemap visualization.

        Args:
            budget_id: The budget ID to fetch data for.

        Returns:
            Tuple of (dimensions, programs, classified_spending).
        """
        if budget_id is None:
            return [], [], ClassifiedSpendingData(budget_type="LAW")

        # Fetch dimensions and calculate sums
        dimensions = self._fetch_treemap_dimensions(budget_id=budget_id)

        # Fetch program hierarchy - extract program IDs inline to avoid extra iteration.
        program_ids = [r["dimension_id"] for r in dimensions if r["dimension_type"] == "PROGRAM"]
        programs = self._fetch_treemap_programs_recursive(program_ids)

        classified = self.fetch_classified_spending(budget_id=budget_id)

        return dimensions, programs, classified
