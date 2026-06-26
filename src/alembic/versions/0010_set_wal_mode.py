"""set WAL journal mode

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-26

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0010"  # pragma: allowlist secret
down_revision = "0009"  # pragma: allowlist secret
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text("PRAGMA journal_mode=WAL"))


def downgrade() -> None:
    op.execute(sa.text("PRAGMA journal_mode=DELETE"))
