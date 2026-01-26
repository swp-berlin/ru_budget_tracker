"""
Data fetching utilities for budget visualization.

This module provides classes for fetching and preparing budget data
for treemap and bar chart visualizations.
"""

from typing import Any, Sequence

from sqlalchemy import RowMapping, Select, and_, extract, func, or_, select
from sqlalchemy.orm import aliased, selectinload

from database import get_sync_session
from models import Budget, Dimension, Expense

# =============================================================================
# Constants
# =============================================================================

# Classified spending dimension IDs
CLASSIFIED_DIMENSION_ID_OFFSET = 1_000_000  # Offset to avoid ID conflicts with real dimensions
CLASSIFIED_PARENT_ID = -999_999  # Synthetic ID for aggregated classified parent node

# Multiplier for TOTAL budget values (stored in thousands)
TOTAL_VALUE_MULTIPLIER = 1000

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

    def fetch_relevant_budgets(self, budget_id: int) -> list[Budget]:
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
            total_budgets = session.execute(total_budgets_stmt).scalars().all()

        # Return initial budget first, then related TOTAL budgets (excluding duplicates)
        return [initial_budget] + [b for b in total_budgets if b.id != initial_budget.id]

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
        relevant_budgets = self.fetch_relevant_budgets(budget_id=budget_id)
        if not relevant_budgets:
            raise ValueError(f"No relevant budgets found for budget ID {budget_id}.")

        budget_ids = [budget.id for budget in relevant_budgets]

        parent_dimension = aliased(Dimension)
        stmt = (
            select(
                Expense.id,
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
            .where(or_(Dimension.type.in_(TREEMAP_DIMENSION_TYPES), Dimension.type.is_(None)))
            .join(Expense.dimensions, isouter=True)
            .join(Expense.budget, isouter=True)
            .join(parent_dimension, Dimension.parent_id == parent_dimension.id, isouter=True)
            .where(Expense.budget_id.in_(budget_ids))
        )

        return _execute_query(stmt)

    def _create_treemap_value_sums_mapping(
        self, budget_id: int, is_total: bool = False, dimension_type: str | None = None
    ) -> dict[int, float]:
        """
        Create a mapping of dimension IDs to their summed expense values.

        Args:
            budget_id: The budget ID to sum expenses for.
            is_total: If True, only include TOTAL budget types; otherwise exclude them.

        Returns:
            Dictionary mapping dimension_id to total expense value.
        """
        stmt = (
            select(
                Dimension.id.label("dimension_id"),
                func.sum(Expense.value).label("total_expense_value"),
            )
            .where(Expense.budget_id == budget_id)
            .outerjoin(Dimension, Expense.dimensions)
            .join(Expense.budget)
            .group_by(Dimension.id)
        )
        if dimension_type:
            stmt = stmt.where(Dimension.type == dimension_type)

        # Filter by budget type
        if is_total:
            stmt = stmt.where(
                Budget.type == "TOTAL",
                or_(
                    and_(
                        Dimension.type.in_(TREEMAP_DIMENSION_TYPES),
                        Budget.original_identifier.like("%LAW-EXPENSE%"),
                    ),
                    and_(
                        Dimension.type.is_(None),
                        Budget.original_identifier.like("%REPORT-EXPENSE%"),
                    ),
                ),
            )
        else:
            stmt = stmt.where(Budget.type != "TOTAL", Dimension.type.in_(TREEMAP_DIMENSION_TYPES))

        sums = _execute_query(stmt, unique=False)
        return {row["dimension_id"]: row["total_expense_value"] for row in sums}

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

    def _create_classified_dimension(
        self, total_dim: RowMapping, law_chapter_id: int
    ) -> dict[str, Any]:
        """
        Create a synthetic classified spending dimension.

        Args:
            total_dim: The TOTAL dimension row to base the classified dimension on.
            law_chapter_id: The LAW budget's chapter ID to use as parent.

        Returns:
            Dictionary representing the classified dimension.
        """
        new_id = (total_dim["dimension_id"] or 0) + CLASSIFIED_DIMENSION_ID_OFFSET
        orig_id = total_dim["dimension_original_identifier"]

        return {
            "id": total_dim["id"],
            "budget_original_identifier": total_dim["budget_original_identifier"],
            "budget_type": "CLASSIFIED",
            "dimension_id": new_id,
            "dimension_original_identifier": orig_id,
            "dimension_parent_id": law_chapter_id,
            "dimension_type": "CLASSIFIED",
            "dimension_name": f"{orig_id} - Classified Spending"
            if orig_id
            else "Classified Spending",
            "dimension_name_translated": f"{orig_id} - Classified Spending"
            if orig_id
            else "Classified Spending",
        }

    def _create_difference_dimensions(
        self,
        dimensions: Sequence[RowMapping],
        sum_mapping: dict[int, float],
    ) -> tuple[Sequence[RowMapping], dict[int, float]]:
        """
        Create dimensions representing classified spending (TOTAL - LAW difference).

        Compares TOTAL budget chapters with LAW budget chapters to calculate
        the classified spending difference for each chapter.

        Args:
            dimensions: Existing dimension row mappings.
            sum_mapping: Mapping of dimension IDs to their summed values.

        Returns:
            Tuple of (updated dimensions, updated sum mapping).
        """
        # Separate TOTAL and non-TOTAL dimensions
        total_dimensions = [d for d in dimensions if d["budget_type"] == "TOTAL"]
        nontotal_dimensions = [d for d in dimensions if d["budget_type"] != "TOTAL"]

        if not total_dimensions:
            return dimensions, sum_mapping

        budget_type = "LAW"
        if nontotal_dimensions[0]["budget_type"] == "REPORT":
            budget_type = "REPORT"

        law_chapters_by_orig_id = None
        nontotal_sum = 0
        if budget_type == "REPORT":
            # Get sum mapping for LAW budget
            nontotal_sum_maping = self._create_treemap_value_sums_mapping(
                budget_id=nontotal_dimensions[0]["budget_id"],
                is_total=False,
                dimension_type="PROGRAM",
            )
            nontotal_sum = sum(nontotal_sum_maping.values())
        else:
            # Build lookup for LAW chapter dimensions by original_identifier
            law_chapters_by_orig_id = {
                d["dimension_original_identifier"]: d
                for d in nontotal_dimensions
                if d["dimension_type"] == "CHAPTER"
            }

        total_sum_mapping = self._create_treemap_value_sums_mapping(
            budget_id=total_dimensions[0]["budget_id"],
            is_total=True,
        )

        # Calculate classified dimensions
        classified_dimensions = []
        for total_dim in total_dimensions:
            orig_id = total_dim["dimension_original_identifier"]
            value = 0
            if budget_type == "LAW" and law_chapters_by_orig_id is not None:
                law_chapter = law_chapters_by_orig_id.get(orig_id)
                if not law_chapter:
                    continue
                value = sum_mapping.get(law_chapter["dimension_id"], 0)
            else:
                value = nontotal_sum
                law_chapter = {"dimension_id": CLASSIFIED_PARENT_ID}

            # Calculate the difference (TOTAL values are stored in thousands)
            multiplier = TOTAL_VALUE_MULTIPLIER if budget_type == "LAW" else 1
            total_value = total_sum_mapping.get(total_dim["dimension_id"], 0) * multiplier
            classified_value = total_value - value

            if classified_value > 0:
                classified_dim = self._create_classified_dimension(
                    total_dim=total_dim,
                    law_chapter_id=law_chapter["dimension_id"],
                )
                classified_dimensions.append(classified_dim)
                sum_mapping[classified_dim["dimension_id"]] = classified_value

        # Return dimensions without TOTAL, plus new classified dimensions
        updated_dimensions = [d for d in dimensions if d not in total_dimensions]
        return updated_dimensions + classified_dimensions, sum_mapping

    def fetch_data(
        self,
        budget_id: int | None = None,
    ) -> tuple[Sequence[RowMapping], Sequence[RowMapping], dict[int, float]]:
        """
        Fetch all data needed for treemap visualization.

        Args:
            budget_id: The budget ID to fetch data for.
            unit: The unit type (currently unused, reserved for future use).

        Returns:
            Tuple of (dimensions, programs, sum_mapping).
        """
        if budget_id is None:
            return [], [], {}

        # Fetch dimensions and calculate sums
        dimensions = self._fetch_treemap_dimensions(budget_id=budget_id)
        sum_mapping = self._create_treemap_value_sums_mapping(budget_id=budget_id)

        # Fetch program hierarchy
        program_ids = [r["dimension_id"] for r in dimensions if r["dimension_type"] == "PROGRAM"]
        programs = self._fetch_treemap_programs_recursive(program_ids)

        # Add classified spending dimensions
        dimensions, sum_mapping = self._create_difference_dimensions(dimensions, sum_mapping)

        return dimensions, programs, sum_mapping


# Backwards compatibility alias (typo in original class name)
TremapDataFetcher = TreemapDataFetcher


# =============================================================================
# Bar Chart Data Fetcher
# =============================================================================


class BarChartDataFetcher:
    """Fetches and prepares data for bar chart (timeseries) visualization."""

    def fetch_budget(self, budget_id: int) -> Budget:
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
            select(*base_columns, func.sum(Expense.value).label("total_value"))
            .select_from(Budget)
            .join(Expense, Budget.id == Expense.budget_id, isouter=True)
            .join(assoc_table, Expense.id == assoc_table.c.expense_id, isouter=True)
            .join(Dimension, assoc_table.c.dimension_id == Dimension.id, isouter=True)
            .where(Budget.type == "LAW")
            .where(Dimension.type == "MINISTRY")
            .group_by(Budget.id, Budget.original_identifier, Budget.type)
        )

        # TOTAL budgets with CHAPTER dimensions (values stored in thousands)
        total_chapter_stmt = (
            select(
                *base_columns,
                (func.sum(Expense.value) * TOTAL_VALUE_MULTIPLIER).label("total_value"),
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
            select(*base_columns, func.sum(Expense.value).label("total_value"))
            .select_from(Budget)
            .join(Expense, Budget.id == Expense.budget_id, isouter=True)
            .join(Expense.dimensions, isouter=True)
            .where(Budget.type.in_(["REPORT", "TOTAL"]))
            .where(
                or_(
                    # REPORT budgets with MINISTRY dimension
                    Dimension.type == "MINISTRY",
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
            return session.execute(stmt).mappings().all()

    def fetch_budgets_by_type(self, budget_id: int) -> tuple[Sequence[RowMapping], str]:
        """
        Fetch budget expenses based on the budget type.

        Args:
            budget_id: The ID of the budget to determine the fetch type.

        Returns:
            Tuple of (budget expense rows, budget category string).

        Raises:
            ValueError: If the budget type is not supported.
        """
        initial_budget = self.fetch_budget(budget_id)

        if initial_budget.type == "REPORT":
            return self._fetch_execution_budget_expenses(), "EXECUTION"
        elif initial_budget.type == "LAW":
            return self._fetch_law_budget_expenses(), "LAW"
        else:
            raise ValueError(f"Unsupported budget type: {initial_budget.type} for ID {budget_id}")

    def fetch_data(
        self,
        budget_id: int | None = None,
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

        return self.fetch_budgets_by_type(budget_id=budget_id)
