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
    delete,
    extract,
    func,
    insert,
    select,
    union,
)
from pydantic import BaseModel
from database import get_sync_session
from models import (
    Budget,
    Dimension,
    Expense,
    LawClassifiedSpendingPerChapter,
    MAX_PROGRAM_LEVELS,
    ReportClassifiedSpendingPerChapter,
    ReportMilitaryOpenSpendingPerChapter,
    TreemapExpenseHierarchy,
    assoc_table,
)

# =============================================================================
# Constants
# =============================================================================

# Valid dimension types for treemap hierarchy
TREEMAP_DIMENSION_TYPES = ["MINISTRY", "CHAPTER", "SUBCHAPTER", "PROGRAM"]


def _build_military_expense_ids_cte():
    """Return a CTE of expense_ids classified as military, matching the view logic.

    Covers:
      - CHAPTER = '02'  (National Defense)
      - PROGRAM LIKE '31%'  (federal programs starting with 31)
      - MINISTRY = '187'  (Rosgvardia)
      - CHAPTER = '03' AND MINISTRY = '180'  (FSB combination)
    """

    def _expense_ids_for_dim(dim_type: str, orig_id_condition):
        return (
            select(assoc_table.c.expense_id)
            .join(Dimension, assoc_table.c.dimension_id == Dimension.id)
            .where(Dimension.type == dim_type)
            .where(orig_id_condition)
        )

    chapter_02_sq = _expense_ids_for_dim("CHAPTER", Dimension.original_identifier == "02")
    program_31_sq = _expense_ids_for_dim("PROGRAM", Dimension.original_identifier.like("31%"))
    ministry_187_sq = _expense_ids_for_dim("MINISTRY", Dimension.original_identifier == "187")
    ministry_180_sq = _expense_ids_for_dim("MINISTRY", Dimension.original_identifier == "180")
    combo_sq = (
        select(assoc_table.c.expense_id)
        .join(Dimension, assoc_table.c.dimension_id == Dimension.id)
        .where(Dimension.type == "CHAPTER")
        .where(Dimension.original_identifier == "03")
        .where(assoc_table.c.expense_id.in_(ministry_180_sq))
    )

    return union(chapter_02_sq, program_31_sq, ministry_187_sq, combo_sq).cte(
        "military_expense_ids"
    )


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
    For REPORT budgets: total_classified is set; military_classified and
    military_classified_share are set for military-mode rendering.
    """

    budget_type: str  # "LAW" or "REPORT"
    chapters: list[ClassifiedChapterRow] = []
    total_classified: float = 0.0
    # REPORT military mode: sum of estimated classified for military chapters (02, 10).
    military_classified: float = 0.0
    # Fraction of total classified attributable to military chapters (from LAW budget shares).
    military_classified_share: float = 0.0


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

    def get_budget_meta(self, budget_id: int) -> tuple[str, date]:
        """Return (budget_type, published_at) for the given budget ID."""
        stmt = select(Budget.type, Budget.published_at).where(Budget.id == budget_id)
        with get_sync_session() as session:
            row = session.execute(stmt).one_or_none()
        if row is None:
            raise ValueError(f"Budget with ID {budget_id} not found.")
        return row.type, row.published_at

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
            Sequence of dimension row mappings with budget and dimension info,
            including an is_military flag computed in SQL.
        """
        military_cte = _build_military_expense_ids_cte()
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
                case(
                    (military_cte.c.expense_id.is_not(None), True),
                    else_=False,
                ).label("is_military"),
            )
            .join(Expense.dimensions, isouter=True)
            .join(Expense.budget, isouter=True)
            .outerjoin(military_cte, Expense.id == military_cte.c.expense_id)
            .where(Budget.id == budget_id)
            .where(Dimension.type.in_(TREEMAP_DIMENSION_TYPES))
        )

        return _execute_query(stmt, unique=False)

    def fetch_classified_spending(
        self,
        budget_id: int,
        budget_type: str | None = None,
        published_at: date | None = None,
    ) -> ClassifiedSpendingData:
        """
        Fetch classified spending data from pre-computed views.

        Replaces the Python-side classified spending calculation by reading from
        v_law_classified_spending_per_chapter or v_report_classified_spending_per_chapter.

        Args:
            budget_id: The budget ID to fetch classified spending for.
            budget_type: Pre-fetched budget type ("LAW" or "REPORT"); avoids a DB round-trip.
            published_at: Pre-fetched published_at date; avoids a DB round-trip.

        Returns:
            ClassifiedSpendingData with per-chapter rows (LAW) or aggregate total (REPORT).
        """
        if budget_type is None or published_at is None:
            budget_type, published_at = self.get_budget_meta(budget_id)
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

        # Military mode: sum estimated classified and share across military chapters.
        military_stmt = select(
            func.sum(ReportMilitaryOpenSpendingPerChapter.classified_spending).label(
                "military_classified"
            ),
            func.sum(ReportMilitaryOpenSpendingPerChapter.classified_share_of_budget).label(
                "military_share"
            ),
        ).where(ReportMilitaryOpenSpendingPerChapter.budget_id == budget_id)
        with get_sync_session() as session:
            mil = session.execute(military_stmt).one_or_none()

        return ClassifiedSpendingData(
            budget_type="REPORT",
            total_classified=float(total) if total is not None else 0.0,
            military_classified=float(mil[0]) if mil and mil[0] is not None else 0.0,
            military_classified_share=float(mil[1]) if mil and mil[1] is not None else 0.0,
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
        budget_type: str | None = None,
        published_at: date | None = None,
    ) -> tuple[Sequence[RowMapping], Sequence[RowMapping], ClassifiedSpendingData]:
        """
        Fetch all data needed for treemap visualization.

        Args:
            budget_id: The budget ID to fetch data for.
            budget_type: Pre-fetched budget type to avoid a redundant DB query.
            published_at: Pre-fetched published_at date to avoid a redundant DB query.

        Returns:
            Tuple of (dimensions, programs, classified_spending).
        """
        if budget_id is None:
            return [], [], ClassifiedSpendingData(budget_type="LAW")

        dimensions = self._fetch_treemap_dimensions(budget_id=budget_id)

        program_ids = [r["dimension_id"] for r in dimensions if r["dimension_type"] == "PROGRAM"]
        programs = self._fetch_treemap_programs_recursive(program_ids)

        classified = self.fetch_classified_spending(
            budget_id=budget_id, budget_type=budget_type, published_at=published_at
        )

        return dimensions, programs, classified


