from datetime import date

from models.base import Base

from sqlalchemy import Date, Float, Integer, String
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
    # Direct per-chapter TOTAL-EXPENSE value; NULL for years without chapter breakdowns (2022+).
    chapter_total_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Direct classified spending for this chapter: chapter_total_value − open_spending; NULL from 2022+.
    chapter_classified_spending: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Share of total classified attributable to this chapter from direct TOTAL data; NULL when above is NULL.
    chapter_classified_share: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Fallback estimate: total_budget_classified × law_classified_share.
    estimated_classified_spending: Mapped[float | None] = mapped_column(Float, nullable=True)


class MilitaryClassifiedSpendingPerChapter(Base):
    """
    Read-only ORM model backed by v_military_classified_spending_per_chapter.

    Covers both LAW and REPORT budgets, filtered to military chapters (02 and 10).
    Provides open, classified, and estimated classified spending per budget and chapter.

    - classified_spending: always populated for LAW; populated for REPORT 2018–2021 only.
    - estimated_classified_spending: NULL for LAW; LAW-share fallback for REPORT 2022+.

    Do not use with Base.metadata.create_all(); the view is managed by Alembic.
    """

    __tablename__ = "v_military_classified_spending_per_chapter"
    __table_args__ = {"info": {"is_view": True}}

    # Composite primary key: one row per budget × chapter.
    budget_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    original_identifier: Mapped[str] = mapped_column(String, primary_key=True)

    budget_type: Mapped[str] = mapped_column(String)
    published_at: Mapped[date] = mapped_column(Date)
    chapter_name: Mapped[str] = mapped_column(String)
    chapter_name_translated: Mapped[str | None] = mapped_column(String, nullable=True)
    open_spending: Mapped[float] = mapped_column(Float)
    # Direct classified spending; always set for LAW, set for REPORT 2018–2021, else NULL.
    classified_spending: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Fallback estimate used when direct data is unavailable; NULL for LAW rows.
    estimated_classified_spending: Mapped[float | None] = mapped_column(Float, nullable=True)
