from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import UTC, date, datetime
from threading import Barrier, Event
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.errors import PROCESSING_FAILED_MESSAGE, PROCESSING_TIMEOUT_MESSAGE, public_error_message
from app.job_execution import claim_job, fail_job_execution
from app.models import (
    ConfidenceLevel,
    Course,
    ExtractedEvent,
    JobStatus,
    ProcessingJob,
    ReviewStatus,
    Semester,
    SyllabusDocument,
)
from app.processing import SyllabusExtraction, process_job

from .conftest import USER_A


def seed_job(app, status=JobStatus.QUEUED):
    with app.state.session_factory() as session:
        semester = Semester(
            user_id=USER_A, name="Fall", start_date=date(2026, 8, 24),
            end_date=date(2026, 12, 18), timezone="America/New_York",
            review_completed_at=datetime.now(UTC),
        )
        session.add(semester)
        session.flush()
        document = SyllabusDocument(
            user_id=USER_A, semester_id=semester.id, filename="syllabus.pdf",
            size_bytes=10, storage_key=str(uuid4()),
            extracted_pages=[{"page": 1, "text": "Existing reviewed evidence"}],
        )
        job = ProcessingJob(
            user_id=USER_A, semester_id=semester.id, document=document,
            status=status, attempts=2,
        )
        session.add(job)
        session.commit()
        return job.id


@pytest.mark.parametrize("status", [
    JobStatus.EXTRACTING_TEXT, JobStatus.RUNNING_OCR, JobStatus.EXTRACTING_EVENTS,
    JobStatus.VALIDATING, JobStatus.NEEDS_REVIEW, JobStatus.COMPLETED, JobStatus.FAILED,
])
def test_unqueued_deliveries_do_not_read_files_or_start_models(app_client, monkeypatch, status):
    _, app = app_client
    job_id = seed_job(app, status)

    def unexpected(*args, **kwargs):
        pytest.fail("Duplicate delivery must not perform processing")

    monkeypatch.setattr("app.processing.StorageService.read", unexpected)
    monkeypatch.setattr("app.processing.extract_syllabus", unexpected)
    process_job(str(job_id), app.state.settings, app.state.session_factory)
    with app.state.session_factory() as session:
        job = session.get(ProcessingJob, job_id)
        assert job.status == status
        assert job.attempts == 2


def test_concurrent_deliveries_only_one_claims_job(app_client, monkeypatch):
    _, app = app_client
    job_id = seed_job(app)
    gate = Barrier(2)
    entered = Event()
    release = Event()
    calls = []

    def read_once(*args):
        calls.append(1)
        entered.set()
        assert release.wait(10)
        raise RuntimeError("deliberate failed processing")

    def deliver():
        gate.wait(10)
        process_job(str(job_id), app.state.settings, app.state.session_factory)

    monkeypatch.setattr("app.processing.StorageService.read", read_once)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(deliver) for _ in range(2)]
        try:
            assert entered.wait(10)
            # One delivery completes while the claim winner is still processing.
            done, _ = wait(futures, timeout=10, return_when=FIRST_COMPLETED)
            assert len(done) == 1
        finally:
            release.set()
        for future in futures:
            future.result(timeout=10)
    assert calls == [1]
    with app.state.session_factory() as session:
        assert session.get(ProcessingJob, job_id).attempts == 3


def test_failure_hides_secrets_and_preserves_review(app_client, monkeypatch, caplog):
    _, app = app_client
    job_id = seed_job(app)
    secret = "sk-sensitive-value-private-provider-response"

    def failed_read(*args):
        raise RuntimeError(f"Request failed with {secret} at /private/customer.pdf")

    monkeypatch.setattr("app.processing.StorageService.read", failed_read)
    process_job(str(job_id), app.state.settings, app.state.session_factory)
    with app.state.session_factory() as session:
        job = session.get(ProcessingJob, job_id)
        assert job.status == JobStatus.FAILED
        assert secret not in job.error_message
        assert "/private" not in job.error_message
        assert job.document.extracted_pages[0]["text"] == "Existing reviewed evidence"
        assert job.document.semester.review_completed_at is not None
    assert secret not in caplog.text
    assert "RuntimeError" in caplog.text


def test_old_timeout_does_not_overwrite_new_attempt_or_finished_review(app_client):
    _, app = app_client
    job_id = seed_job(app)
    current_execution = str(uuid4())
    with app.state.session_factory() as session:
        assert claim_job(session, job_id, current_execution)
    fail_job_execution(app.state.session_factory, job_id, str(uuid4()), PROCESSING_TIMEOUT_MESSAGE)
    with app.state.session_factory() as session:
        job = session.get(ProcessingJob, job_id)
        assert job.status == JobStatus.EXTRACTING_TEXT
        job.status = JobStatus.NEEDS_REVIEW
        session.commit()
    fail_job_execution(
        app.state.session_factory, job_id, current_execution, PROCESSING_TIMEOUT_MESSAGE,
    )
    with app.state.session_factory() as session:
        assert session.get(ProcessingJob, job_id).status == JobStatus.NEEDS_REVIEW


