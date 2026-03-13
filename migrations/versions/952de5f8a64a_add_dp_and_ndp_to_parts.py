"""add dp and ndp to parts

Revision ID: 952de5f8a64a
Revises: 94c3d24ce122
Create Date: 2026-03-13 16:24:47.477014

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '952de5f8a64a'
down_revision: Union[str, None] = '94c3d24ce122'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("parts", sa.Column("dp", sa.Numeric(10, 2), nullable=True))
    op.add_column("parts", sa.Column("ndp", sa.Numeric(10, 2), nullable=True))


def downgrade() -> None:
    op.drop_column("parts", "ndp")
    op.drop_column("parts", "dp")
