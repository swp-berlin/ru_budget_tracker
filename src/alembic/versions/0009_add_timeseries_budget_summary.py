"""add table: timeseries_budget_summary

Revision ID: 0009
Revises: 0008
Create Date: 2026-04-21

"""

import sqlalchemy as sa
from alembic import op

from models.timeseries_cache import TimeseriesBudgetSummary

# revision identifiers, used by Alembic.
revision = "0009"  # pragma: allowlist secret
down_revision = "0008"  # pragma: allowlist secret
branch_labels = None
depends_on = None

TABLE_NAME = TimeseriesBudgetSummary.__tablename__


def upgrade() -> None:
    op.create_table(
        TABLE_NAME,
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "budget_id",
            sa.Integer,
            sa.ForeignKey("budgets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("original_identifier", sa.Text),
        sa.Column("published_at", sa.Date),
        sa.Column("budget_type", sa.Text),
        sa.Column("fetch_category", sa.Text),
        sa.Column("spending_type", sa.Text),
        sa.Column("total_value", sa.Float),
        sa.Column("military_value", sa.Float),
    )
    op.create_index(
        "ix_timeseries_budget_summary_lookup",
        TABLE_NAME,
        ["spending_type", "fetch_category"],
    )


def downgrade() -> None:
    op.drop_table(TABLE_NAME)