def fetch_treemap_hierarchy(budget_id: int) -> Sequence[RowMapping]:
    """Read pre-computed flat hierarchy rows for this budget from the DB table."""
    from sqlalchemy.exc import OperationalError

    stmt = select(TreemapExpenseHierarchy.__table__).where(
        TreemapExpenseHierarchy.budget_id == budget_id
    )
    try:
        return _execute_query(stmt, unique=False)
    except OperationalError:
        return []


def populate_treemap_hierarchy(budget_id: int) -> None:
    """Compute flat hierarchy for budget_id and persist to treemap_expense_hierarchy."""
    from utils.transform_treemap import TreemapTransformer

    fetcher = TreemapDataFetcher()
    budget_type, published_at = fetcher.get_budget_meta(budget_id)
    dimensions, programs, classified = fetcher.fetch_data(
        budget_id=budget_id,
        budget_type=budget_type,
        published_at=published_at,
    )

    transformer = TreemapTransformer(dimensions, programs, classified, spending_type="ALL")
    df = transformer.transform_data()

    # Exclude classified rows — they are dynamic and generated at render time.
    df = df[df["BUDGET_TYPE"] != "CLASSIFIED"].copy()

    df["expense_id"] = df.index
    df["budget_id"] = budget_id
    df = df.drop(columns=["ROOT"], errors="ignore")

    # Ensure all PROGRAM_* columns exist even if this budget has fewer program levels.
    for i in range(MAX_PROGRAM_LEVELS):
        for suffix in ("DIM_ID", "ORIG_ID", "NAME", "NAME_TRANSLATED"):
            col = f"PROGRAM_{i}_{suffix}"
            if col not in df.columns:
                df[col] = None

    rows = df.where(df.notna(), other=None).to_dict("records")

    from sqlalchemy.exc import OperationalError

    try:
        with get_sync_session() as session:
            session.execute(
                delete(TreemapExpenseHierarchy).where(
                    TreemapExpenseHierarchy.budget_id == budget_id
                )
            )
            if rows:
                session.execute(insert(TreemapExpenseHierarchy), rows)
    except OperationalError:
        pass
