from __future__ import annotations

from io import BytesIO
from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ProcessingJob, SyllabusDocument
from app.processing import process_job
from app.storage import StorageError, StorageService

from .conftest import auth_headers
from .test_uploads import create_semester, make_pdf


def uploaded_pdfs(upload_root: Path) -> list[Path]:
    return sorted(path for path in upload_root.rglob("*.pdf") if path.is_file())


def test_upload_rejects_empty_pdf_payload(app_client):
    client, _ = app_client
    semester_id = create_semester(client)

    response = client.post(
        f"/api/semesters/{semester_id}/syllabi",
        headers=auth_headers(),
        files=[("files", ("empty.pdf", BytesIO(b""), "application/pdf"))],
    )

    assert response.status_code == 415
    assert response.json()["detail"] == "The selected file is not a valid PDF."


def test_upload_rejects_corrupt_pdf_payload(app_client):
    client, _ = app_client
    semester_id = create_semester(client)

    response = client.post(
        f"/api/semesters/{semester_id}/syllabi",
        headers=auth_headers(),
        files=[("files", ("broken.pdf", BytesIO(b"not really a pdf"), "application/pdf"))],
    )

    assert response.status_code == 415
    assert response.json()["detail"] == "The selected file is not a valid PDF."


def test_upload_rejects_oversize_pdf_payload(app_client):
    client, app = app_client
    semester_id = create_semester(client)
    app.state.settings.max_upload_bytes = 8

    response = client.post(
        f"/api/semesters/{semester_id}/syllabi",
        headers=auth_headers(),
        files=[("files", ("big.pdf", BytesIO(b"%PDF-1.4 too big"), "application/pdf"))],
    )

    assert response.status_code == 413
    assert response.json()["detail"] == "Each PDF must be 20 MB or smaller."


def test_upload_rejects_missing_mime_even_with_pdf_filename(app_client):
    client, _ = app_client
    semester_id = create_semester(client)

    response = client.post(
        f"/api/semesters/{semester_id}/syllabi",
        headers=auth_headers(),
        files=[("files", ("syllabus.pdf", BytesIO(make_pdf()), ""))],
    )

    assert response.status_code == 415
    assert response.json()["detail"] == "Only PDF syllabus files are supported."


def test_upload_allows_repeated_filenames_as_independent_documents(app_client):
    client, app = app_client
    semester_id = create_semester(client)

    response = client.post(
        f"/api/semesters/{semester_id}/syllabi",
        headers=auth_headers(),
        files=[
            ("files", ("cs101.pdf", BytesIO(make_pdf("first syllabus")), "application/pdf")),
            ("files", ("cs101.pdf", BytesIO(make_pdf("second syllabus")), "application/pdf")),
        ],
    )

    assert response.status_code == 202
    payload = response.json()
    assert len(payload["jobs"]) == 2
    assert len({job["id"] for job in payload["jobs"]}) == 2
    assert [job["filename"] for job in payload["jobs"]] == ["cs101.pdf", "cs101.pdf"]

    with app.state.session_factory() as session:
        semester_uuid = UUID(semester_id)
        documents = session.scalars(
            select(SyllabusDocument).where(SyllabusDocument.semester_id == semester_uuid)
        ).all()
        jobs = session.scalars(
            select(ProcessingJob).where(ProcessingJob.semester_id == semester_uuid)
        ).all()
        assert len(documents) == 2
        assert len(jobs) == 2
        assert {document.filename for document in documents} == {"cs101.pdf"}
        assert len({document.storage_key for document in documents}) == 2
        stored_payloads = [
            (Path(app.state.settings.local_storage_path) / document.storage_key).read_bytes()
            for document in documents
        ]
        assert len(stored_payloads) == 2
        assert len(set(stored_payloads)) == 2


