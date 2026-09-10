import pytest
from pdf2image.exceptions import PDFInfoNotInstalledError, PDFPopplerTimeoutError
from PIL import Image
from pytesseract import TesseractNotFoundError

from app.config import Settings
from app.processing import ocr_pdf_page


def settings(**overrides):
    return Settings(_env_file=None, app_env="test", auth_mode="dev", **overrides)


def test_ocr_finds_user_install_without_path(tmp_path, monkeypatch):
    install = tmp_path / "Programs" / "Tesseract-OCR" / "tesseract.exe"
    install.parent.mkdir(parents=True)
    install.touch()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr("shutil.which", lambda command: None)
    monkeypatch.setattr(
        "app.processing.convert_from_bytes", lambda *args, **kwargs: [Image.new("L", (1, 1))]
    )
    seen = []

    def recognize(image, **kwargs):
        from app.processing import pytesseract
        seen.append(pytesseract.pytesseract.tesseract_cmd)
        return "Scanned final exam"

    monkeypatch.setattr("app.processing.pytesseract.image_to_string", recognize)
    assert ocr_pdf_page(b"pdf", 1, settings()) == "Scanned final exam"
    assert seen == [str(install)]


def test_ocr_explicit_binary_has_priority(monkeypatch):
    monkeypatch.setattr(
        "app.processing.convert_from_bytes", lambda *args, **kwargs: [Image.new("L", (1, 1))]
    )
    monkeypatch.setattr("shutil.which", lambda command: "/some/other/tesseract")
    seen = []

    def recognize(image, **kwargs):
        from app.processing import pytesseract
        seen.append(pytesseract.pytesseract.tesseract_cmd)
        return "Text"

    monkeypatch.setattr("app.processing.pytesseract.image_to_string", recognize)
    ocr_pdf_page(b"pdf", 1, settings(tesseract_cmd="/custom/tesseract"))
    assert seen == ["/custom/tesseract"]


def test_ocr_missing_tesseract_identifies_actual_dependency(monkeypatch):
    monkeypatch.setattr(
        "app.processing.convert_from_bytes", lambda *args, **kwargs: [Image.new("L", (1, 1))]
    )

    def missing(image, **kwargs):
        raise TesseractNotFoundError()

    monkeypatch.setattr("app.processing.pytesseract.image_to_string", missing)
    with pytest.raises(RuntimeError, match="Tesseract was not found") as error:
        ocr_pdf_page(b"pdf", 1, settings())
    assert "Poppler" not in str(error.value)


def test_ocr_missing_poppler_identifies_actual_dependency(monkeypatch):
    def missing(*args, **kwargs):
        raise PDFInfoNotInstalledError("pdfinfo unavailable")

    monkeypatch.setattr("app.processing.convert_from_bytes", missing)
    with pytest.raises(RuntimeError, match="Poppler was not found") as error:
        ocr_pdf_page(b"pdf", 1, settings())
    assert "Tesseract" not in str(error.value)


def test_ocr_missing_renderer_identifies_poppler(monkeypatch):
    def missing(*args, **kwargs):
        raise FileNotFoundError(2, "No such file", "pdftoppm.exe")

    monkeypatch.setattr("app.processing.convert_from_bytes", missing)
    with pytest.raises(RuntimeError, match="Poppler was not found"):
        ocr_pdf_page(b"pdf", 1, settings())


@pytest.mark.parametrize("recognition_fails", [False, True])
def test_ocr_bounds_subprocesses_and_closes_images(monkeypatch, recognition_fails):
    rendered = Image.new("L", (5, 5))
    limits = settings(pdf_render_timeout_seconds=12, ocr_timeout_seconds=8,
                      max_ocr_dimension_pixels=1000)

    def convert(*args, **kwargs):
        assert kwargs["timeout"] == 12
        assert kwargs["size"] == 1000
        assert kwargs["first_page"] == kwargs["last_page"] == 2
        return [rendered]

    def recognize(image, **kwargs):
        assert kwargs["timeout"] == 8
        if recognition_fails:
            raise RuntimeError("Tesseract process timeout")
        return "Text"

    monkeypatch.setattr("app.processing.convert_from_bytes", convert)
    monkeypatch.setattr("app.processing.pytesseract.image_to_string", recognize)
    if recognition_fails:
        with pytest.raises(RuntimeError, match="OCR"):
            ocr_pdf_page(b"pdf", 2, limits)
    else:
        assert ocr_pdf_page(b"pdf", 2, limits) == "Text"
    with pytest.raises(ValueError, match="closed image"):
        rendered.getpixel((0, 0))


def test_ocr_render_timeout_has_safe_message(monkeypatch):
    def convert(*args, **kwargs):
        raise PDFPopplerTimeoutError("secret internal path")

    monkeypatch.setattr("app.processing.convert_from_bytes", convert)
    with pytest.raises(RuntimeError, match="time limit") as error:
        ocr_pdf_page(b"pdf", 1, settings())
    assert "secret" not in str(error.value)


def test_oversized_renderer_output_is_closed_without_ocr(monkeypatch):
    rendered = Image.new("L", (1001, 1))
    monkeypatch.setattr("app.processing.convert_from_bytes", lambda *args, **kwargs: [rendered])

    def unexpected_recognition(*args, **kwargs):
        pytest.fail("Oversized image reached Tesseract")

    monkeypatch.setattr("app.processing.pytesseract.image_to_string", unexpected_recognition)
    with pytest.raises(RuntimeError, match="image size limit"):
        ocr_pdf_page(b"pdf", 1, settings(max_ocr_dimension_pixels=1000))
    with pytest.raises(ValueError, match="closed image"):
        rendered.getpixel((0, 0))
