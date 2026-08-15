"""Add recurring series and model audit fields.

Revision ID: 0003_recurring_model_audit
Revises: 0002_support_undated_events
Create Date: 2026-08-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0003_recurring_model_audit"
down_revision: str | None = "0002_support_undated_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"
    confidence_type = (
        postgresql.ENUM(
            "HIGH",
            "MEDIUM",
            "LOW",
            name="confidencelevel",
            create_type=False,
        )
        if is_postgres
        else sa.Enum("HIGH", "MEDIUM", "LOW", name="confidencelevel")
    )

    with op.batch_alter_table("processing_jobs") as batch_op:
        batch_op.add_column(sa.Column("primary_model", sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column("fallback_model", sa.String(length=80), nullable=True))
        batch_op.add_column(
            sa.Column("fallback_used", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch_op.add_column(
            sa.Column("fallback_reason_codes", sa.JSON(), nullable=False, server_default="[]")
        )

    op.create_table(
        "recurring_event_series",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("semester_id", sa.Uuid(), nullable=False),
        sa.Column("course_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("rule_kind", sa.String(length=40), nullable=False),
        sa.Column("rule_summary", sa.Text(), nullable=False),
        sa.Column("source_quote", sa.Text(), nullable=False),
        sa.Column("source_page", sa.Integer(), nullable=False),
        sa.Column("anchor_sources", sa.JSON(), nullable=False),
        sa.Column("rule_payload", sa.JSON(), nullable=False),
        sa.Column("confidence", confidence_type, nullable=False),
        sa.Column("warning_codes", sa.JSON(), nullable=False),
        sa.Column("warning_reason", sa.Text(), nullable=True),
        sa.Column("extraction_model", sa.String(length=80), nullable=True),
        sa.Column("fallback_reason_codes", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["syllabus_documents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["semester_id"], ["semesters.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_recurring_event_series_user_id", "recurring_event_series", ["user_id"]
    )
    op.create_index(
        "ix_recurring_event_series_semester_id", "recurring_event_series", ["semester_id"]
    )
    op.create_index(
        "ix_recurring_event_series_course_id", "recurring_event_series", ["course_id"]
    )
    op.create_index(
        "ix_recurring_event_series_document_id", "recurring_event_series", ["document_id"]
    )

    with op.batch_alter_table("extracted_events") as batch_op:
        batch_op.add_column(sa.Column("recurring_series_id", sa.Uuid(), nullable=True))
        batch_op.add_column(sa.Column("extraction_model", sa.String(length=80), nullable=True))
        batch_op.add_column(
            sa.Column("fallback_reason_codes", sa.JSON(), nullable=False, server_default="[]")
        )
        batch_op.add_column(sa.Column("derivation_summary", sa.Text(), nullable=True))
        batch_op.create_index(
            "ix_extracted_events_recurring_series_id", ["recurring_series_id"], unique=False
        )
        batch_op.create_foreign_key(
            "fk_extracted_events_recurring_series_id",
            "recurring_event_series",
            ["recurring_series_id"],
            ["id"],
            ondelete="SET NULL",
        )

    if is_postgres:
        op.execute("ALTER TABLE recurring_event_series ENABLE ROW LEVEL SECURITY")
        op.execute(
            "CREATE POLICY recurring_event_series_owner "
            "ON recurring_event_series FOR ALL TO authenticated "
            "USING ((select auth.uid()) = user_id) "
            "WITH CHECK ((select auth.uid()) = user_id)"
        )


def downgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    with op.batch_alter_table("extracted_events") as batch_op:
        batch_op.drop_constraint("fk_extracted_events_recurring_series_id", type_="foreignkey")
        batch_op.drop_index("ix_extracted_events_recurring_series_id")
        batch_op.drop_column("derivation_summary")
        batch_op.drop_column("fallback_reason_codes")
        batch_op.drop_column("extraction_model")
        batch_op.drop_column("recurring_series_id")

    if is_postgres:
        op.execute("DROP POLICY IF EXISTS recurring_event_series_owner ON recurring_event_series")
    op.drop_index("ix_recurring_event_series_document_id", table_name="recurring_event_series")
    op.drop_index("ix_recurring_event_series_course_id", table_name="recurring_event_series")
    op.drop_index("ix_recurring_event_series_semester_id", table_name="recurring_event_series")
    op.drop_index("ix_recurring_event_series_user_id", table_name="recurring_event_series")
    op.drop_table("recurring_event_series")

    with op.batch_alter_table("processing_jobs") as batch_op:
        batch_op.drop_column("fallback_reason_codes")
        batch_op.drop_column("fallback_used")
        batch_op.drop_column("fallback_model")
        batch_op.drop_column("primary_model")
