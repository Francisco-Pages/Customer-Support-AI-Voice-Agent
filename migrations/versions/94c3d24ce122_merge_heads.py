"""merge heads

Revision ID: 94c3d24ce122
Revises: b3f1d2e4a7c8, d9e2f4a1b5c3
Create Date: 2026-03-13 15:34:15.038595

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '94c3d24ce122'
down_revision: Union[str, None] = ('b3f1d2e4a7c8', 'd9e2f4a1b5c3')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
