"""replace google calendar oauth with ics

Revision ID: fe47f056ee9d
Revises: 46b39a5f3f9b
Create Date: 2026-08-23 19:26:33.811534

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fe47f056ee9d'
down_revision: Union[str, Sequence[str], None] = '46b39a5f3f9b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Google Calendar OAuth is gone — replaced by locally-generated .ics
    # attachments on the existing confirmation/reschedule/cancellation emails.
    op.drop_table("calendar_connections")
    op.drop_column("appointments", "patient_event_id")
    op.drop_column("appointments", "doctor_event_id")
    op.drop_column("appointments", "calendar_status")
    op.add_column("notifications", sa.Column("attachment_filename", sa.String(), nullable=True))
    op.add_column("notifications", sa.Column("attachment_content", sa.Text(), nullable=True))
    op.add_column("notifications", sa.Column("ics_method", sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("notifications", "ics_method")
    op.drop_column("notifications", "attachment_content")
    op.drop_column("notifications", "attachment_filename")
    op.add_column("appointments", sa.Column("calendar_status", sa.String(), nullable=False, server_default="PENDING"))
    op.add_column("appointments", sa.Column("doctor_event_id", sa.String(), nullable=True))
    op.add_column("appointments", sa.Column("patient_event_id", sa.String(), nullable=True))
    op.create_table(
        "calendar_connections",
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("access_token", sa.Text(), nullable=False),
        sa.Column("refresh_token", sa.Text(), nullable=True),
        sa.Column("token_expiry", sa.String(), nullable=True),
        sa.Column("scope", sa.String(), nullable=True),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("user_id"),
    )
