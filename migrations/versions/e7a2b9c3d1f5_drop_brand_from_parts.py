"""drop brand from parts

Revision ID: e7a2b9c3d1f5
Revises: 952de5f8a64a
Create Date: 2026-03-16 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e7a2b9c3d1f5'
down_revision: Union[str, None] = '952de5f8a64a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("parts", "brand")


def downgrade() -> None:
    op.add_column("parts", sa.Column("brand", sa.String(100), nullable=False, server_default=""))
    op.alter_column("parts", "brand", server_default=None)
