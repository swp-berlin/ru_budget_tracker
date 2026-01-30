from datetime import date
from functools import lru_cache

from sqlalchemy import and_, extract, func, or_, select
from models import ConversionRate, Budget, Expense, Dimension
from database import get_sync_session
from utils.definitions import UnitLiteral, unit_map, BudgetScopeLiteral


class Calculator:
    """A collection of methods for various budget calculations."""

    def __init__(self, unit: UnitLiteral, budget_id: int, date: date) -> None:
        self.unit: UnitLiteral = unit
        self.budget_id: int = budget_id
        self.date = date

    def _load_conversion_rate(self) -> float:
        """Load conversion rate based on from/to currencies. Placeholder implementation."""
        conversion_target: str = "ppp"
        select_stmt = select(ConversionRate).where(
            ConversionRate.name.like(f"{conversion_target.lower()}_%"),
            ConversionRate.started_at <= self.date,
            ConversionRate.ended_at >= self.date,
        )
        with get_sync_session() as session:
            result = session.scalars(select_stmt).one_or_none()

        if not result:
            raise ValueError(f"No conversion rate found for {conversion_target} on {self.date}")

        return result.value

    @lru_cache(maxsize=32)
    def _fetch_gdp_data(
        self,
        period_start_date: date,
    ) -> float:
        """Fetch GDP data for a given date."""
        conversion_target: str = "gdp"
        select_stmt = select(func.sum(ConversionRate.value)).where(
            ConversionRate.name.like(f"{conversion_target.lower()}%"),
            extract("year", ConversionRate.ended_at) == period_start_date.year,
        )

        if self.unit == "PERCENT_GDP_FULL_YEAR":
            select_stmt = select_stmt.where(
                or_(
                    ConversionRate.name.not_like("%q_"), ConversionRate.name.like("%20___estimate")
                ),
                extract("month", ConversionRate.ended_at) == 12,
                extract("day", ConversionRate.ended_at) == 31,
                extract("month", ConversionRate.started_at) == 1,
                extract("day", ConversionRate.started_at) == 1,
            )

        if self.unit == "PERCENT_GDP_YEAR_TO_DATE":
            # For year-to-date, match the month and day of the period start date
            # to the quarter-end dates in the conversion rates
            month_to_months_mapping = {
                (1, 2, 3): {1, 3},
                (4, 5, 6): {1, 3, 4, 6},
                (7, 8, 9): {1, 3, 4, 6, 7, 9},
                (10, 11, 12): {1, 3, 4, 6, 7, 9, 10, 12},
            }
            valid_months = set()
            for months, valid in month_to_months_mapping.items():
                if period_start_date.month in months:
                    valid_months = valid
                    break

            select_stmt = select_stmt.where(
                or_(
                    and_(
                        ConversionRate.name.like("%_q_"),
                        extract("month", ConversionRate.ended_at).in_(valid_months),
                        extract("year", ConversionRate.ended_at) == period_start_date.year,
                    ),
                    ConversionRate.name.like("%20___estimate"),
                )
            )

        with get_sync_session() as session:
            value = session.scalar(select_stmt)

        if not value:
            raise ValueError(
                f"No GDP data found for {period_start_date.year} in {unit_map[self.unit]}"
            )

        return value

    @lru_cache(maxsize=32)
    def _fetch_spending_value(
        self,
        period_start_date: date,
    ) -> float:
        """Fetch spending value for a given date."""
        # Fetch target budget
        with get_sync_session() as session:
            budget = session.get(Budget, self.budget_id)

        if not budget:
            raise ValueError(f"No budget found with ID {self.budget_id}")

        # Fetch the relevant total budget
        select_stmt = select(Budget).where(
            Budget.type == "TOTAL",
            Budget.original_identifier.like("%-EXPENSE-%"),
            extract("year", Budget.published_at) == period_start_date.year,
        )
        with get_sync_session() as session:
            relevant_total_budgets = session.scalars(select_stmt).all()

        base_spending_stmt = (
            select(func.sum(Expense.value))
            .outerjoin(Dimension, Expense.dimensions)
            .where(Dimension.type.is_(None))
        )

        relevant_month = 1
        relevant_scope: BudgetScopeLiteral = "YEARLY"
        if self.unit == "PERCENT_FULL_YEAR_SPENDING":
            # Filter by relevant total budgets for full-year spending
            if budget.type == "REPORT":
                relevant_scope = "MONTHLY"
                month = max(
                    [
                        b.published_at.month
                        for b in relevant_total_budgets
                        if b.scope == relevant_scope
                    ]
                )
                relevant_month = month

        if self.unit == "PERCENT_YEAR_TO_DATE_SPENDING":
            # Filter by relevant total budgets for full-year spending
            if budget.type == "REPORT":
                relevant_month = budget.published_at.month
                relevant_scope = "MONTHLY"

        relevant_total_budget_id = next(
            (
                b.id
                for b in relevant_total_budgets
                if (b.published_at.month == relevant_month and b.scope == relevant_scope)
            )
        )
        spending_stmt = base_spending_stmt.where(Expense.budget_id == relevant_total_budget_id)

        with get_sync_session() as session:
            spending_value = session.scalar(spending_stmt)
        if not spending_value:
            raise ValueError(
                f"No spending data found for {period_start_date.year} in {unit_map[self.unit]}"
            )
        return spending_value

    @lru_cache(maxsize=32)
    def _fetch_revenue_value(
        self,
        period_start_date: date,
    ) -> float:
        """Fetch revenue value for a given date."""
        # Fetch target budget
        with get_sync_session() as session:
            budget = session.get(Budget, self.budget_id)

        if not budget:
            raise ValueError(f"No budget found with ID {self.budget_id}")

        # Fetch the relevant total budget
        select_stmt = select(Budget).where(
            Budget.type == "TOTAL",
            Budget.original_identifier.like("%-REVENUE-%"),
            extract("year", Budget.published_at) == period_start_date.year,
        )
        with get_sync_session() as session:
            relevant_total_budgets = session.scalars(select_stmt).all()

        base_renevue_stmt = (
            select(func.sum(Expense.value))
            .outerjoin(Dimension, Expense.dimensions)
            .where(Dimension.type.is_(None))
        )

        relevant_month = period_start_date.month
        if budget.type == "LAW":
            month = max([b.published_at.month for b in relevant_total_budgets])
            relevant_month = month

        relevant_total_budget_id = next(
            (b.id for b in relevant_total_budgets if (b.published_at.month == relevant_month))
        )

        revenue_stmt = base_renevue_stmt.where(Expense.budget_id == relevant_total_budget_id)

        with get_sync_session() as session:
            revenue_value = session.scalar(revenue_stmt)
        if not revenue_value:
            raise ValueError(
                f"No revenue data found for {period_start_date.year} in {unit_map[self.unit]}"
            )
        return revenue_value

    def _absolute(self, value: float) -> float:
        """Calculate absolute value in billions."""
        value_in_billions = value / 1_000_000_000
        return value_in_billions

    def _ppp_dollars(self, value: float, date: date) -> float:
        """Calculate value in PPP dollars."""
        rate = self._load_conversion_rate()
        value_in_billions = (value / rate) / 1_000_000_000
        return value_in_billions

    def _percentage_gdp(self, value: float, date: date) -> float:
        """Calculate percentage of GDP."""
        gdp = self._fetch_gdp_data(date)
        if gdp == 0:
            raise ValueError("GDP value is zero, cannot calculate percentage.")
        value = (value / gdp) * 100
        return value

    def _percentage_spending(self, value: float, date: date) -> float:
        """Calculate percentage of spending."""
        spending_value = self._fetch_spending_value(date)
        if spending_value == 0:
            raise ValueError("Spending value is zero, cannot calculate percentage.")
        value = (value / spending_value) * 100
        return value

    def _percentage_revenue(self, value: float, date: date) -> float:
        """Calculate percentage of year-to-date revenue."""
        revenue_value = self._fetch_revenue_value(date)
        if revenue_value == 0:
            raise ValueError("Revenue value is zero, cannot calculate percentage.")
        value = (value / revenue_value) * 100
        return value

    def calculate(self, value: float) -> float:
        """Calculate based on spending scope."""
        date = self.date
        if self.unit == "ABSOLUTE":
            return self._absolute(value)
        if self.unit == "DOLLARS":
            return self._ppp_dollars(value, date)
        if self.unit in ["PERCENT_GDP_FULL_YEAR", "PERCENT_GDP_YEAR_TO_DATE"]:
            return self._percentage_gdp(value, date)
        if self.unit in [
            "PERCENT_FULL_YEAR_SPENDING",
            "PERCENT_YEAR_TO_DATE_SPENDING",
        ]:
            return self._percentage_spending(value, date)
        if self.unit == "PERCENT_YEAR_TO_DATE_REVENUE":
            return self._percentage_revenue(value, date)
        raise ValueError(f"Unknown spending scope: {self.unit}")
