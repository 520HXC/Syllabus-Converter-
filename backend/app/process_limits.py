"""Linux process isolation helpers, kept independent of Celery and the database."""
from __future__ import annotations

import os
import signal


def isolate_worker_process(memory_limit_mb: int) -> None:
    import resource

    # Billiard can terminate descendants only when the worker leads a group.
    # Poppler/Tesseract inherit this isolated session and process group.
    os.setsid()
    for variable in (
        "OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "OMP_THREAD_LIMIT", "MKL_NUM_THREADS",
    ):
        os.environ[variable] = "1"
    limit_bytes = memory_limit_mb * 1024 * 1024
    _, existing_hard = resource.getrlimit(resource.RLIMIT_AS)
    if existing_hard != resource.RLIM_INFINITY:
        limit_bytes = min(limit_bytes, existing_hard)
    resource.setrlimit(resource.RLIMIT_AS, (limit_bytes, limit_bytes))


def kill_worker_process_group(process_group_id: int | None) -> None:
    """Reap a previously verified worker group after its sole task finishes."""
    if (
        process_group_id is None or process_group_id <= 1
        or process_group_id in (os.getpid(), os.getpgrp())
    ):
        return
    try:
        # The leader may already have exited while an OCR descendant remains.
        # Its recorded group remains valid until every member exits.
        os.killpg(process_group_id, signal.SIGKILL)
    except ProcessLookupError:
        pass
