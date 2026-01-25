from typing import Any, Sequence
from database import get_sync_session
from models import Budget, Dimension, Expense
from sqlalchemy import RowMapping, func, select


def fetch_budgets() -> list[dict[str, Any]]:
    """Load all budgets from the database."""
    with get_sync_session() as session:
        budgets = (
            session.execute(
                select(
                    Budget.id,
                    Budget.original_identifier,
                    Budget.type,
                )
                .where(
                    Budget.type.not_like("TOTAL%"),
                )
                .order_by(Budget.published_at.desc(), Budget.original_identifier.desc())
            )
            .unique()
            .mappings()
            .all()
        )
    return [dict(budget) for budget in budgets]


class TremapDataFetcher:
    def _fetch_treemap_dimensions(
        self,
        budget_id: int | None = None,
    ) -> Sequence[RowMapping]:
        """
        Load data from the database based on provided filters.
        Loads budgets, expenses, and dimensions, applies filters, and returns the result set.
        Query is built dynamically and uses a recursive CTE to fetch the full dimension hierarchy.
        Args:
            **kwargs: Filter parameters such as budget_dataset, viewby, spending_type, unit.
        Returns:
            pd.DataFrame: The loaded and transformed data.
        """
        select_stmt = (
            select(
                Expense.id,
                Dimension.id.label("dimension_id"),
                Dimension.original_identifier.label("dimension_original_identifier"),
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

    # This is a recursive CTE to fetch all programs in the hierarchy for given leave program IDs

    def _fetch_treemap_programs_recursive(
        self, leave_program_ids: list[int]
    ) -> Sequence[RowMapping]:
        # Build the base select statement for the CTE
        basic_select_stmt = select(
            Dimension.id.label("dimension_id"),
            Dimension.parent_id.label("dimension_parent_id"),
            Dimension.original_identifier.label("dimension_original_identifier"),
            func.CONCAT(Dimension.original_identifier, " - ", Dimension.name).label(
                "dimension_name"
            ),
        )
        child_programs_cte = (basic_select_stmt.where(Dimension.id.in_(leave_program_ids))).cte(
            "program_hierarchy", recursive=True
        )

        # Recursive part to get parent dimensions
        parent_select_stmt = (
            basic_select_stmt.select_from(Dimension)
            .join(child_programs_cte, Dimension.id == child_programs_cte.c.dimension_parent_id)
            .where(Dimension.type == "PROGRAM")
        )
        # Union the base and recursive parts to get all programs belonging to the relevant expenses
        union = child_programs_cte.union_all(parent_select_stmt)
        select_stmt = select(
            union.c.dimension_id,
            union.c.dimension_parent_id,
            union.c.dimension_original_identifier,
            union.c.dimension_name,
        )

        with get_sync_session() as session:
            programs = session.execute(select_stmt).unique().mappings().all()

        return programs

    def fetch_data(
        self,
        budget_id: int | None = None,
        unit: str = "ABSOLUTE",
    ) -> tuple[Sequence[RowMapping], Sequence[RowMapping], dict[int, float]]:
        """
        Load data from the database based on provided filters.
        Loads budgets, expenses, and dimensions, applies filters, and returns the result set.
        Query is built dynamically and uses a recursive CTE to fetch the full dimension hierarchy.
        Args:
            **kwargs: Filter parameters such as budget_dataset, viewby, spending_type, unit.
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


class BarChartDataFetcher:
    def fetch_budget(
        self,
        budget_id: int,
    ) -> Budget:
        """
        Load a single budget from the database based on its ID.
        Args:
            budget_id (int): The ID of the budget to fetch.
        Returns:
            Sequence[RowMapping]: The loaded budget data.
        """
        select_stmt = select(Budget).where(Budget.id == budget_id)
        with get_sync_session() as session:
            budget: Budget | None = session.scalars(select_stmt).one_or_none()

        if budget is None:
            raise ValueError(f"Budget with ID {budget_id} not found.")

        return budget

    def fetch_budgets_by_type(
        self,
        budget_id: int,
    ) -> tuple[Sequence[RowMapping], str]:
        """
        Fetch budgets of type REPORT and TOTAL-REPORT-EXPENSE corresponding to a LAW budget.
        """

        def _fetch_law_budget_expenses() -> Sequence[RowMapping]:
            """
            Fetch budgets of type LAW and their corresponding TOTAL budgets.
            Returns a union of:
            - LAW budgets with MINISTRY dimension expenses (summed)
            - LAW+TOTAL budgets with CHAPTER dimension expenses (summed * 1000)
            """
            # Import the association table for explicit joins
            from models.budget import expense_dimension_association_table as assoc_table

            # First query: LAW budgets with MINISTRY dimension type
            ministry_query = (
                select(
                    Budget.id,
                    Budget.original_identifier,
                    Budget.published_at,
                    Budget.type,
                    func.sum(Expense.value).label("total_value"),
                )
                .select_from(Budget)
                .join(Expense, Budget.id == Expense.budget_id, isouter=True)
                .join(assoc_table, Expense.id == assoc_table.c.expense_id, isouter=True)
                .join(Dimension, assoc_table.c.dimension_id == Dimension.id, isouter=True)
                .where(Budget.type == "LAW")
                .where(Dimension.type == "MINISTRY")
                .group_by(Budget.id, Budget.original_identifier, Budget.type)
            )

            # Second query: LAW+TOTAL budgets with CHAPTER dimension type (value * 1000)
            chapter_total_query = (
                select(
                    Budget.id,
                    Budget.original_identifier,
                    Budget.published_at,
                    Budget.type,
                    (func.sum(Expense.value) * 1000).label("total_value"),
                )
                .select_from(Budget)
                .join(Expense, Budget.id == Expense.budget_id, isouter=True)
                .join(assoc_table, Expense.id == assoc_table.c.expense_id, isouter=True)
                .join(Dimension, assoc_table.c.dimension_id == Dimension.id, isouter=True)
                .where(Dimension.type == "CHAPTER")
                .where(Budget.type == "TOTAL")
                .where(Budget.original_identifier.like("%LAW%"))
                .group_by(Budget.id, Budget.original_identifier, Budget.type)
            )

            # Union both queries
            union_query = ministry_query.union(chapter_total_query)

            with get_sync_session() as session:
                results = session.execute(union_query).mappings().all()

            return results

        def _fetch_execution_budget_expenses() -> Sequence[RowMapping]:
            """
            Fetch budgets of type REPORT and their corresponding TOTAL budgets.
            Returns REPORT budgets where:
            - dimension.type = 'MINISTRY', OR
            - dimension.type is NULL and budget.type = 'TOTAL'
            """
            # Import the association table for explicit joins
            from models.budget import expense_dimension_association_table as assoc_table
            from sqlalchemy import or_, and_, extract

            # Query: REPORT budgets with MINISTRY dimension OR TOTAL budgets with NULL dimension
            report_query = (
                select(
                    Budget.id,
                    Budget.original_identifier,
                    Budget.published_at,
                    Budget.type,
                    func.sum(Expense.value).label("total_value"),
                )
                .select_from(Budget)
                .join(Expense, Budget.id == Expense.budget_id, isouter=True)
                .join(assoc_table, Expense.id == assoc_table.c.expense_id, isouter=True)
                .join(Dimension, assoc_table.c.dimension_id == Dimension.id, isouter=True)
                .where(Budget.type.in_(["REPORT", "TOTAL"]))
                .where(
                    or_(
                        Dimension.type == "MINISTRY",
                        and_(
                            Dimension.type.is_(None),
                            Budget.type == "TOTAL",
                            Budget.original_identifier.like("%EXPENSE%"),
                        ),
                    )
                )
                # Filter to only include budgets published in months 3, 6, 9, or 12 (quarterly)
                .where(extract("month", Budget.published_at).in_([3, 6, 9, 12]))
                .group_by(Budget.id, Budget.original_identifier, Budget.type)
            )

            with get_sync_session() as session:
                results = session.execute(report_query).mappings().all()

            return results

        initial_budget = self.fetch_budget(budget_id)
        if initial_budget.type == "REPORT":
            return _fetch_execution_budget_expenses(), "EXECUTION"
        elif initial_budget.type == "LAW":
            return _fetch_law_budget_expenses(), "LAW"
        else:
            raise ValueError(f"Unsupported budget type: {initial_budget.type} for ID {budget_id}")

    def fetch_data(
        self,
        budget_id: int | None = None,
        unit: str = "ABSOLUTE",
    ) -> tuple[Sequence[RowMapping], str]:
        """
        Load budget and expense data from the database and return as a DataFrame.
        Takes an optional original_identifier to filter budgets.
        """
        if budget_id is None:
            raise ValueError("budget_id must be provided to fetch data.")

        budgets, type = self.fetch_budgets_by_type(budget_id=budget_id)

        return budgets, type
