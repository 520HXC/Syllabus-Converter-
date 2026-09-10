import pymupdf
import pytest

from app.config import Settings
from app.processing import extract_pdf_pages


def settings(**overrides):
    return Settings(_env_file=None, app_env="test", auth_mode="dev", **overrides)


@pytest.mark.parametrize("crop_large_media", [False, True])
def test_oversized_pdf_page_is_rejected_before_text_extraction(monkeypatch, crop_large_media):
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=2000, height=792)
        page.insert_text((30, 30), "Readable embedded syllabus text")
        if crop_large_media:
            page.set_cropbox(pymupdf.Rect(0, 0, 612, 792))
        content = pdf.tobytes()

    def unexpected_extraction(*args, **kwargs):
        pytest.fail("Oversized page reached text extraction")

    monkeypatch.setattr(pymupdf.Page, "get_text", unexpected_extraction)
    with pytest.raises(ValueError, match="dimensions"):
        extract_pdf_pages(content, 5, settings=settings())


def test_regular_page_keeps_embedded_text():
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=612, height=792)
        page.insert_text((30, 30), "Readable embedded syllabus text")
        content = pdf.tobytes()

    pages, used_ocr = extract_pdf_pages(content, 5, settings=settings())
    assert not used_ocr
    assert pages == [{"page": 1, "text": "Readable embedded syllabus text", "ocr": False}]


def test_pdf_extraction_stops_at_cumulative_deadline(monkeypatch):
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=612, height=792)
        page.insert_text((30, 30), "Readable embedded syllabus text")
        content = pdf.tobytes()
    times = iter([0, 0, 21])
    monkeypatch.setattr("app.processing.monotonic", lambda: next(times))
    with pytest.raises(RuntimeError, match="time limit"):
        extract_pdf_pages(content, 5, settings=settings(processing_timeout_seconds=20))
