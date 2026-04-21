from sqlalchemy import ForeignKey, Index, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base

MAX_PROGRAM_LEVELS = 4


class TreemapExpenseHierarchy(Base):
    __tablename__ = "treemap_expense_hierarchy"
    __table_args__ = (Index("ix_treemap_expense_hierarchy_budget_id", "budget_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    expense_id: Mapped[int] = mapped_column(Integer, nullable=False)
    budget_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("budgets.id", ondelete="CASCADE"), nullable=False
    )
    VALUE: Mapped[str | None] = mapped_column(Text)
    BUDGET_TYPE: Mapped[str | None] = mapped_column(Text)
    IS_MILITARY: Mapped[str | None] = mapped_column(Text)
    MINISTRY_DIM_ID: Mapped[str | None] = mapped_column(Text)
    MINISTRY_ORIG_ID: Mapped[str | None] = mapped_column(Text)
    MINISTRY_NAME: Mapped[str | None] = mapped_column(Text)
    MINISTRY_NAME_TRANSLATED: Mapped[str | None] = mapped_column(Text)
    CHAPTER_DIM_ID: Mapped[str | None] = mapped_column(Text)
    CHAPTER_ORIG_ID: Mapped[str | None] = mapped_column(Text)
    CHAPTER_NAME: Mapped[str | None] = mapped_column(Text)
    CHAPTER_NAME_TRANSLATED: Mapped[str | None] = mapped_column(Text)
    SUBCHAPTER_DIM_ID: Mapped[str | None] = mapped_column(Text)
    SUBCHAPTER_ORIG_ID: Mapped[str | None] = mapped_column(Text)
    SUBCHAPTER_NAME: Mapped[str | None] = mapped_column(Text)
    SUBCHAPTER_NAME_TRANSLATED: Mapped[str | None] = mapped_column(Text)
    PROGRAM_0_DIM_ID: Mapped[str | None] = mapped_column(Text)
    PROGRAM_0_ORIG_ID: Mapped[str | None] = mapped_column(Text)
    PROGRAM_0_NAME: Mapped[str | None] = mapped_column(Text)
    PROGRAM_0_NAME_TRANSLATED: Mapped[str | None] = mapped_column(Text)
    PROGRAM_1_DIM_ID: Mapped[str | None] = mapped_column(Text)
    PROGRAM_1_ORIG_ID: Mapped[str | None] = mapped_column(Text)
    PROGRAM_1_NAME: Mapped[str | None] = mapped_column(Text)
    PROGRAM_1_NAME_TRANSLATED: Mapped[str | None] = mapped_column(Text)
    PROGRAM_2_DIM_ID: Mapped[str | None] = mapped_column(Text)
    PROGRAM_2_ORIG_ID: Mapped[str | None] = mapped_column(Text)
    PROGRAM_2_NAME: Mapped[str | None] = mapped_column(Text)
    PROGRAM_2_NAME_TRANSLATED: Mapped[str | None] = mapped_column(Text)
    PROGRAM_3_DIM_ID: Mapped[str | None] = mapped_column(Text)
    PROGRAM_3_ORIG_ID: Mapped[str | None] = mapped_column(Text)
    PROGRAM_3_NAME: Mapped[str | None] = mapped_column(Text)
    PROGRAM_3_NAME_TRANSLATED: Mapped[str | None] = mapped_column(Text)
