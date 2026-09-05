import pytest
from pdf2image.exceptions import PDFInfoNotInstalledError
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
    monkeypatch.setattr("app.processing.convert_from_bytes", lambda *args, **kwargs: [object()])
    seen = []

    def recognize(image):
        from app.processing import pytesseract
        seen.append(pytesseract.pytesseract.tesseract_cmd)
        return "Scanned final exam"

    monkeypatch.setattr("app.processing.pytesseract.image_to_string", recognize)
    assert ocr_pdf_page(b"pdf", 1, settings()) == "Scanned final exam"
    assert seen == [str(install)]


def test_ocr_explicit_binary_has_priority(monkeypatch):
    monkeypatch.setattr("app.processing.convert_from_bytes", lambda *args, **kwargs: [object()])
    monkeypatch.setattr("shutil.which", lambda command: "/some/other/tesseract")
    seen = []

    def recognize(image):
        from app.processing import pytesseract
        seen.append(pytesseract.pytesseract.tesseract_cmd)
        return "Text"

    monkeypatch.setattr("app.processing.pytesseract.image_to_string", recognize)
    ocr_pdf_page(b"pdf", 1, settings(tesseract_cmd="/custom/tesseract"))
    assert seen == ["/custom/tesseract"]


def test_ocr_missing_tesseract_identifies_actual_dependency(monkeypatch):
    monkeypatch.setattr("app.processing.convert_from_bytes", lambda *args, **kwargs: [object()])

    def missing(image):
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
