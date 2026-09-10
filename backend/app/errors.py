from __future__ import annotations

import logging
import traceback

PROCESSING_FAILED_MESSAGE = "Processing failed. Please retry this file or contact support."
PROCESSING_TIMEOUT_MESSAGE = "PDF processing exceeded its time limit. Try a shorter PDF."
PROCESSING_RESOURCE_MESSAGE = "PDF processing exceeded its resource limit. Try a simpler PDF."

SAFE_ERROR_MESSAGES = frozenset({
    "Processing could not be started. Please try again.",
    PROCESSING_FAILED_MESSAGE,
    PROCESSING_TIMEOUT_MESSAGE,
    PROCESSING_RESOURCE_MESSAGE,
    "OCR page rendering exceeded its time limit. Try a simpler PDF.",
    "OCR page rendering exceeded its image size limit.",
    "OCR could not run because Poppler was not found. "
    "Install Poppler or set PDF_POPPLER_PATH, then retry this file.",
    "OCR could not run because Tesseract was not found. "
    "Install Tesseract or set TESSERACT_CMD, then retry this file.",
    "OCR could not read this page. Check that the PDF is readable, then retry this file.",
    "The PDF page dimensions exceed the supported limit.",
    "The uploaded file could not be opened as a PDF.",
    "No readable text was found in this PDF.",
})


class SafeProcessingError(RuntimeError):
    """A processing failure whose fixed message is intended for the user."""


def public_error_message(error: BaseException | str | None) -> str | None:
    """Only return approved text, including for legacy database error strings."""
    if error is None:
        return None
    if isinstance(error, MemoryError):
        return PROCESSING_RESOURCE_MESSAGE
    message = str(error)
    return message if message in SAFE_ERROR_MESSAGES else PROCESSING_FAILED_MESSAGE


def log_processing_failure(job_id: str, error: BaseException) -> None:
    # Exception messages, source lines and locals can contain provider response
    # bodies, API keys or document text. Keep only type and stack locations.
    frames = [
        f"{frame.filename}:{frame.lineno} in {frame.name}"
        for frame in traceback.extract_tb(error.__traceback__)
    ]
    logging.getLogger(__name__).error(
        "Processing job %s failed (%s); stack=%s", job_id, type(error).__name__, frames
    )