def test_timeout_marks_matching_execution_failed(app_client):
    _, app = app_client
    job_id = seed_job(app)
    execution = str(uuid4())
    with app.state.session_factory() as session:
        assert claim_job(session, job_id, execution)
    fail_job_execution(app.state.session_factory, job_id, execution, PROCESSING_TIMEOUT_MESSAGE)
    with app.state.session_factory() as session:
        job = session.get(ProcessingJob, job_id)
        assert job.status == JobStatus.FAILED
        assert job.error_message == PROCESSING_TIMEOUT_MESSAGE


def test_late_pipeline_failure_rolls_back_reviewed_events(app_client, monkeypatch):
    _, app = app_client
    job_id = seed_job(app)
    with app.state.session_factory() as session:
        job = session.get(ProcessingJob, job_id)
        course = Course(
            user_id=USER_A, semester_id=job.semester_id, document_id=job.document_id,
            name="Reviewed course",
        )
        session.add(course)
        session.flush()
        event = ExtractedEvent(
            user_id=USER_A, semester_id=job.semester_id, document_id=job.document_id,
            course_id=course.id, title="Reviewed exam", event_type="exam",
            event_date=date(2026, 10, 20), timezone="America/New_York",
            source_quote="Reviewed evidence", confidence=ConfidenceLevel.HIGH,
            review_status=ReviewStatus.CONFIRMED,
        )
        session.add(event)
        session.commit()
        event_id, course_id = event.id, course.id

    monkeypatch.setattr("app.processing.StorageService.read", lambda *args: b"pdf")
    monkeypatch.setattr("app.processing.extract_pdf_pages", lambda *args, **kwargs: (
        [{"page": 1, "text": "Course text", "ocr": False}], False,
    ))
    monkeypatch.setattr("app.processing.extract_syllabus", lambda *args: SyllabusExtraction(
        course_name="Replacement course", events=[],
    ))

    def fail_after_deletes(**kwargs):
        raise RuntimeError("provider secret body")

    monkeypatch.setattr("app.processing.expand_recurring_rules", fail_after_deletes)
    process_job(str(job_id), app.state.settings, app.state.session_factory)
    with app.state.session_factory() as session:
        assert session.get(ProcessingJob, job_id).status == JobStatus.FAILED
        assert session.get(Course, course_id).name == "Reviewed course"
        assert session.get(ExtractedEvent, event_id).review_status == ReviewStatus.CONFIRMED


def test_legacy_error_strings_are_never_trusted():
    assert public_error_message(None) is None
    assert public_error_message("request key=secret path=/private") == PROCESSING_FAILED_MESSAGE
    assert public_error_message(PROCESSING_TIMEOUT_MESSAGE) == PROCESSING_TIMEOUT_MESSAGE


def test_production_refuses_pools_without_hard_time_limits(app_client, monkeypatch):
    import app.worker as worker

    monkeypatch.setattr(worker, "settings", SimpleNamespace(app_env="production"))
    monkeypatch.setattr(worker.sys, "platform", "linux")
    monkeypatch.setenv("MALLOC_ARENA_MAX", "2")
    with pytest.raises(SystemExit, match="prefork"):
        worker.require_bounded_production_worker(SimpleNamespace(pool_cls="threads"))
    worker.require_bounded_production_worker(SimpleNamespace(
        pool_cls="prefork", max_tasks_per_child=1, soft_time_limit=None,
    ))
    with pytest.raises(SystemExit, match="one task"):
        worker.require_bounded_production_worker(SimpleNamespace(
            pool_cls="prefork", max_tasks_per_child=2, soft_time_limit=None,
        ))
    with pytest.raises(SystemExit, match="soft limit"):
        worker.require_bounded_production_worker(SimpleNamespace(
            pool_cls="prefork", max_tasks_per_child=1, soft_time_limit=300,
        ))
    monkeypatch.setattr(worker.sys, "platform", "win32")
    with pytest.raises(SystemExit, match="Linux"):
        worker.require_bounded_production_worker(SimpleNamespace(pool_cls="prefork"))


