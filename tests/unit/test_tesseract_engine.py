import pytest

from krmanfi_search.infrastructure.ocr import tesseract
from krmanfi_search.infrastructure.ocr.tesseract import OcrWord, TesseractEngine, find_tesseract
from krmanfi_search.shared import runtime
from krmanfi_search.shared.exceptions import DependencyMissingError
from tests.conftest import needs_tesseract
from tests.helpers import text_image


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    runtime.vendor_tesseract.cache_clear()
    runtime.vendor_tessdata.cache_clear()
    monkeypatch.setenv("KRMANFI_VENDOR_DIR", str(tmp_path / "no_vendor"))
    monkeypatch.delenv("TESSERACT_CMD", raising=False)
    monkeypatch.setattr(tesseract, "which", lambda binary: None)
    monkeypatch.setattr(tesseract, "vendor_tesseract", lambda: None)
    yield
    runtime.vendor_tesseract.cache_clear()
    runtime.vendor_tessdata.cache_clear()


def fake_binary(folder, name="tesseract"):
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text("", encoding="utf-8")
    return path


def test_nothing_found_gives_none():
    assert find_tesseract() is None


def test_explicit_path_is_used(tmp_path):
    binary = fake_binary(tmp_path / "x")
    assert find_tesseract(str(binary)) == str(binary)


def test_explicit_path_that_does_not_exist_is_ignored(tmp_path):
    assert find_tesseract(str(tmp_path / "нет")) is None


def test_environment_variable_is_used(monkeypatch, tmp_path):
    binary = fake_binary(tmp_path / "env")
    monkeypatch.setenv("TESSERACT_CMD", str(binary))
    assert find_tesseract() == str(binary)


def test_explicit_beats_environment(monkeypatch, tmp_path):
    explicit = fake_binary(tmp_path / "explicit")
    monkeypatch.setenv("TESSERACT_CMD", str(fake_binary(tmp_path / "env")))
    assert find_tesseract(str(explicit)) == str(explicit)


def test_vendor_beats_explicit_and_environment(monkeypatch, tmp_path):
    vendor = fake_binary(tmp_path / "vendor")
    monkeypatch.setattr(tesseract, "vendor_tesseract", lambda: vendor)
    monkeypatch.setenv("TESSERACT_CMD", str(fake_binary(tmp_path / "env")))
    assert find_tesseract(str(fake_binary(tmp_path / "explicit"))) == str(vendor)


def test_path_lookup_is_the_last_resort(monkeypatch, tmp_path):
    binary = fake_binary(tmp_path / "bin")
    monkeypatch.setattr(tesseract, "which", lambda name: str(binary))
    assert find_tesseract() == str(binary)


def test_windows_standard_folders_are_checked(monkeypatch, tmp_path):
    binary = fake_binary(tmp_path / "Tesseract-OCR", "tesseract.exe")
    monkeypatch.setattr(tesseract.sys, "platform", "win32")
    monkeypatch.setenv("PROGRAMFILES", str(tmp_path))
    monkeypatch.delenv("PROGRAMFILES(X86)", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    assert find_tesseract() == str(binary)


def test_engine_unavailable_without_pytesseract(monkeypatch):
    monkeypatch.setattr(tesseract, "optional_import", lambda name: None)
    engine = TesseractEngine()
    assert not engine.available()
    assert TesseractEngine.installed_languages.__wrapped__() == frozenset()


def test_engine_recognize_requires_pytesseract(monkeypatch):
    monkeypatch.setattr(tesseract, "optional_import", lambda name: None)
    with pytest.raises(DependencyMissingError):
        TesseractEngine().recognize(b"", ["eng"])
    with pytest.raises(DependencyMissingError):
        TesseractEngine().words(b"", ["eng"])


def test_engine_unavailable_when_binary_not_found():
    engine = TesseractEngine()
    assert not engine.available() and engine.executable is None


def test_engine_configures_environment_for_child_process(monkeypatch, tmp_path):
    import pytesseract

    binary = fake_binary(tmp_path / "bin")
    tessdata = tmp_path / "tessdata"
    tessdata.mkdir()
    monkeypatch.setattr(tesseract, "vendor_tessdata", lambda: tessdata)
    monkeypatch.setattr(pytesseract.pytesseract, "tesseract_cmd", "tesseract")
    monkeypatch.setattr(pytesseract.pytesseract, "environ", {}, raising=False)
    engine = TesseractEngine(str(binary))
    assert engine.available()
    assert pytesseract.pytesseract.tesseract_cmd == str(binary)
    env = pytesseract.pytesseract.environ
    assert env["TESSDATA_PREFIX"] == str(tessdata) and env["OMP_THREAD_LIMIT"] == "1"


def test_ocr_word_is_a_frozen_value():
    item = OcrWord("текст", 1, 2, 3, 4, (1, 1, 1))
    with pytest.raises(AttributeError):
        item.text = "другое"


@needs_tesseract
def test_real_engine_reads_latin_text_with_confidence(monkeypatch):
    monkeypatch.undo()
    engine = TesseractEngine()
    assert engine.available()
    assert "eng" in TesseractEngine.installed_languages()
    _, data = text_image("Hello World", size=80)
    text, confidence = engine.recognize(data, ["eng"])
    assert "Hello" in text and 0 < confidence <= 100


@needs_tesseract
def test_real_engine_words_have_positions_inside_the_image(monkeypatch):
    monkeypatch.undo()
    engine = TesseractEngine()
    image, data = text_image("Hello World", size=80)
    words = engine.words(data, ["eng"])
    assert {w.text for w in words} >= {"Hello", "World"}
    for item in words:
        assert 0 <= item.left < image.width and 0 <= item.top < image.height
        assert item.width > 0 and item.height > 0
    hello = next(w for w in words if w.text == "Hello")
    world = next(w for w in words if w.text == "World")
    assert hello.left < world.left and hello.line == world.line


@needs_tesseract
def test_unknown_language_falls_back_to_english(monkeypatch):
    monkeypatch.undo()
    engine = TesseractEngine()
    _, data = text_image("Hello", size=80)
    text, _ = engine.recognize(data, ["zzz"])
    assert "Hello" in text
