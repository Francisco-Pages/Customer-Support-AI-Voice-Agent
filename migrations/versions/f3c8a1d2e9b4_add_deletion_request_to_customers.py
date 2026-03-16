"""add deletion_requested fields to customers

Revision ID: f3c8a1d2e9b4
Revises: e7a2b9c3d1f5
Create Date: 2026-03-16 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f3c8a1d2e9b4'
down_revision: Union[str, None] = 'e7a2b9c3d1f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("customers", sa.Column("deletion_requested", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("customers", sa.Column("deletion_requested_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("customers", "deletion_requested_at")
    op.drop_column("customers", "deletion_requested")
