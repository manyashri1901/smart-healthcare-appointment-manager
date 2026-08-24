"""add unique_active_hold index

Revision ID: 46b39a5f3f9b
Revises: 4992d1a4ec63
Create Date: 2026-08-23 18:23:33.464445

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '46b39a5f3f9b'
down_revision: Union[str, Sequence[str], None] = '4992d1a4ec63'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index(
        "uq_active_hold",
        "slot_holds",
        ["doctor_id", "start"],
        unique=True,
        postgresql_where=sa.text("status = 'HELD'"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("uq_active_hold", table_name="slot_holds")
