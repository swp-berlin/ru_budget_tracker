"""add table: treemap_expense_hierarchy

Revision ID: 0008
Revises: 0007
Create Date: 2026-04-17

"""

import sqlalchemy as sa
from alembic import op

from models.treemap_cache import MAX_PROGRAM_LEVELS

# revision identifiers, used by Alembic.
revision = "0008"  # pragma: allowlist secret
down_revision = "0007"  # pragma: allowlist secret
branch_labels = None
depends_on = None

TABLE_NAME = "treemap_expense_hierarchy"


def _program_columns():
    cols = []
    for i in range(MAX_PROGRAM_LEVELS):
        cols += [
            sa.Column(f"PROGRAM_{i}_DIM_ID", sa.Text),
            sa.Column(f"PROGRAM_{i}_ORIG_ID", sa.Text),
            sa.Column(f"PROGRAM_{i}_NAME", sa.Text),
            sa.Column(f"PROGRAM_{i}_NAME_TRANSLATED", sa.Text),
        ]
    return cols


def upgrade() -> None:
    op.create_table(
        TABLE_NAME,
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("expense_id", sa.Integer, nullable=False),
        sa.Column(
            "budget_id",
            sa.Integer,
            sa.ForeignKey("budgets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("VALUE", sa.Text),
        sa.Column("BUDGET_TYPE", sa.Text),
        sa.Column("IS_MILITARY", sa.Text),
        sa.Column("MINISTRY_DIM_ID", sa.Text),
        sa.Column("MINISTRY_ORIG_ID", sa.Text),
        sa.Column("MINISTRY_NAME", sa.Text),
        sa.Column("MINISTRY_NAME_TRANSLATED", sa.Text),
        sa.Column("CHAPTER_DIM_ID", sa.Text),
        sa.Column("CHAPTER_ORIG_ID", sa.Text),
        sa.Column("CHAPTER_NAME", sa.Text),
        sa.Column("CHAPTER_NAME_TRANSLATED", sa.Text),
        sa.Column("SUBCHAPTER_DIM_ID", sa.Text),
        sa.Column("SUBCHAPTER_ORIG_ID", sa.Text),
        sa.Column("SUBCHAPTER_NAME", sa.Text),
        sa.Column("SUBCHAPTER_NAME_TRANSLATED", sa.Text),
        *_program_columns(),
    )
    op.create_index(
        "ix_treemap_expense_hierarchy_budget_id",
        TABLE_NAME,
        ["budget_id"],
    )


def downgrade() -> None:
    op.drop_table(TABLE_NAME)
