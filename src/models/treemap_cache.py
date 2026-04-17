from sqlalchemy import Column, ForeignKey, Index, Integer, Text, Table

from models.base import Base

MAX_PROGRAM_LEVELS = 4

_program_columns = []
for _i in range(MAX_PROGRAM_LEVELS):
    _program_columns += [
        Column(f"PROGRAM_{_i}_DIM_ID", Text),
        Column(f"PROGRAM_{_i}_ORIG_ID", Text),
        Column(f"PROGRAM_{_i}_NAME", Text),
        Column(f"PROGRAM_{_i}_NAME_TRANSLATED", Text),
    ]

treemap_expense_hierarchy = Table(
    "treemap_expense_hierarchy",
    Base.metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("expense_id", Integer, nullable=False),
    Column(
        "budget_id",
        Integer,
        ForeignKey("budgets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    ),
    Column("VALUE", Text),
    Column("BUDGET_TYPE", Text),
    Column("IS_MILITARY", Text),
    Column("MINISTRY_DIM_ID", Text),
    Column("MINISTRY_ORIG_ID", Text),
    Column("MINISTRY_NAME", Text),
    Column("MINISTRY_NAME_TRANSLATED", Text),
    Column("CHAPTER_DIM_ID", Text),
    Column("CHAPTER_ORIG_ID", Text),
    Column("CHAPTER_NAME", Text),
    Column("CHAPTER_NAME_TRANSLATED", Text),
    Column("SUBCHAPTER_DIM_ID", Text),
    Column("SUBCHAPTER_ORIG_ID", Text),
    Column("SUBCHAPTER_NAME", Text),
    Column("SUBCHAPTER_NAME_TRANSLATED", Text),
    *_program_columns,
    Index("ix_treemap_expense_hierarchy_budget_id", "budget_id"),
)
