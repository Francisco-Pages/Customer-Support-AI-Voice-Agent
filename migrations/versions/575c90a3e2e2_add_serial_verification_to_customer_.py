"""add serial verification to customer_products

Revision ID: 575c90a3e2e2
Revises: c865b3367a94
Create Date: 2026-02-26

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "575c90a3e2e2"
down_revision: Union[str, None] = "c865b3367a94"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "customer_products",
        sa.Column(
            "serial_verified",
            sa.Boolean,
            nullable=False,
            server_default="false",
        ),
    )
    op.add_column(
        "customer_products",
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("customer_products", "verified_at")
    op.drop_column("customer_products", "serial_verified")
