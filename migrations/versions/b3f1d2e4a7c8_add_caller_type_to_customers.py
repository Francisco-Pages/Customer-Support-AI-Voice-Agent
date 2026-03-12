"""add caller_type to customers

Revision ID: b3f1d2e4a7c8
Revises: a81c555e193c
Create Date: 2026-03-12

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b3f1d2e4a7c8"
down_revision: Union[str, None] = "a81c555e193c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "customers",
        sa.Column("caller_type", sa.String(20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("customers", "caller_type")
