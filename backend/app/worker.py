from __future__ import annotations

import os
import sys
from threading import Thread
from uuid import UUID

from celery import Celery, Task, signals
from celery.worker.request import Request
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .config import get_settings
from .errors import (
    PROCESSING_RESOURCE_MESSAGE,
    PROCESSING_TIMEOUT_MESSAGE,
    log_processing_failure,
)
from .job_execution import fail_job_execution
from .process_limits import isolate_worker_process, kill_worker_process_group

settings = get_settings()
celery_app = Celery("syllabus_calendar", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(
    task_always_eager=settings.celery_task_always_eager,
    task_eager_propagates=True,
    task_track_started=True,
    worker_prefetch_multiplier=1,
    worker_pool="prefork",
    worker_concurrency=2,
    task_soft_time_limit=None,
    task_time_limit=settings.processing_timeout_seconds,
    worker_max_tasks_per_child=1,
    worker_max_memory_per_child=settings.processing_memory_limit_mb * 1024,
)


@signals.worker_init.connect
def require_bounded_production_worker(sender=None, **kwargs) -> None:
    if settings.app_env != "production":
        return
    from celery.concurrency.prefork import TaskPool

    if not sys.platform.startswith("linux") or sender.pool_cls not in ("prefork", TaskPool):
        raise SystemExit("Production processing requires a Linux Celery prefork worker.")
    if os.environ.get("MALLOC_ARENA_MAX") != "2":
        raise SystemExit(
            "Set MALLOC_ARENA_MAX=2 in the container or shell before starting Python/Celery "
            "so allocator arenas fit within the processing memory limit."
        )
    if sender.max_tasks_per_child != 1:
        raise SystemExit("Production processing requires one task per worker child.")
    if sender.soft_time_limit:
        raise SystemExit("Production processing must use a hard time limit without a soft limit.")


@signals.worker_process_init.connect
def limit_production_worker_memory(**kwargs) -> None:
    if settings.app_env != "production":
        return
    try:
        isolate_worker_process(settings.processing_memory_limit_mb)
    except (ValueError, OSError) as error:
        log_processing_failure("worker-initialization", error)
        raise SystemExit("The processing process isolation could not be enforced.") from None


def record_worker_failure(job_id: str, execution_id: str, message: str) -> None:
    try:
        if settings.database_url.startswith("postgresql"):
            connect_args = {"connect_timeout": 5, "options": "-c statement_timeout=10000"}
        elif settings.database_url.startswith("sqlite"):
            connect_args = {"timeout": 10}
        else:
            connect_args = {}
        engine = create_engine(settings.database_url, connect_args=connect_args)
        try:
            fail_job_execution(sessionmaker(bind=engine), UUID(job_id), execution_id, message)
        finally:
            engine.dispose()
    except Exception as error:
        log_processing_failure(job_id, error)


class ProcessingRequest(Request):
    """Failure handlers run in the parent even when a child is hard-killed."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._isolated_process_group = None
        # Celery generates a subclass with an optimized on_success override.
        # Wrap the effective callback on the instance so both implementations
        # acknowledge the result before the one-use child's group is reaped.
        original_success = self.on_success

        def success_with_cleanup(*callback_args, **callback_kwargs):
            try:
                return original_success(*callback_args, **callback_kwargs)
            finally:
                self._cleanup_process_group()

        self.on_success = success_with_cleanup

    def on_accepted(self, pid, time_accepted):
        if settings.app_env == "production":
            try:
                if os.getpgid(pid) == pid and pid != os.getpgrp():
                    self._isolated_process_group = pid
            except ProcessLookupError:
                pass
        super().on_accepted(pid, time_accepted)

    def _cleanup_process_group(self) -> None:
        if settings.app_env == "production":
            kill_worker_process_group(getattr(self, "_isolated_process_group", None))

    def _record_failure(self, message: str) -> None:
        job_id = self.args[0] if self.args else self.kwargs.get("job_id")
        if job_id:
            # Billiard calls this hook before killing the child. Never block
            # that kill on a database lock still held by the same child.
            Thread(
                target=record_worker_failure,
                args=(str(job_id), self.id, message),
                daemon=True,
            ).start()

    def on_timeout(self, soft, timeout):
        if not soft:
            self._record_failure(PROCESSING_TIMEOUT_MESSAGE)
        super().on_timeout(soft, timeout)

    def on_failure(self, exc_info, send_failed_event=True, return_ok=False):
        self._record_failure(PROCESSING_RESOURCE_MESSAGE)
        try:
            super().on_failure(exc_info, send_failed_event=send_failed_event, return_ok=return_ok)
        finally:
            self._cleanup_process_group()


class ProcessingTask(Task):
    Request = ProcessingRequest


@celery_app.task(name="process_document_job", bind=True, base=ProcessingTask)
def process_document_job(self, job_id: str) -> None:
    from .processing import process_job

    process_job(job_id, execution_id=self.request.id)