@pytest.mark.parametrize("arena_limit", [None, "", "1", "8"])
def test_production_requires_allocator_limit_before_worker_start(
    app_client, monkeypatch, arena_limit,
):
    import app.worker as worker

    monkeypatch.setattr(worker, "settings", SimpleNamespace(app_env="production"))
    monkeypatch.setattr(worker.sys, "platform", "linux")
    if arena_limit is None:
        monkeypatch.delenv("MALLOC_ARENA_MAX", raising=False)
    else:
        monkeypatch.setenv("MALLOC_ARENA_MAX", arena_limit)
    sender = SimpleNamespace(pool_cls="prefork", max_tasks_per_child=1, soft_time_limit=None)
    with pytest.raises(SystemExit, match="MALLOC_ARENA_MAX=2.*before"):
        worker.require_bounded_production_worker(sender)
    # Detecting a missing startup prerequisite must not pretend that changing
    # the environment now can reconfigure an already initialized allocator.
    assert worker.os.environ.get("MALLOC_ARENA_MAX") == arena_limit
    monkeypatch.setenv("MALLOC_ARENA_MAX", "2")
    worker.require_bounded_production_worker(sender)


def test_memory_cap_is_applied_inside_child(app_client, monkeypatch):
    import sys

    import app.worker as worker

    calls = []
    fake_resource = SimpleNamespace(
        RLIMIT_AS=9, RLIM_INFINITY=-1,
        getrlimit=lambda resource: (-1, -1),
        setrlimit=lambda resource, limits: calls.append((resource, limits)),
    )
    monkeypatch.setitem(sys.modules, "resource", fake_resource)
    monkeypatch.setattr(worker.os, "environ", {})
    isolated = []
    monkeypatch.setattr(worker.os, "setsid", lambda: isolated.append(True), raising=False)
    monkeypatch.setattr(worker, "settings", SimpleNamespace(
        app_env="production", processing_memory_limit_mb=512,
    ))
    worker.limit_production_worker_memory()
    assert isolated == [True]
    assert calls == [(9, (512 * 1024 * 1024, 512 * 1024 * 1024))]


def test_hard_timeout_callback_runs_in_parent(app_client, monkeypatch):
    import app.worker as worker

    recorded = []
    monkeypatch.setattr(worker.Request, "on_timeout", lambda *args: None)
    # Use a real subclass instance so zero-argument super resolves normally.
    request = object.__new__(worker.ProcessingRequest)
    monkeypatch.setattr(
        worker.ProcessingRequest, "_record_failure", lambda self, msg: recorded.append(msg),
    )
    worker.ProcessingRequest.on_timeout(request, True, 300)
    assert recorded == []
    worker.ProcessingRequest.on_timeout(request, False, 310)
    assert recorded == [PROCESSING_TIMEOUT_MESSAGE]


@pytest.mark.parametrize("pause_at", ["page_extraction", "final_replacement"])
def test_stale_attempt_cannot_flush_document_or_replace_new_events(
    app_client, monkeypatch, pause_at,
):
    import app.processing as processing

    _, app = app_client
    job_id = seed_job(app)
    old_execution = str(uuid4())
    new_execution = str(uuid4())
    newest_event_id = uuid4()

    def replace_attempt():
        fail_job_execution(
            app.state.session_factory, job_id, old_execution, PROCESSING_TIMEOUT_MESSAGE,
        )
        with app.state.session_factory() as session:
            job = session.get(ProcessingJob, job_id)
            assert job.status == JobStatus.FAILED
            job.status = JobStatus.QUEUED
            job.execution_id = new_execution
            session.commit()
            assert claim_job(session, job_id, new_execution)
            job.document.extracted_pages = [{"page": 1, "text": "New execution evidence"}]
            course = Course(
                user_id=USER_A, semester_id=job.semester_id, document_id=job.document_id,
                name="New execution course",
            )
            session.add(course)
            session.flush()
            session.add(ExtractedEvent(
                id=newest_event_id, user_id=USER_A, semester_id=job.semester_id,
                document_id=job.document_id, course_id=course.id, title="New execution event",
                event_type="exam", event_date=date(2026, 10, 20),
                timezone="America/New_York", source_quote="New evidence",
                confidence=ConfidenceLevel.HIGH, review_status=ReviewStatus.CONFIRMED,
            ))
            session.commit()

    def extract_pages(*args, **kwargs):
        if pause_at == "page_extraction":
            replace_attempt()
        return [{"page": 1, "text": "Stale execution text", "ocr": False}], False

    original_update = processing._update_job

    def update_stage(session, job, status, detail, **kwargs):
        original_update(session, job, status, detail, **kwargs)
        if pause_at == "final_replacement" and status == JobStatus.VALIDATING:
            replace_attempt()

    monkeypatch.setattr(processing.StorageService, "read", lambda *args: b"pdf")
    monkeypatch.setattr(processing, "extract_pdf_pages", extract_pages)
    monkeypatch.setattr(processing, "_update_job", update_stage)
    monkeypatch.setattr(processing, "extract_syllabus", lambda *args: SyllabusExtraction(
        course_name="Stale execution course", events=[],
    ))
    process_job(
        str(job_id), app.state.settings, app.state.session_factory, execution_id=old_execution,
    )
    with app.state.session_factory() as session:
        job = session.get(ProcessingJob, job_id)
        assert job.execution_id == new_execution
        assert job.status == JobStatus.EXTRACTING_TEXT
        assert job.attempts == 4
        assert job.document.extracted_pages[0]["text"] == "New execution evidence"
        event = session.get(ExtractedEvent, newest_event_id)
        assert event.title == "New execution event"
        assert event.course.name == "New execution course"
        assert event.review_status == ReviewStatus.CONFIRMED


