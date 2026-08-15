"""Create the Syllabus Calendar MVP schema.

Revision ID: 0001_initial
Revises:
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    job_status = sa.Enum(
        "QUEUED",
        "EXTRACTING_TEXT",
        "RUNNING_OCR",
        "EXTRACTING_EVENTS",
        "VALIDATING",
        "NEEDS_REVIEW",
        "COMPLETED",
        "FAILED",
        name="jobstatus",
    )
    confidence = sa.Enum("HIGH", "MEDIUM", "LOW", name="confidencelevel")
    review_status = sa.Enum("NEEDS_REVIEW", "CONFIRMED", "IGNORED", name="reviewstatus")

    op.create_table(
        "profiles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320)),
        sa.Column("display_name", sa.String(length=160)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "semesters",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("timezone", sa.String(length=80), nullable=False),
        sa.Column("review_completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_semesters_user_id", "semesters", ["user_id"])
    op.create_table(
        "syllabus_documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("semester_id", sa.Uuid(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("extracted_pages", sa.JSON(), nullable=False),
        sa.Column("used_ocr", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["semester_id"], ["semesters.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_key"),
    )
    op.create_index("ix_syllabus_documents_user_id", "syllabus_documents", ["user_id"])
    op.create_index("ix_syllabus_documents_semester_id", "syllabus_documents", ["semester_id"])
    op.create_table(
        "courses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("semester_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid()),
        sa.Column("code", sa.String(length=40)),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("instructor", sa.String(length=160)),
        sa.Column("color", sa.String(length=7), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["syllabus_documents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["semester_id"], ["semesters.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_courses_user_id", "courses", ["user_id"])
    op.create_index("ix_courses_semester_id", "courses", ["semester_id"])
    op.create_index("ix_courses_document_id", "courses", ["document_id"], unique=True)
    op.create_table(
        "processing_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("semester_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("status", job_status, nullable=False),
        sa.Column("stage_detail", sa.String(length=240)),
        sa.Column("error_message", sa.Text()),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["document_id"], ["syllabus_documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["semester_id"], ["semesters.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_processing_jobs_user_id", "processing_jobs", ["user_id"])
    op.create_index("ix_processing_jobs_semester_id", "processing_jobs", ["semester_id"])
    op.create_index(
        "ix_processing_jobs_document_id",
        "processing_jobs",
        ["document_id"],
        unique=True,
    )
    op.create_table(
        "extracted_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("semester_id", sa.Uuid(), nullable=False),
        sa.Column("course_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid()),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("event_date", sa.Date(), nullable=False),
        sa.Column("start_time", sa.Time()),
        sa.Column("end_time", sa.Time()),
        sa.Column("timezone", sa.String(length=80), nullable=False),
        sa.Column("is_all_day", sa.Boolean(), nullable=False),
        sa.Column("source_quote", sa.Text(), nullable=False),
        sa.Column("source_page", sa.Integer(), nullable=False),
        sa.Column("confidence", confidence, nullable=False),
        sa.Column("warning_codes", sa.JSON(), nullable=False),
        sa.Column("warning_reason", sa.Text()),
        sa.Column("review_status", review_status, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["syllabus_documents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["semester_id"], ["semesters.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_extracted_events_user_id", "extracted_events", ["user_id"])
    op.create_index("ix_extracted_events_semester_id", "extracted_events", ["semester_id"])
    op.create_index("ix_extracted_events_course_id", "extracted_events", ["course_id"])
    op.create_index("ix_extracted_events_document_id", "extracted_events", ["document_id"])

    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE profiles ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE semesters ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE courses ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE syllabus_documents ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE processing_jobs ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE extracted_events ENABLE ROW LEVEL SECURITY")
        op.execute(
            "CREATE POLICY profiles_owner ON profiles FOR ALL TO authenticated "
            "USING ((select auth.uid()) = id) WITH CHECK ((select auth.uid()) = id)"
        )
        for table in (
            "semesters",
            "courses",
            "syllabus_documents",
            "processing_jobs",
            "extracted_events",
        ):
            op.execute(
                f"CREATE POLICY {table}_owner ON {table} FOR ALL TO authenticated "
                "USING ((select auth.uid()) = user_id) "
                "WITH CHECK ((select auth.uid()) = user_id)"
            )
        op.execute(
            "INSERT INTO storage.buckets (id, name, public) VALUES ('syllabi', 'syllabi', false) "
            "ON CONFLICT (id) DO UPDATE SET public = false"
        )
        op.execute(
            "ALTER TABLE profiles ADD CONSTRAINT profiles_auth_user_fk "
            "FOREIGN KEY (id) REFERENCES auth.users(id) ON DELETE CASCADE"
        )
        op.execute(
            "CREATE OR REPLACE FUNCTION public.handle_new_user() RETURNS trigger "
            "LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$ "
            "BEGIN INSERT INTO public.profiles (id, email, display_name, created_at, updated_at) "
            "VALUES (new.id, new.email, new.raw_user_meta_data ->> 'full_name', now(), now()) "
            "ON CONFLICT (id) DO NOTHING; RETURN new; END; $$"
        )
        op.execute(
            "CREATE TRIGGER on_auth_user_created AFTER INSERT ON auth.users "
            "FOR EACH ROW EXECUTE PROCEDURE public.handle_new_user()"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users")
        op.execute("DROP FUNCTION IF EXISTS public.handle_new_user()")
    op.drop_table("extracted_events")
    op.drop_table("processing_jobs")
    op.drop_table("courses")
    op.drop_table("syllabus_documents")
    op.drop_table("semesters")
    op.drop_table("profiles")
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TYPE IF EXISTS reviewstatus")
        op.execute("DROP TYPE IF EXISTS confidencelevel")
        op.execute("DROP TYPE IF EXISTS jobstatus")
