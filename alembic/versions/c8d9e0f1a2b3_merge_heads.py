"""merge heads

Revision ID: c8d9e0f1a2b3
Revises: 2c8c67f6fb6d, b7c8d9e0f1a2
Create Date: 2026-07-07
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'c8d9e0f1a2b3'
down_revision: Union[str, Sequence[str], None] = ('2c8c67f6fb6d', 'b7c8d9e0f1a2')
branch_labels = None
depends_on = None

def upgrade() -> None:
    pass

def downgrade() -> None:
    pass
