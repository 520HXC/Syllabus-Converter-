"""Support undated syllabus events.

Revision ID: 0002_support_undated_events
Revises: 0001_initial
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002_support_undated_events"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TYPE reviewstatus ADD VALUE IF NOT EXISTS 'PENDING'")
    with op.batch_alter_table("extracted_events") as batch_op:
        batch_op.alter_column("event_date", existing_type=sa.Date(), nullable=True)


def downgrade() -> None:
    op.execute("DELETE FROM extracted_events WHERE event_date IS NULL")
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "UPDATE extracted_events SET review_status = 'IGNORED' WHERE review_status = 'PENDING'"
        )
    with op.batch_alter_table("extracted_events") as batch_op:
        batch_op.alter_column("event_date", existing_type=sa.Date(), nullable=False)
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TYPE reviewstatus RENAME TO reviewstatus_with_pending")
        op.execute("CREATE TYPE reviewstatus AS ENUM ('NEEDS_REVIEW', 'CONFIRMED', 'IGNORED')")
        op.execute(
            "ALTER TABLE extracted_events ALTER COLUMN review_status TYPE reviewstatus "
            "USING review_status::text::reviewstatus"
        )
        op.execute("DROP TYPE reviewstatus_with_pending")
