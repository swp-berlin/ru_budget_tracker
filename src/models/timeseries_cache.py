from datetime import date

from sqlalchemy import Date, Float, ForeignKey, Index, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class TimeseriesBudgetSummary(Base):
    __tablename__ = "timeseries_budget_summary"
    __table_args__ = (
        Index("ix_timeseries_budget_summary_lookup", "spending_type", "fetch_category"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    budget_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("budgets.id", ondelete="CASCADE"), nullable=False
    )
    original_identifier: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[date | None] = mapped_column(Date)
    budget_type: Mapped[str | None] = mapped_column(Text)
    fetch_category: Mapped[str | None] = mapped_column(Text)
    spending_type: Mapped[str | None] = mapped_column(Text)
    total_value: Mapped[float | None] = mapped_column(Float)
    military_value: Mapped[float | None] = mapped_column(Float)
