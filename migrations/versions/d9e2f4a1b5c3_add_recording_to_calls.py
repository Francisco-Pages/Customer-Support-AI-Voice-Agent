"""add recording to calls

Revision ID: d9e2f4a1b5c3
Revises: 575c90a3e2e2
Create Date: 2026-03-13

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d9e2f4a1b5c3"
down_revision: Union[str, None] = "575c90a3e2e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("calls", sa.Column("recording_sid", sa.String(100), nullable=True))
    op.add_column("calls", sa.Column("recording_url", sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column("calls", "recording_url")
    op.drop_column("calls", "recording_sid")
