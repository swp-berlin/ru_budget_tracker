from models.base import Base

from sqlalchemy import Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column


class LawClassifiedSpendingPerChapter(Base):
    """
    Read-only ORM model backed by the v_law_classified_spending_per_chapter view.

    Classified spending per chapter is defined as:
        total_spending (TOTAL-LAW × 1000) − open_spending (LAW per chapter)

    Do not use with Base.metadata.create_all(); the view is managed by Alembic.
    """

    __tablename__ = "v_law_classified_spending_per_chapter"
    __table_args__ = {"info": {"is_view": True}}

    # Composite primary key so SQLAlchemy can track identity (view has no real PK).
    year: Mapped[int] = mapped_column(Integer, primary_key=True)
    original_identifier: Mapped[str] = mapped_column(String, primary_key=True)

    chapter_name: Mapped[str] = mapped_column(String)
    chapter_name_translated: Mapped[str | None] = mapped_column(String, nullable=True)
    open_spending: Mapped[float] = mapped_column(Float)
    total_spending: Mapped[float] = mapped_column(Float)
    classified_spending: Mapped[float] = mapped_column(Float)
    classified_share_of_budget: Mapped[float | None] = mapped_column(Float, nullable=True)


class ReportClassifiedSpendingPerChapter(Base):
    """
    Read-only ORM model backed by the v_report_classified_spending_per_chapter view.

    Classified spending per chapter is estimated as:
        estimated_classified = total_budget_classified × law_classified_share

    Where:
      - total_budget_classified = TOTAL(EXPENSE) for the period − Σ open REPORT across all chapters
      - law_classified_share    = classified_share_of_budget from the LAW view for the same year

    Only quarterly periods (months 3, 6, 9, 12) are included since TOTAL budgets are
    cumulative monthly and only quarter-end values are meaningful.

    Do not use with Base.metadata.create_all(); the view is managed by Alembic.
    """

    __tablename__ = "v_report_classified_spending_per_chapter"
    __table_args__ = {"info": {"is_view": True}}

    # Composite primary key so SQLAlchemy can track identity (view has no real PK).
    year: Mapped[int] = mapped_column(Integer, primary_key=True)
    month: Mapped[int] = mapped_column(Integer, primary_key=True)
    original_identifier: Mapped[str] = mapped_column(String, primary_key=True)

    quarter: Mapped[int] = mapped_column(Integer)
    chapter_name: Mapped[str] = mapped_column(String)
    chapter_name_translated: Mapped[str | None] = mapped_column(String, nullable=True)
    open_spending: Mapped[float] = mapped_column(Float)
    total_budget_classified: Mapped[float] = mapped_column(Float)
    law_classified_share: Mapped[float | None] = mapped_column(Float, nullable=True)
    estimated_classified_spending: Mapped[float | None] = mapped_column(Float, nullable=True)