def test_upload_cleans_up_saved_files_when_second_storage_write_fails(
    app_client,
    monkeypatch,
):
    client, app = app_client
    semester_id = create_semester(client)
    original_save = StorageService.save
    upload_root = Path(app.state.settings.local_storage_path)
    save_calls = 0

    def fail_on_second_save(self, storage_key: str, content: bytes, content_type: str) -> None:
        nonlocal save_calls
        save_calls += 1
        if save_calls == 2:
            raise StorageError("storage exploded on second file")
        original_save(self, storage_key, content, content_type)

    monkeypatch.setattr(StorageService, "save", fail_on_second_save)

    response = client.post(
        f"/api/semesters/{semester_id}/syllabi",
        headers=auth_headers(),
        files=[
            ("files", ("first.pdf", BytesIO(make_pdf("first syllabus")), "application/pdf")),
            ("files", ("second.pdf", BytesIO(make_pdf("second syllabus")), "application/pdf")),
        ],
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "storage exploded on second file"
    assert uploaded_pdfs(upload_root) == []
    with app.state.session_factory() as session:
        semester_uuid = UUID(semester_id)
        assert (
            session.scalars(
                select(SyllabusDocument).where(SyllabusDocument.semester_id == semester_uuid)
            ).all()
            == []
        )
        assert (
            session.scalars(
                select(ProcessingJob).where(ProcessingJob.semester_id == semester_uuid)
            ).all()
            == []
        )


def test_upload_cleans_up_second_file_that_was_written_before_storage_error(
    app_client,
    monkeypatch,
):
    client, app = app_client
    semester_id = create_semester(client)
    original_save = StorageService.save
    upload_root = Path(app.state.settings.local_storage_path)
    save_calls = 0

    def write_then_raise(self, storage_key: str, content: bytes, content_type: str) -> None:
        nonlocal save_calls
        save_calls += 1
        original_save(self, storage_key, content, content_type)
        if save_calls == 2:
            raise StorageError("storage exploded after write")

    monkeypatch.setattr(StorageService, "save", write_then_raise)

    response = client.post(
        f"/api/semesters/{semester_id}/syllabi",
        headers=auth_headers(),
        files=[
            ("files", ("first.pdf", BytesIO(make_pdf("first syllabus")), "application/pdf")),
            ("files", ("second.pdf", BytesIO(make_pdf("second syllabus")), "application/pdf")),
        ],
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "storage exploded after write"
    assert uploaded_pdfs(upload_root) == []


def test_upload_cleans_up_second_file_that_was_written_before_os_error(
    app_client,
    monkeypatch,
):
    client, app = app_client
    semester_id = create_semester(client)
    original_save = StorageService.save
    upload_root = Path(app.state.settings.local_storage_path)
    save_calls = 0

    def write_then_raise(self, storage_key: str, content: bytes, content_type: str) -> None:
        nonlocal save_calls
        save_calls += 1
        original_save(self, storage_key, content, content_type)
        if save_calls == 2:
            raise OSError("disk write verification failed")

    monkeypatch.setattr(StorageService, "save", write_then_raise)

    response = client.post(
        f"/api/semesters/{semester_id}/syllabi",
        headers=auth_headers(),
        files=[
            ("files", ("first.pdf", BytesIO(make_pdf("first syllabus")), "application/pdf")),
            ("files", ("second.pdf", BytesIO(make_pdf("second syllabus")), "application/pdf")),
        ],
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "Upload could not be completed."
    assert uploaded_pdfs(upload_root) == []


def test_upload_cleans_up_saved_files_when_database_commit_fails(
    app_client,
    monkeypatch,
):
    _, app = app_client
    client = TestClient(app, raise_server_exceptions=False)
    semester_id = create_semester(client)
    upload_root = Path(app.state.settings.local_storage_path)

    def fail_commit(self):
        raise RuntimeError("commit exploded")

    monkeypatch.setattr(Session, "commit", fail_commit)

    with client:
        response = client.post(
            f"/api/semesters/{semester_id}/syllabi",
            headers=auth_headers(),
            files=[
                ("files", ("first.pdf", BytesIO(make_pdf("first syllabus")), "application/pdf")),
                ("files", ("second.pdf", BytesIO(make_pdf("second syllabus")), "application/pdf")),
            ],
        )

    assert response.status_code == 500
    assert uploaded_pdfs(upload_root) == []
    with app.state.session_factory() as session:
        semester_uuid = UUID(semester_id)
        assert (
            session.scalars(
                select(SyllabusDocument).where(SyllabusDocument.semester_id == semester_uuid)
            ).all()
            == []
        )
        assert (
            session.scalars(
                select(ProcessingJob).where(ProcessingJob.semester_id == semester_uuid)
            ).all()
            == []
        )


def test_malformed_pdf_job_fails_without_blocking_valid_sibling(app_client):
    client, app = app_client
    semester_id = create_semester(client)

    response = client.post(
        f"/api/semesters/{semester_id}/syllabi",
        headers=auth_headers(),
        files=[
            ("files", ("broken.pdf", BytesIO(b"%PDF-not-a-real-document"), "application/pdf")),
            (
                "files",
                (
                    "valid.pdf",
                    BytesIO(make_pdf("Valid midterm October 14, 2026. " * 8)),
                    "application/pdf",
                ),
            ),
        ],
    )

    assert response.status_code == 202
    jobs_by_name = {job["filename"]: job["id"] for job in response.json()["jobs"]}
    broken_job_id = jobs_by_name["broken.pdf"]
    valid_job_id = jobs_by_name["valid.pdf"]

    process_job(
        broken_job_id,
        settings=app.state.settings,
        session_factory=app.state.session_factory,
    )
    process_job(
        valid_job_id,
        settings=app.state.settings,
        session_factory=app.state.session_factory,
    )

    jobs = client.get(
        f"/api/semesters/{semester_id}/jobs",
        headers=auth_headers(),
    )

    assert jobs.status_code == 200
    payload = {job["filename"]: job for job in jobs.json()}
    assert payload["broken.pdf"]["status"] == "failed"
    assert (
        payload["broken.pdf"]["error_message"]
        == "The uploaded file could not be opened as a PDF."
    )
    assert payload["valid.pdf"]["status"] == "needs_review"
    assert payload["valid.pdf"]["error_message"] is None


def test_upload_reports_cleanup_failure_when_compensation_delete_fails(
    app_client,
    monkeypatch,
):
    client, _ = app_client
    semester_id = create_semester(client)
    original_save = StorageService.save

    def save_then_fail(self, storage_key: str, content: bytes, content_type: str) -> None:
        original_save(self, storage_key, content, content_type)
        if storage_key.endswith("second.pdf"):
            raise StorageError("storage exploded after first file")

    def fail_cleanup(self, storage_keys: list[str]) -> None:
        raise StorageError("cleanup delete exploded")

    monkeypatch.setattr(StorageService, "save", save_then_fail)
    monkeypatch.setattr(StorageService, "discard_new_uploads", fail_cleanup)

    response = client.post(
        f"/api/semesters/{semester_id}/syllabi",
        headers=auth_headers(),
        files=[
            ("files", ("first.pdf", BytesIO(make_pdf("first syllabus")), "application/pdf")),
            ("files", ("second.pdf", BytesIO(make_pdf("second syllabus")), "application/pdf")),
        ],
    )

    assert response.status_code == 502
    assert (
        response.json()["detail"]
        == (
            "storage exploded after first file "
            "Partial upload cleanup failed. cleanup delete exploded"
        )
    )


def test_upload_marks_jobs_failed_when_dispatch_fails_after_commit(
    app_client,
    monkeypatch,
):
    client, app = app_client
    semester_id = create_semester(client)
    app.state.settings.processing_mode = "worker"

    def fail_dispatch(job_id, settings):
        raise RuntimeError("queue unavailable")

    monkeypatch.setattr("app.api.dispatch_job", fail_dispatch)

    response = client.post(
        f"/api/semesters/{semester_id}/syllabi",
        headers=auth_headers(),
        files=[
            (
                "files",
                (
                    "cs101.pdf",
                    BytesIO(make_pdf("Midterm October 14, 2026. " * 8)),
                    "application/pdf",
                ),
            )
        ],
    )

    assert response.status_code == 202
    assert response.json()["jobs"][0]["status"] == "failed"
    assert (
        response.json()["jobs"][0]["error_message"]
        == "Processing could not be started. Please try again."
    )

    with app.state.session_factory() as session:
        semester_uuid = UUID(semester_id)
        job = session.scalars(
            select(ProcessingJob).where(ProcessingJob.semester_id == semester_uuid)
        ).one()
        assert job.status == "failed"
        assert job.stage_detail == "Dispatch failed"
        assert job.error_message == "Processing could not be started. Please try again."


def test_upload_dispatch_failure_does_not_block_later_jobs_and_retry_reuses_same_records(
    app_client,
    monkeypatch,
):
    client, app = app_client
    semester_id = create_semester(client)
    app.state.settings.processing_mode = "worker"
    dispatch_calls: list[str] = []

    def fail_first_dispatch(job_id, settings):
        dispatch_calls.append(str(job_id))
        if len(dispatch_calls) == 1:
            raise RuntimeError("queue unavailable")

    monkeypatch.setattr("app.api.dispatch_job", fail_first_dispatch)

    upload = client.post(
        f"/api/semesters/{semester_id}/syllabi",
        headers=auth_headers(),
        files=[
            (
                "files",
                (
                    "first.pdf",
                    BytesIO(make_pdf("First midterm October 14, 2026. " * 8)),
                    "application/pdf",
                ),
            ),
            (
                "files",
                (
                    "second.pdf",
                    BytesIO(make_pdf("Second midterm October 20, 2026. " * 8)),
                    "application/pdf",
                ),
            ),
        ],
    )

    assert upload.status_code == 202
    jobs = {job["filename"]: job for job in upload.json()["jobs"]}
    assert jobs["first.pdf"]["status"] == "failed"
    assert jobs["second.pdf"]["status"] == "queued"
    first_job_id = jobs["first.pdf"]["id"]
    first_document_id = jobs["first.pdf"]["document_id"]

    monkeypatch.setattr("app.api.dispatch_job", lambda job_id, settings: None)

    retry = client.post(f"/api/jobs/{first_job_id}/retry", headers=auth_headers())

    assert retry.status_code == 200
    assert retry.json()["id"] == first_job_id
    assert retry.json()["document_id"] == first_document_id
    assert retry.json()["status"] == "queued"
    assert retry.json()["error_message"] is None

    with app.state.session_factory() as session:
        semester_uuid = UUID(semester_id)
        jobs_in_db = session.scalars(
            select(ProcessingJob).where(ProcessingJob.semester_id == semester_uuid)
        ).all()
        documents_in_db = session.scalars(
            select(SyllabusDocument).where(SyllabusDocument.semester_id == semester_uuid)
        ).all()
        assert len(jobs_in_db) == 2
        assert len(documents_in_db) == 2
        recovered_job = next(job for job in jobs_in_db if str(job.id) == first_job_id)
        assert str(recovered_job.document_id) == first_document_id
        assert recovered_job.status == "queued"
