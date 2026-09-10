"""Add backend-only admission counters and worker execution identity."""

import sqlalchemy as sa

from alembic import op

revision = "0004_processing_security"
down_revision = "0003_recurring_model_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("processing_jobs", sa.Column("execution_id", sa.String(36), nullable=True))
    op.create_table(
        "processing_quotas",
        sa.Column("key", sa.String(120), primary_key=True),
        sa.Column("value", sa.BigInteger(), nullable=False),
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE processing_quotas ENABLE ROW LEVEL SECURITY")
        # These rows are read/written through the authenticated backend API.
        # Owner RLS alone still permits direct REST edits of job status and
        # stored byte counts, or deleting a semester to cascade those rows.
        # Removing SELECT also prevents bypassing API error-message filtering.
        # PostgreSQL table REVOKE removes corresponding column grants as well.
        for table in (
            "semesters", "syllabus_documents", "processing_jobs", "processing_quotas",
        ):
            op.execute(f"REVOKE ALL ON TABLE public.{table} FROM PUBLIC, anon, authenticated")
            # Preserve trusted backend/service access independently of PUBLIC.
            # The migration/table owner retains its implicit owner privileges.
            op.execute(f"GRANT ALL ON TABLE public.{table} TO service_role")


def downgrade() -> None:
    # Intentionally retain restrictive metadata ACLs. Prior deployment grants
    # are unknown, and schema rollback must not reopen direct API bypasses.
    op.drop_table("processing_quotas")
    op.drop_column("processing_jobs", "execution_id")
