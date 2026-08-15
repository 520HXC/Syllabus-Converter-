from __future__ import annotations

from celery import Celery

from .config import get_settings

settings = get_settings()
celery_app = Celery("syllabus_calendar", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(
    task_always_eager=settings.celery_task_always_eager,
    task_eager_propagates=True,
    task_track_started=True,
    worker_prefetch_multiplier=1,
)


@celery_app.task(name="process_document_job")
def process_document_job(job_id: str) -> None:
    from .processing import process_job

    process_job(job_id)
