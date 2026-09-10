from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

from sqlalchemy import select

from app.models import JobStatus, ProcessingJob, SyllabusDocument

from .conftest import USER_B, auth_headers
from .test_uploads import create_semester, make_pdf


def upload(client, semester_id, content=None, count=1):
    return client.post(
        f"/api/semesters/{semester_id}/syllabi",
        headers=auth_headers(),
        files=[("files", (f"{i}.pdf", content or make_pdf(), "application/pdf"))
               for i in range(count)],
    )


def limit(app, **values):
    # Allow these behavioral regression tests to run against the pre-fix settings too.
    app.state.settings.__dict__.update(values)


def test_daily_upload_quota_survives_semester_deletion(app_client):
    client, app = app_client
    limit(app, max_user_jobs_per_day=1)
    semester_id = create_semester(client)
    assert upload(client, semester_id).status_code == 202
    assert client.delete(f"/api/semesters/{semester_id}", headers=auth_headers()).status_code == 204
    response = upload(client, create_semester(client))
    assert response.status_code == 429


def test_aggregate_upload_limit_writes_nothing(app_client):
    client, app = app_client
    pdf = make_pdf()
    limit(app, max_upload_total_bytes=len(pdf) + 1)
    response = upload(client, create_semester(client), pdf, count=2)
    assert response.status_code == 413
    with app.state.session_factory() as db:
        assert db.scalars(select(SyllabusDocument)).all() == []


def test_storage_and_active_job_limits(app_client):
    client, app = app_client
    limit(app, max_user_active_jobs=1)
    semester_id = create_semester(client)
    first = upload(client, semester_id)
    assert first.status_code == 202
    assert upload(client, semester_id).status_code == 429
    with app.state.session_factory() as db:
        job = db.get(ProcessingJob, UUID(first.json()["jobs"][0]["id"]))
        job.status = JobStatus.COMPLETED
        db.commit()
    limit(app, max_user_storage_bytes=1)
    assert upload(client, semester_id).status_code == 429


def test_concurrent_uploads_cannot_exceed_daily_limit(app_client):
    client, app = app_client
    limit(app, max_user_jobs_per_day=1)
    semester_id = create_semester(client)
    with ThreadPoolExecutor(max_workers=2) as pool:
        codes = list(pool.map(lambda _: upload(client, semester_id).status_code, range(2)))
    assert sorted(codes) == [202, 429]
    with app.state.session_factory() as db:
        assert len(db.scalars(select(ProcessingJob)).all()) == 1


def test_retry_and_reprocess_share_daily_quota(app_client):
    client, app = app_client
    limit(app, max_user_jobs_per_day=1)
    semester_id = create_semester(client)
    job_id = upload(client, semester_id).json()["jobs"][0]["id"]
    for state, operation in [(JobStatus.FAILED, "retry"), (JobStatus.COMPLETED, "reprocess")]:
        with app.state.session_factory() as db:
            db.get(ProcessingJob, UUID(job_id)).status = state
            db.commit()
        response = client.post(f"/api/jobs/{job_id}/{operation}", headers=auth_headers())
        assert response.status_code == 429
        with app.state.session_factory() as db:
            assert db.get(ProcessingJob, UUID(job_id)).status == state


def test_concurrent_reprocess_dispatches_once(app_client, monkeypatch):
    client, app = app_client
    semester_id = create_semester(client)
    job_id = upload(client, semester_id).json()["jobs"][0]["id"]
    with app.state.session_factory() as db:
        db.get(ProcessingJob, UUID(job_id)).status = JobStatus.COMPLETED
        db.commit()
    app.state.settings.processing_mode = "worker"
    dispatched = []
    monkeypatch.setattr(
        "app.api.dispatch_job", lambda job_id, settings, **kwargs: dispatched.append(job_id),
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        codes = list(pool.map(lambda _: client.post(
            f"/api/jobs/{job_id}/reprocess", headers=auth_headers(),
        ).status_code, range(2)))
    assert sorted(codes) == [200, 409]
    assert len(dispatched) == 1


def test_global_daily_quota_applies_across_users(app_client):
    client, app = app_client
    limit(app, max_global_jobs_per_day=1)
    assert upload(client, create_semester(client)).status_code == 202
    semester = client.post("/api/semesters", headers=auth_headers(USER_B), json={
        "name": "Second user", "start_date": "2026-08-24",
        "end_date": "2026-12-18", "timezone": "UTC",
    }).json()["id"]
    response = client.post(
        f"/api/semesters/{semester}/syllabi", headers=auth_headers(USER_B),
        files=[("files", ("sample.pdf", make_pdf(), "application/pdf"))],
    )
    assert response.status_code == 429


def test_failed_upload_rolls_back_quota_reservation(app_client, monkeypatch):
    from app.storage import StorageError, StorageService

    client, app = app_client
    limit(app, max_user_jobs_per_day=1)
    semester = create_semester(client)
    original = StorageService.save

    def fail(*args):
        raise StorageError("Storage request failed.")

    monkeypatch.setattr(StorageService, "save", fail)
    assert upload(client, semester).status_code == 502
    monkeypatch.setattr(StorageService, "save", original)
    assert upload(client, semester).status_code == 202


def test_delivered_job_is_not_failed_when_producer_reports_error(app_client, monkeypatch):
    from app.job_execution import claim_job

    client, app = app_client
    app.state.settings.processing_mode = "worker"

    def delivered_then_error(job_id, settings, **kwargs):
        with app.state.session_factory() as db:
            assert claim_job(db, job_id, kwargs["execution_id"])
        raise RuntimeError("broker confirmation lost")

    monkeypatch.setattr("app.api.dispatch_job", delivered_then_error)
    response = upload(client, create_semester(client))
    assert response.status_code == 202
    assert response.json()["jobs"][0]["status"] == "extracting_text"
