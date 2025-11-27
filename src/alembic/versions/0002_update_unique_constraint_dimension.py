"""update unique constraint dimension

Revision ID: 0002
Revises: 0001
Create Date: 2025-11-21 10:20:08.646887

"""

from alembic import op
import sqlalchemy as sa  # noqa: F401
from database import get_sync_session  # noqa: F401


# Revision identifiers, used by Alembic for version tracking
revision = "0002"  # pragma: allowlist secret
down_revision = "0001"  # pragma: allowlist secret
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    Upgrade function to update the unique constraint on dimensions table.
    Uses batch mode for SQLite compatibility to replace the single-column unique index
    with a multi-column unique constraint.
    """
    # Use batch_alter_table for SQLite compatibility
    # This creates a new table with the desired schema and copies data over
    with op.batch_alter_table("dimensions", schema=None) as batch_op:
        # Drop the existing unique index on original_identifier column
        # This index was too restrictive and needs to be replaced
        batch_op.drop_index("ix_dimensions_original_identifier")

        # Create a new composite unique constraint that prevents duplicates
        # based on name, type, original_identifier, and parent_id combination
        # This allows the same original_identifier to exist with different parents/types
        batch_op.create_unique_constraint(
            "uix_dimensions_name_type_original_parent",  # Constraint name for future reference
            ["name", "type", "original_identifier", "parent_id"],  # Columns in the constraint
        )


def downgrade() -> None:
    """
    Downgrade function to revert the unique constraint changes.
    Uses batch mode for SQLite compatibility to restore the original
    single-column unique index configuration.
    """
    # Use batch_alter_table for SQLite compatibility
    # This reverses the changes made in the upgrade function
    with op.batch_alter_table("dimensions", schema=None) as batch_op:
        # Remove the composite unique constraint that was added in upgrade
        # This restores the table to its previous constraint state
        batch_op.drop_constraint("uix_dimensions_name_type_original_parent", type_="unique")

        # Recreate the original unique index on original_identifier column
        # This restores the previous (more restrictive) uniqueness requirement
        batch_op.create_index(
            "ix_dimensions_original_identifier",  # Index name matching the original
            ["original_identifier"],  # Single column index
            unique=True,  # Enforce uniqueness on this column alone
        )
