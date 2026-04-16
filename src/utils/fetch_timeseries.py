"""
Timeseries data fetching utilities for budget visualization.

This module provides the TimeseriesDataFetcher class for fetching and preparing
budget data for timeseries (bar chart) visualization.
"""

from typing import Sequence
from datetime import date
from functools import lru_cache

from sqlalchemy import (
    ColumnElement,
    RowMapping,
    Subquery,
    and_,
    extract,
    func,
    literal,
    or_,
    select,
    case,
)

from database import get_sync_session
from models import (
    Budget,
    Dimension,
    Expense,
    LawMilitaryOpenSpendingPerChapter,
    ReportMilitaryOpenSpendingPerChapter,
    assoc_table,
)
from utils.definitions import (
    SpendingTypeLiteral,
    BudgetTypeLiteral,
    MilitarySpending,
    budget_config,
)
from utils.fetch_treemap import _execute_query


# =============================================================================
# Timeseries Data Fetcher
# =============================================================================


class TimeseriesDataFetcher:
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

    def _build_military_spending_condition(self) -> list[ColumnElement[bool]]:
        """
        Build the SQLAlchemy condition for filtering military spending based on the defined patterns.
        """
        military_conditions: list[ColumnElement[bool]] = []
        for dim, pattern in MilitarySpending.simple_patterns_sql.items():
            military_conditions.append(
                and_(
                    Dimension.type == dim,
                    Dimension.original_identifier.op("REGEXP")(pattern),
                )
            )
        for combination in MilitarySpending.combination_patterns_sql:
            # Each combination requires an expense to have dimensions matching ALL conditions
            # simultaneously (e.g. MINISTRY=180 AND CHAPTER=03 on different dimension rows).
            # A single JOIN row can only hold one Dimension.type, so AND-ing type conditions
            # directly is always False. Instead, intersect per-dimension expense_id subqueries
            # so that only expenses with ALL required dimension rows are matched.
            part_queries = [
                select(assoc_table.c.expense_id)
                .join(Dimension, assoc_table.c.dimension_id == Dimension.id)
                .where(
                    and_(Dimension.type == dim, Dimension.original_identifier.op("REGEXP")(pattern))
                )
                for dim, pattern in combination.items()
            ]
            if part_queries:
                combo_sq = part_queries[0]
                for pq in part_queries[1:]:
                    combo_sq = combo_sq.intersect(pq)
                military_conditions.append(Expense.id.in_(combo_sq))

        return military_conditions

    def _build_expense_subquery(
        self,
        military_conditions: list[ColumnElement[bool]],
        budget_type: BudgetTypeLiteral | None = None,
        dimension_ids: list[int] | None = None,
    ) -> Subquery:
        """
        Build the subquery for expenses with military spending classification.

        This subquery selects distinct expenses associated with the given dimension IDs,
        calculates the absolute value of the expense, and classifies it as military
        based on the defined patterns.
        """
        # Select distinct expenses to avoid double counting across multiple dimensions.
        expenses_subquery = (
            select(
                Expense.id.label("expense_id"),
                Expense.budget_id.label("budget_id"),
                func.abs(Expense.value).label("value"),  # Ensure no negative values in sums.
                # Use MAX so that if ANY dimension of the expense matches military patterns,
                # the expense is classified as military. Without MAX the GROUP BY would pick
                # an arbitrary dimension row, almost always returning 0.
                func.max(
                    case(
                        (
                            or_(
                                *military_conditions,
                            ),
                            func.abs(Expense.value),
                        ),
                        else_=0,
                    )
                ).label("military_value"),
            )
            .select_from(Expense)
            .join(assoc_table, Expense.id == assoc_table.c.expense_id)
            .join(Dimension, assoc_table.c.dimension_id == Dimension.id)
        )
        if dimension_ids:
            expenses_subquery = expenses_subquery.where(Dimension.id.in_(dimension_ids))

        if budget_type == "REPORT":
            expenses_subquery = expenses_subquery.join(
                Budget, and_(Expense.budget_id == Budget.id, Budget.type == "REPORT")
            )
        if budget_type == "LAW":
            expenses_subquery = expenses_subquery.join(
                Budget, and_(Expense.budget_id == Budget.id, Budget.type == "LAW")
            )

        expenses_subquery = expenses_subquery.group_by(Expense.id).subquery()

        return expenses_subquery

    def _fetch_budget_expenses_for_dimensions(
        self,
        budget_types: list[str],
        dimension_ids: list[int],
        quarterly_only: bool,
    ) -> Sequence[RowMapping]:
        """Fetch summed expenses for budgets filtered by dimension ids."""
        from models.budget import expense_dimension_association_table as assoc_table

        base_columns = self._get_budget_expense_columns()

        military_conditions = self._build_military_spending_condition()

        expenses_subquery = self._build_expense_subquery(
            military_conditions, dimension_ids=dimension_ids
        )

        stmt = (
            select(
                *base_columns,
                func.sum(expenses_subquery.c.value).label("total_value"),
                func.sum(expenses_subquery.c.military_value).label("military_value"),
            )
            .select_from(Budget)
            .join(expenses_subquery, Budget.id == expenses_subquery.c.budget_id)
            .where(Budget.type.in_(budget_types))
            .group_by(*base_columns)
        )

        if quarterly_only:
            stmt = stmt.where(
                extract("month", Budget.published_at).in_(budget_config.quarterly_months)
            )

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

        base_columns = self._get_budget_expense_columns()

        military_conditions = self._build_military_spending_condition()

        expenses_subquery = self._build_expense_subquery(military_conditions, budget_type="LAW")

        # LAW budgets with MINISTRY dimensions
        law_ministry_stmt = (
            select(
                *base_columns,
                func.sum(func.abs(expenses_subquery.c.value)).label("total_value"),
                func.sum(func.abs(expenses_subquery.c.military_value)).label("military_value"),
            )
            .select_from(Budget)
            .join(expenses_subquery, Budget.id == expenses_subquery.c.budget_id)
            .join(
                assoc_table,
                expenses_subquery.c.expense_id == assoc_table.c.expense_id,
                isouter=True,
            )
            .join(Dimension, assoc_table.c.dimension_id == Dimension.id, isouter=True)
            .where(Budget.type == "LAW")
            .where(Dimension.type == "MINISTRY")
            .group_by(Budget.id, Budget.original_identifier, Budget.type)
        )

        # TOTAL budgets with CHAPTER dimensions (values stored in thousands)
        total_chapter_stmt = (
            select(
                *base_columns,
                (func.sum(func.abs(Expense.value))).label("total_value"),
                (
                    func.sum(
                        func.abs(
                            case(
                                (
                                    or_(
                                        *military_conditions,
                                    ),
                                    Expense.value,
                                ),
                                else_=0,
                            )
                        )
                    )
                ).label("military_value"),
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
            # Use the pre-computed military view which already aggregates all military
            # patterns (Chapter 02, PROGRAMM 31%, Ministry 187, Chapter 03 + Ministry 180).
            # LAW rows: sum open_spending per budget from the view.
            law_stmt = (
                select(
                    *base_columns,
                    func.sum(LawMilitaryOpenSpendingPerChapter.open_spending).label("total_value"),
                    func.sum(LawMilitaryOpenSpendingPerChapter.open_spending).label(
                        "military_value"
                    ),
                )
                .select_from(Budget)
                .join(
                    LawMilitaryOpenSpendingPerChapter,
                    Budget.id == LawMilitaryOpenSpendingPerChapter.budget_id,
                )
                .where(Budget.type == "LAW")
                .group_by(*base_columns)
            )

            # Aggregate classified_spending by year (only chapters 02+10 have non-NULL values).
            view_year_agg = (
                select(
                    extract("year", Budget.published_at).label("year"),
                    func.sum(LawMilitaryOpenSpendingPerChapter.classified_spending).label(
                        "classified_sum"
                    ),
                )
                .select_from(LawMilitaryOpenSpendingPerChapter)
                .join(Budget, LawMilitaryOpenSpendingPerChapter.budget_id == Budget.id)
                .where(Budget.type == "LAW")
                .group_by(extract("year", Budget.published_at))
                .subquery()
            )

            # TOTAL rows: divide by multiplier so the transformer restores the correct value:
            #   classified = (classified_sum / 1000) × 1000 = classified_sum
            # military_value = 0 so the transformer subtracts nothing.
            total_stmt = (
                select(
                    *base_columns,
                    (
                        view_year_agg.c.classified_sum / budget_config.law_total_value_multiplier
                    ).label("total_value"),
                    literal(0.0).label("military_value"),
                )
                .select_from(Budget)
                .join(view_year_agg, extract("year", Budget.published_at) == view_year_agg.c.year)
                .where(Budget.type == "TOTAL")
                .where(Budget.original_identifier.like("%LAW%"))
            )

            union_stmt = law_stmt.union(total_stmt)
            with get_sync_session() as session:
                return session.execute(union_stmt).mappings().all()

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

        military_conditions = self._build_military_spending_condition()

        if self.spending_type == "MILITARY":
            # Use the pre-computed military view which aggregates all military patterns
            # per (budget_id, chapter). REPORT rows: sum open_spending per budget.
            report_stmt = (
                select(
                    *base_columns,
                    func.sum(ReportMilitaryOpenSpendingPerChapter.open_spending).label(
                        "total_value"
                    ),
                    func.sum(ReportMilitaryOpenSpendingPerChapter.open_spending).label(
                        "military_value"
                    ),
                )
                .select_from(Budget)
                .join(
                    ReportMilitaryOpenSpendingPerChapter,
                    Budget.id == ReportMilitaryOpenSpendingPerChapter.budget_id,
                )
                .where(Budget.type == "REPORT")
                .where(extract("month", Budget.published_at).in_(budget_config.quarterly_months))
                .group_by(*base_columns)
            )

            # Aggregate classified_spending by (year, month) from the REPORT military view
            # (only chapters 02+10 have non-NULL classified_spending values).
            view_period_agg = (
                select(
                    extract("year", Budget.published_at).label("year"),
                    extract("month", Budget.published_at).label("month"),
                    func.sum(ReportMilitaryOpenSpendingPerChapter.classified_spending).label(
                        "classified_sum"
                    ),
                )
                .select_from(ReportMilitaryOpenSpendingPerChapter)
                .join(Budget, ReportMilitaryOpenSpendingPerChapter.budget_id == Budget.id)
                .where(Budget.type == "REPORT")
                .group_by(
                    extract("year", Budget.published_at), extract("month", Budget.published_at)
                )
                .subquery()
            )

            # TOTAL rows: classified spending pre-computed from the view.
            # report_total_value_multiplier = 1, so classified = total_value × 1 − 0.
            # military_value = 0 so the transformer subtracts nothing.
            total_stmt = (
                select(
                    *base_columns,
                    view_period_agg.c.classified_sum.label("total_value"),
                    literal(0.0).label("military_value"),
                )
                .select_from(Budget)
                .join(
                    view_period_agg,
                    and_(
                        extract("year", Budget.published_at) == view_period_agg.c.year,
                        extract("month", Budget.published_at) == view_period_agg.c.month,
                    ),
                )
                .where(Budget.type == "TOTAL")
                .where(Budget.original_identifier.like("%EXPENSE%"))
                .where(extract("month", Budget.published_at).in_(budget_config.quarterly_months))
            )

            union_stmt = report_stmt.union(total_stmt)
            with get_sync_session() as session:
                return session.execute(union_stmt).mappings().all()

        stmt = (
            select(
                *base_columns,
                func.sum(func.abs(Expense.value)).label("total_value"),
                func.sum(
                    func.abs(
                        case(
                            (or_(*military_conditions), Expense.value),
                            else_=0,
                        )
                    )
                ).label("military_value"),
            )
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
            .where(extract("month", Budget.published_at).in_(budget_config.quarterly_months))
            .group_by(Budget.id, Budget.original_identifier, Budget.type)
        )

        with get_sync_session() as session:
            results = session.execute(stmt).mappings().all()

        return results

    def fetch_budgets(self, budget_id: int) -> tuple[Sequence[RowMapping], BudgetTypeLiteral]:
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
        budget_type: BudgetTypeLiteral = initial_budget.type

        result: Sequence[RowMapping] = []
        if budget_type == "REPORT":
            result = self._fetch_execution_budget_expenses()
        elif budget_type == "LAW":
            result = self._fetch_law_budget_expenses()

        if not result:
            raise ValueError(
                f"No expenses found for budget ID {budget_id} with type {budget_type}."
            )
        return result, budget_type

    def _fetch_chapter_original_identifier(self, dimension_id: int) -> str | None:
        """Walk up the dimension hierarchy to find the ancestor CHAPTER's original_identifier.

        Uses a single recursive CTE instead of one query per ancestor level.
        """
        base_stmt = select(
            Dimension.id.label("id"),
            Dimension.parent_id.label("parent_id"),
            Dimension.type.label("type"),
            Dimension.original_identifier.label("original_identifier"),
        ).where(Dimension.id == dimension_id)

        ancestors_cte = base_stmt.cte("ancestors", recursive=True)

        recursive_stmt = select(
            Dimension.id.label("id"),
            Dimension.parent_id.label("parent_id"),
            Dimension.type.label("type"),
            Dimension.original_identifier.label("original_identifier"),
        ).join(ancestors_cte, Dimension.id == ancestors_cte.c.parent_id)

        full_cte = ancestors_cte.union_all(recursive_stmt)
        final_stmt = select(full_cte).where(full_cte.c.type == "CHAPTER").limit(1)

        rows = _execute_query(final_stmt, unique=False)
        return str(rows[0]["original_identifier"]) if rows else None

    def _fetch_total_law_expenses_for_chapter(self, chapter_orig_id: str) -> Sequence[RowMapping]:
        """Fetch TOTAL LAW budget expenses for a specific chapter to enable classified spending calculation."""
        base_columns = self._get_budget_expense_columns()
        stmt = (
            select(
                *base_columns,
                func.sum(func.abs(Expense.value)).label("total_value"),
                literal(0.0).label("military_value"),
            )
            .select_from(Budget)
            .join(Expense, Budget.id == Expense.budget_id, isouter=True)
            .join(assoc_table, Expense.id == assoc_table.c.expense_id, isouter=True)
            .join(Dimension, assoc_table.c.dimension_id == Dimension.id, isouter=True)
            .where(Budget.type == "TOTAL")
            .where(Budget.original_identifier.like("%LAW%"))
            .where(Dimension.type == "CHAPTER")
            .where(Dimension.original_identifier == chapter_orig_id)
            .group_by(*base_columns)
        )
        with get_sync_session() as session:
            return session.execute(stmt).mappings().all()

    def fetch_budgets_filtered(
        self, budget_id: int, dimension_id: int
    ) -> tuple[Sequence[RowMapping], BudgetTypeLiteral]:
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
                "REPORT",
            )
        elif initial_budget.type == "LAW":
            open_data = self._fetch_budget_expenses_for_dimensions(
                ["LAW"],
                dimension_ids,
                quarterly_only=False,
            )
            # Also fetch TOTAL budget data for the ancestor CHAPTER so classified spending
            # can be computed as TOTAL_chapter - open_chapter.
            chapter_orig_id = self._fetch_chapter_original_identifier(dimension_id)
            if chapter_orig_id:
                total_data = self._fetch_total_law_expenses_for_chapter(chapter_orig_id)
                return list(open_data) + list(total_data), "LAW"
            return open_data, "LAW"
        else:
            raise ValueError(f"Unsupported budget type: {initial_budget.type} for ID {budget_id}")

    def fetch_data(
        self,
        budget_id: int | None = None,
        dimension_id: int | None = None,
    ) -> tuple[Sequence[RowMapping], BudgetTypeLiteral]:
        """
        Fetch budget and expense data for bar chart visualization.

        Args:
            budget_id: The budget ID to fetch data for.
            dimension_id: Optional dimension ID to filter by.

        Returns:
            Tuple of (budget expense rows, budget category string).

        Raises:
            ValueError: If budget_id is not provided.
        """
        if budget_id is None:
            raise ValueError("budget_id must be provided to fetch data.")
        # Filter to the selected dimension when provided.
        if dimension_id is not None:
            result = self.fetch_budgets_filtered(budget_id=budget_id, dimension_id=dimension_id)
        else:
            result = self.fetch_budgets(budget_id=budget_id)

        return result
