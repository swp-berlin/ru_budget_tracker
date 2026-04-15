from datetime import date
from functools import lru_cache
from typing import ClassVar, Sequence

from sqlalchemy import RowMapping, and_, extract, func, or_, select
from models import ConversionRate, Budget, Expense, Dimension
from database import get_sync_session
from utils.definitions import (
    UnitLiteral,
    BudgetTypeLiteral,
    BudgetScopeLiteral,
    budget_config,
    unit_config,
)


class Calculator:
    # Class-level caches to persist across instances
    _conversion_rate_cache: ClassVar[dict[tuple[str, date], float]] = {}
    _gdp_cache: ClassVar[dict[tuple[str, date], float]] = {}
    _spending_cache: ClassVar[dict[tuple[str, BudgetTypeLiteral, date], float]] = {}
    _revenue_cache: ClassVar[dict[tuple[BudgetTypeLiteral, date], float]] = {}
    """A collection of methods for various budget calculations."""

    def __init__(
        self, unit: UnitLiteral, budget_id: int, date: date, budget_type: BudgetTypeLiteral
    ) -> None:
        self.unit: UnitLiteral = unit
        self.budget_id: int = budget_id
        self.budget_type: BudgetTypeLiteral = budget_type
        self.date = date

    def _load_conversion_rate(self) -> float:
        """Load conversion rate based on from/to currencies. Cached at class level."""
        conversion_target: str = "ppp"
        # Use year as cache key since rates typically don't change within a year
        cache_key = (conversion_target, self.date)
        if cache_key in Calculator._conversion_rate_cache:
            return Calculator._conversion_rate_cache[cache_key]

        select_stmt = select(ConversionRate).where(
            ConversionRate.name.like(f"{conversion_target.lower()}_%"),
            ConversionRate.started_at <= self.date,
            ConversionRate.ended_at >= self.date,
        )
        with get_sync_session() as session:
            result = session.scalars(select_stmt).one_or_none()

        if not result:
            raise ValueError(f"No conversion rate found for {conversion_target} on {self.date}")

        Calculator._conversion_rate_cache[cache_key] = result.value
        return result.value

    def _fetch_gdp_data(
        self,
        period_start_date: date,
    ) -> float:
        """Fetch GDP data for a given date. Cached at class level."""
        # Cache key includes unit type and year
        cache_key = (self.unit, period_start_date)
        if cache_key in Calculator._gdp_cache:
            return Calculator._gdp_cache[cache_key]

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
                f"No GDP data found for {period_start_date.year} in {unit_config.map[self.unit]}"
            )

        Calculator._gdp_cache[cache_key] = value
        return value

    @lru_cache(maxsize=10)
    def _fetch_spending_budgets(
        self,
        budget_scope: BudgetScopeLiteral,
    ) -> Sequence[RowMapping]:
        """Fetch relevant total budgets for spending calculations."""
        select_stmt = (
            select(Budget.id, Expense.value, Budget.published_at, Budget.scope)
            .select_from(Budget)
            .join(Expense, Expense.budget_id == Budget.id, isouter=True)
            .join(Dimension, Expense.dimensions, isouter=True)
            .where(
                Budget.type == "TOTAL",
                Budget.original_identifier.like("%-EXPENSE-%"),
                Dimension.type.is_(None),  # Exclude expenses with dimensions
            )
        )
        with get_sync_session() as session:
            budgets = session.execute(select_stmt).mappings().all()
        return budgets

    def _fetch_spending_value(
        self,
        period_start_date: date,
    ) -> float:
        """Fetch spending value for a given date. Cached at class level."""
        # Cache key includes unit, budget_type, and year
        cache_key = (self.unit, self.budget_type, period_start_date)
        if cache_key in Calculator._spending_cache:
            return Calculator._spending_cache[cache_key]

        # Use single session for all queries
        scope: BudgetScopeLiteral = "YEARLY" if self.budget_type == "LAW" else "MONTHLY"
        total_budgets = self._fetch_spending_budgets(scope)
        relevant_total_budgets = [
            b
            for b in total_budgets
            if b.published_at.year == period_start_date.year and b.scope == scope
        ]
        # For monthly budgets, we need to consider the latest available month up to the period start date
        if scope == "MONTHLY":
            relevant_total_budgets = [
                b
                for b in relevant_total_budgets
                if b.published_at.month in budget_config.quarterly_months
            ]
        spending_cumulative = 0.0
        previous_spending_value = 0.0
        max_date = max([b.published_at for b in relevant_total_budgets], default=1)
        spending_cumulative = next(
            (b.value for b in relevant_total_budgets if b.published_at == max_date), 0.0
        )
        if self.unit == "PERCENT_FULL_YEAR_SPENDING" and self.budget_type == "REPORT":
            # For REPORT and full-year spending, we want the latest monthly total budget available in the report
            latest_budget = max(relevant_total_budgets, key=lambda b: b.published_at, default=None)
            spending_cumulative = latest_budget.value if latest_budget else 0.0
        if self.unit == "PERCENT_YEAR_TO_DATE_SPENDING" and self.budget_type == "REPORT":
            # For REPORT and year-to-date spending, we want the latest monthly total budget available in the report that matches the month of
            # the period start date
            spending_cumulative = next(
                (b.value for b in relevant_total_budgets if b.published_at == period_start_date),
                0.0,
            )
            if period_start_date.month > 3:
                previous_spending_date = period_start_date.replace(
                    month=period_start_date.month - 3
                )
                previous_spending_value = next(
                    (
                        b.value
                        for b in relevant_total_budgets
                        if b.published_at == previous_spending_date
                    ),
                    0.0,
                )

        if not spending_cumulative:
            raise ValueError(
                f"No spending data found for {period_start_date.year} in {unit_config.map[self.unit]}"
            )

        multiplier: float = budget_config.law_total_value_multiplier
        if self.budget_type == "REPORT":
            multiplier = budget_config.report_total_value_multiplier
        spending_value = spending_cumulative - previous_spending_value
        spending_value *= multiplier
        Calculator._spending_cache[cache_key] = spending_value
        return spending_value

    @lru_cache(maxsize=10)
    def _fetch_revenue_budgets(
        self,
    ) -> Sequence[RowMapping]:
        """Fetch relevant total budgets for spending calculations."""
        select_stmt = (
            select(Budget.id, Expense.value, Budget.published_at)
            .select_from(Budget)
            .join(Expense, Expense.budget_id == Budget.id, isouter=True)
            .join(Dimension, Expense.dimensions, isouter=True)
            .where(
                Budget.type == "TOTAL",
                Budget.original_identifier.like("%-REVENUE-%"),
                Dimension.type.is_(None),  # Exclude expenses with dimensions
                extract("month", Budget.published_at).in_(budget_config.quarterly_months),
            )
        )
        with get_sync_session() as session:
            budgets = session.execute(select_stmt).mappings().all()
        return budgets

    def _fetch_revenue_value(
        self,
        period_start_date: date,
    ) -> float:
        """Fetch revenue value for a given date. Cached at class level."""
        # Cache key includes budget_id and year
        cache_key = (self.budget_type, period_start_date)
        if cache_key in Calculator._revenue_cache:
            return Calculator._revenue_cache[cache_key]

        total_budgets = self._fetch_revenue_budgets()
        relevant_total_budgets = [
            b for b in total_budgets if b.published_at.year == period_start_date.year
        ]
        if not relevant_total_budgets:
            return 0.0  # If no revenue budgets found, return 0 to avoid division errors later
        relevant_date = period_start_date
        if self.budget_type == "LAW":
            relevant_date = max([b.published_at for b in relevant_total_budgets])

        revenue_value = next(
            (b.value for b in relevant_total_budgets if b.published_at == relevant_date), 0.0
        )
        if self.budget_type == "REPORT" and period_start_date.month > 3:
            previous_revenue_date = period_start_date.replace(month=period_start_date.month - 3)
            previous_revenue_value = next(
                (
                    b.value
                    for b in relevant_total_budgets
                    if b.published_at == previous_revenue_date
                ),
                0.0,
            )
            revenue_value -= previous_revenue_value

        Calculator._revenue_cache[cache_key] = revenue_value
        return revenue_value

    @classmethod
    def clear_caches(cls) -> None:
        """Clear all class-level caches. Useful for testing or when data changes."""
        cls._conversion_rate_cache.clear()
        cls._gdp_cache.clear()
        cls._spending_cache.clear()
        cls._revenue_cache.clear()

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
