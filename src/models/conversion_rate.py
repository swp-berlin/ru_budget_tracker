from models.base import Base
from sqlalchemy import (
    String,
    Float,
    Date,
    DateTime,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column
from datetime import date, datetime


class ConversionRate(Base):
    """
    Represents a currency conversion rate entry in the system.
    Naming convention: "{FROM_CURRENCY}_{TO_CURRENCY}"
    Example: "RUB_USD"
    """

    __tablename__ = "conversion_rates"

    name: Mapped[str] = mapped_column(String, primary_key=True)
    # Floating point value representing the conversion rate from first currency to second currency
    value: Mapped[float] = mapped_column(Float, nullable=False)
    # Optional fields to specify the validity period of the conversion rate
    started_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    ended_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Audit fields
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
