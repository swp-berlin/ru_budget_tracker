"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

"""
from alembic import op
import sqlalchemy as sa
from database import get_sync_session  # noqa: F401
${imports if imports else ""}

# revision identifiers, used by Alembic.
revision = ${repr(up_revision)}  # pragma: allowlist secret
down_revision = ${repr(down_revision)}  # pragma: allowlist secret
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