def test_parent_failure_bookkeeping_does_not_block_child_kill(app_client, monkeypatch):
    import app.worker as worker

    entered = Event()
    release = Event()

    def blocked_database(*args):
        entered.set()
        release.wait(10)

    monkeypatch.setattr(worker, "record_worker_failure", blocked_database)
    request = SimpleNamespace(args=(str(uuid4()),), id=str(uuid4()))
    with ThreadPoolExecutor(max_workers=1) as executor:
        callback = executor.submit(
            worker.ProcessingRequest._record_failure, request, PROCESSING_TIMEOUT_MESSAGE,
        )
        try:
            assert entered.wait(5)
            callback.result(timeout=1)
        finally:
            release.set()


def test_delayed_delivery_cannot_claim_new_queued_generation(app_client, monkeypatch):
    _, app = app_client
    job_id = seed_job(app)
    new_execution = str(uuid4())
    with app.state.session_factory() as session:
        job = session.get(ProcessingJob, job_id)
        job.execution_id = new_execution
        session.commit()

    def unexpected(*args, **kwargs):
        pytest.fail("A stale delivery must never read the new generation's file")

    monkeypatch.setattr("app.processing.StorageService.read", unexpected)
    process_job(
        str(job_id), app.state.settings, app.state.session_factory, execution_id=str(uuid4()),
    )
    with app.state.session_factory() as session:
        job = session.get(ProcessingJob, job_id)
        assert job.status == JobStatus.QUEUED
        assert job.execution_id == new_execution
        assert job.attempts == 2


def test_preclaim_import_failure_only_fails_matching_queued_generation(app_client):
    _, app = app_client
    job_id = seed_job(app)
    execution = str(uuid4())
    with app.state.session_factory() as session:
        job = session.get(ProcessingJob, job_id)
        job.execution_id = execution
        session.commit()
    fail_job_execution(app.state.session_factory, job_id, str(uuid4()), MemoryError())
    with app.state.session_factory() as session:
        assert session.get(ProcessingJob, job_id).status == JobStatus.QUEUED
    fail_job_execution(app.state.session_factory, job_id, execution, MemoryError())
    with app.state.session_factory() as session:
        assert session.get(ProcessingJob, job_id).status == JobStatus.FAILED


def test_worker_uses_hard_deadline_without_swallowable_soft_timeout(app_client):
    import app.worker as worker

    assert worker.celery_app.conf.task_soft_time_limit is None
    assert worker.celery_app.conf.task_time_limit == worker.settings.processing_timeout_seconds
    assert worker.celery_app.conf.worker_max_tasks_per_child == 1


def test_group_cleanup_never_targets_parent_and_handles_exited_leader(monkeypatch):
    import app.process_limits as limits

    calls = []
    monkeypatch.setattr(limits.os, "getpid", lambda: 100)
    monkeypatch.setattr(limits.os, "getpgrp", lambda: 90, raising=False)
    monkeypatch.setattr(limits.signal, "SIGKILL", 9, raising=False)
    monkeypatch.setattr(
        limits.os, "killpg", lambda group, signal: calls.append(group), raising=False,
    )
    for group in (None, 0, 1, 90, 100):
        limits.kill_worker_process_group(group)
    assert calls == []
    limits.kill_worker_process_group(200)
    assert calls == [200]

    def already_exited(*args):
        raise ProcessLookupError

    monkeypatch.setattr(limits.os, "killpg", already_exited)
    limits.kill_worker_process_group(200)


def test_generated_celery_request_keeps_success_group_cleanup(app_client, monkeypatch):
    from celery.worker.request import create_request_cls

    import app.worker as worker

    calls = []
    monkeypatch.setattr(worker.Request, "__init__", lambda self, *args, **kwargs: None)
    monkeypatch.setattr(
        worker.ProcessingRequest, "_cleanup_process_group", lambda self: calls.append("cleanup"),
    )
    task = SimpleNamespace(time_limit=300, soft_time_limit=None, acks_late=False)
    request_class = create_request_cls(
        worker.ProcessingRequest, task, SimpleNamespace(apply_async=lambda *args: None),
        "test-worker", None, task_ready=lambda *args, **kwargs: calls.append("result-accepted"),
        app=SimpleNamespace(use_fast_trace_task=False),
    )
    request = request_class()
    request.on_success((False, None, 0.01))
    assert calls == ["result-accepted", "cleanup"]
