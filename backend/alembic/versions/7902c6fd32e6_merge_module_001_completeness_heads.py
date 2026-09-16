"""merge module 001 completeness heads

Revision ID: 7902c6fd32e6
Revises: 0004_module_001_completeness, 714f4f4f81a0
Create Date: 2026-09-16 17:16:31.361941

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7902c6fd32e6'
down_revision: Union[str, None] = ('0004_module_001_completeness', '714f4f4f81a0')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
