from typing import Literal
from models.base import Base

from sqlalchemy import (
    Column,
    Integer,
    String,
    Table,
    Text,
    Date,
    DateTime,
    Float,
    ForeignKey,
    func,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import date, datetime

BudgetTypeLiteral = Literal["DRAFT", "LAW", "REPORT", "TOTAL"]
BudgetScopeLiteral = Literal["YEARLY", "QUARTERLY", "MONTHLY"]
DimensionTypeLiteral = Literal["MINISTRY", "CHAPTER", "SUBCHAPTER", "PROGRAMM", "EXPENSE_TYPE"]
ViewByDimensionTypeLiteral = Literal["MINISTRY", "CHAPTER", "PROGRAMM"]


class Budget(Base):  # type: ignore[misc]
    """
    Represents a budget entry in the budget system.
    """

    __tablename__ = "budgets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # The original identifier from the data source
    original_identifier: Mapped[str] = mapped_column(String, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    # Translated to english
    name_translated: Mapped[str] = mapped_column(String, nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    # Translated to english
    description_translated: Mapped[str] = mapped_column(Text, nullable=True)
    # Type of the budget entry (e.g., DRAFT, LAW, REPORT, TOTAL)
    type: Mapped[BudgetTypeLiteral] = mapped_column(String, nullable=False)
    # Time period scope of the budget (e.g., YEARLY, QUARTERLY, MONTHLY)
    scope: Mapped[BudgetTypeLiteral] = mapped_column(String, nullable=True)
    # First date of the relevant period the budget relates to
    published_at: Mapped[date] = mapped_column(Date, nullable=False)
    # First date of the relevant period the budget was planned in
    planned_at: Mapped[date | None] = mapped_column(Date, nullable=True)
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
    # Relationship to expenses
    expenses: Mapped[list["Expense"]] = relationship("Expense", lazy="noload")


expense_dimension_association_table = Table(
    "association_table",
    Base.metadata,
    Column("expense_id", ForeignKey("expenses.id")),
    Column("dimension_id", ForeignKey("dimensions.id")),
)


class Expense(Base):  # type: ignore[misc]
    """
    Represents an expense entry in the budget system. Expenses will be in russion rubles.
    """

    __tablename__ = "expenses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Foreign key to the associated budget
    budget_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("budgets.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Float value of the expense
    value: Mapped[float] = mapped_column(Float, nullable=False)
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
    # Relationship to the associated dimension entries
    dimensions: Mapped[list["Dimension"]] = relationship(
        secondary=expense_dimension_association_table,
        back_populates="expenses",
        lazy="noload",
    )
    budget: Mapped["Budget"] = relationship("Budget", lazy="selectin", viewonly=True)

    @property
    def expense_type(self) -> str | None:
        """Get the expense type dimension name if available."""
        for dimension in self.dimensions:
            if dimension.type == "EXPENSE_TYPE":
                return dimension.name
        return None


class Dimension(Base):  # type: ignore[misc]
    """
    Represents a dimension of an expense (e.g., ministry, chapter, expense_type, ...)
    """

    __tablename__ = "dimensions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Optional parent dimension for hierarchical structuring (e.g., programm -> subprogramm)
    parent_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("dimensions.id", ondelete="SET NULL"),
        nullable=True,
    )
    # The original identifier from the data source
    original_identifier: Mapped[str] = mapped_column(String, nullable=False)
    # Type of the dimension (e.g., MINISTRY, CHAPTER, PROGRAMM, EXPENSE_TYPE)
    type: Mapped[DimensionTypeLiteral] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    # Translated to english
    name_translated: Mapped[str] = mapped_column(String, nullable=True)
    # Self-referential relationship to parent dimension
    parent: Mapped["Dimension | None"] = relationship("Dimension", remote_side=[id], lazy="noload")
    # Relationship to expenses
    expenses: Mapped[list["Expense"]] = relationship(
        secondary=expense_dimension_association_table,
        back_populates="dimensions",
        lazy="joined",
    )

    # for a given budget, the combination of budget_id, type and original_identifier should be unique
    __table_args__ = (
        UniqueConstraint(
            "name",
            "type",
            "original_identifier",
            "parent_id",
            name="uix_dimensions_name_type_original_parent",
        ),
    )

    # for a given budget, the combination of budget_id, type and original_identifier should be unique
    __table_args__ = (
        UniqueConstraint(
            "name",
            "type",
            "original_identifier",
            "parent_id",
            name="uix_dimensions_name_type_original_parent",
        ),
    )
