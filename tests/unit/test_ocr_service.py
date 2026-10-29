import io
import sys

import pytest
from PIL import Image

from krmanfi_search.infrastructure.ocr import service
from krmanfi_search.infrastructure.ocr.preprocessing import PreprocessOptions, png_bytes
from krmanfi_search.infrastructure.ocr.service import (
    OcrResult,
    OcrService,
    _good_enough,
    _score,
    build_ocr_callable,
    is_blank,
    word_boxes,
)
from krmanfi_search.infrastructure.ocr.tesseract import OcrWord
from krmanfi_search.infrastructure.search.matchers import SubstringMatcher
from krmanfi_search.shared.exceptions import DependencyMissingError
from tests.conftest import needs_tesseract
from tests.helpers import cyrillic_font, ruled_page, text_image

LONG_TEXT = "это достаточно длинный распознанный текст страницы документа"


class FakeEngine:
    def __init__(self, results=None, words=None, available=True, languages=("rus", "eng")):
        self._results = list(results or [(LONG_TEXT, 90.0)])
        self._words = words or []
        self._available = available
        self._languages = frozenset(languages)
        self.calls = 0

    def available(self):
        return self._available

    def installed_languages(self):
        return self._languages

    def recognize(self, image, languages):
        index = min(self.calls, len(self._results) - 1)
        self.calls += 1
        return self._results[index]

    def words(self, image, languages):
        return self._words


def page_png():
    buffer = io.BytesIO()
    ruled_page(600, 800).convert("RGB").save(buffer, "PNG")
    return buffer.getvalue()


def word(text, left, line=(1, 1, 1), top=10):
    return OcrWord(text, left, top, 50, 20, line)


@pytest.mark.parametrize(
    ("text", "confidence", "expected"),
    [
        ("", 99.0, False),
        ("!!! ???", 99.0, False),
        (LONG_TEXT, 59.9, False),
        (LONG_TEXT, 60.0, True),
        ("коротко", 84.9, False),
        ("коротко", 85.0, True),
        ("a" * 39, 70.0, False),
        ("a" * 40, 70.0, True),
    ],
)
def test_good_enough_thresholds(text, confidence, expected):
    assert _good_enough(text, confidence) is expected


def test_score_grows_with_confidence_and_letters():
    assert _score("abc", 50.0) == 150.0
    assert _score("abc def", 50.0) > _score("abc", 50.0)
    assert _score("abc", 90.0) > _score("abc", 50.0)
    assert _score("!!!", 99.0) == 0.0


def test_is_blank_detects_white_page():
    options = PreprocessOptions()
    assert is_blank(Image.new("L", (400, 400), 255), options)


def test_is_blank_false_for_ink():
    options = PreprocessOptions()
    assert not is_blank(ruled_page(400, 400), options)


def test_is_blank_never_true_without_binarization():
    assert not is_blank(Image.new("L", (400, 400), 255), PreprocessOptions(binarization="none"))


def test_status_text_unavailable_linux(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    text = OcrService(["rus"], FakeEngine(available=False)).status_text()
    assert "Tesseract не найден" in text and "apt install" in text


def test_status_text_unavailable_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    text = OcrService(["rus"], FakeEngine(available=False)).status_text()
    assert "winget install" in text


def test_status_text_lists_missing_languages():
    text = OcrService(["rus", "deu", "fra"], FakeEngine(languages=("rus",))).status_text()
    assert "deu, fra" in text and "rus" not in text.split(":")[-1].replace("deu, fra", "")


def test_status_text_is_none_when_everything_is_present():
    assert OcrService(["rus", "eng"], FakeEngine()).status_text() is None


def test_available_follows_engine():
    assert OcrService(["rus"], FakeEngine()).available()
    assert not OcrService(["rus"], FakeEngine(available=False)).available()


def test_recognize_without_engine_raises():
    with pytest.raises(DependencyMissingError):
        OcrService(["rus"], FakeEngine(available=False)).recognize(page_png())


def test_blank_page_is_not_sent_to_engine():
    engine = FakeEngine()
    white = io.BytesIO()
    Image.new("RGB", (600, 800), "white").save(white, "PNG")
    result = OcrService(["rus"], engine).recognize(white.getvalue())
    assert result == OcrResult("", 0.0) and engine.calls == 0


def test_confident_first_pass_is_accepted_at_once():
    engine = FakeEngine([(LONG_TEXT, 92.0)])
    result = OcrService(["rus"], engine).recognize(page_png())
    assert result.text == LONG_TEXT and result.rotation == 0 and engine.calls == 1
    assert result.confidence == 92.0


def test_low_confidence_triggers_rotation_search(monkeypatch):
    monkeypatch.setattr(service, "detect_orientation", lambda image: 90)
    engine = FakeEngine([("мусор", 20.0), (LONG_TEXT, 91.0)])
    result = OcrService(["rus"], engine).recognize(page_png())
    assert result.rotation == 90 and result.text == LONG_TEXT and engine.calls == 2


def test_rotation_order_starts_with_detected_angle(monkeypatch):
    monkeypatch.setattr(service, "detect_orientation", lambda image: 270)
    engine = FakeEngine([("x", 10.0), ("y", 10.0), (LONG_TEXT, 90.0)])
    result = OcrService(["rus"], engine).recognize(page_png())
    assert result.rotation == 90 and engine.calls == 3


def test_best_effort_result_is_returned_when_nothing_is_good(monkeypatch):
    monkeypatch.setattr(service, "detect_orientation", lambda image: 0)
    engine = FakeEngine([("слабый результат", 30.0), ("совсем плохо", 5.0)])
    result = OcrService(["rus"], engine).recognize(page_png())
    assert result.text == "слабый результат" and result.rotation == 0
    assert engine.calls == 1 + 3 + 2


def test_mid_confidence_skips_rotation_but_tries_other_binarizations(monkeypatch):
    called = []
    monkeypatch.setattr(service, "detect_orientation", lambda image: called.append(1) or 0)
    engine = FakeEngine([("короткий", 70.0), (LONG_TEXT, 88.0)])
    result = OcrService(["rus"], engine).recognize(page_png())
    assert called == [] and result.text == LONG_TEXT and engine.calls == 2


def test_as_callable_returns_plain_text():
    run = OcrService(["rus"], FakeEngine([(LONG_TEXT, 95.0)])).as_callable()
    assert run(page_png()) == LONG_TEXT


def test_word_boxes_single_line_match_spans_both_words():
    words = [word("Квартальный", 10), word("отчет", 80), word("за", 140)]
    boxes = word_boxes(words, SubstringMatcher("квартальный отчёт", False))
    assert boxes == [(10, 10, 130, 30)]


def test_word_boxes_match_across_lines_gives_box_per_line():
    words = [word("квартальный", 10, line=(1, 1, 1)), word("отчёт", 12, line=(1, 1, 2), top=60)]
    matcher = SubstringMatcher("квартальный\nотчёт", False)
    boxes = word_boxes(words, matcher)
    assert boxes == [(10, 10, 60, 30), (12, 60, 62, 80)]


def test_word_boxes_regex_matcher_and_multiple_hits():
    from krmanfi_search.infrastructure.search.matchers import RegexMatcher

    words = [word("4711-К", 0), word("и", 60), word("4712-К", 100)]
    boxes = word_boxes(words, RegexMatcher(r"\d{4}-К", False))
    assert boxes == [(0, 10, 50, 30), (100, 10, 150, 30)]


def test_word_boxes_without_match_or_words():
    assert word_boxes([word("текст", 0)], SubstringMatcher("нет", False)) == []
    assert word_boxes([], SubstringMatcher("нет", False)) == []


def test_word_boxes_partial_word_match_marks_whole_word():
    boxes = word_boxes([word("отчётность", 5)], SubstringMatcher("отчёт", False))
    assert boxes == [(5, 10, 55, 30)]


def test_locate_returns_colour_page_and_boxes():
    words = [word("слово", 100, top=100)]
    engine = FakeEngine([(LONG_TEXT, 95.0)], words=words)
    gray = png_bytes(ruled_page(600, 800))
    colour = page_png()
    matcher = SubstringMatcher("слово", False)
    image, boxes = OcrService(["rus"], engine).locate(gray, colour, matcher)
    assert image.mode == "RGB" and image.width >= 600
    assert boxes == [(100, 100, 150, 120)]


def test_locate_without_engine_raises():
    with pytest.raises(DependencyMissingError):
        OcrService(["rus"], FakeEngine(available=False)).locate(
            page_png(), page_png(), SubstringMatcher("a", False)
        )


def test_build_ocr_callable_is_none_without_tesseract(monkeypatch):
    from krmanfi_search.infrastructure.ocr import tesseract

    monkeypatch.setattr(tesseract, "find_tesseract", lambda explicit=None: None)
    assert build_ocr_callable(("rus",), None) is None


@needs_tesseract
def test_build_ocr_callable_reads_real_text():
    run = build_ocr_callable(("eng",), None)
    _, data = text_image("Hello World", size=80)
    text = run(data)
    assert "Hello" in text and "World" in text


@needs_tesseract
def test_real_engine_end_to_end_on_cyrillic():
    from krmanfi_search.infrastructure.ocr.tesseract import TesseractEngine

    if "rus" not in TesseractEngine.installed_languages():
        pytest.skip("нет языка rus")
    if cyrillic_font(90) is None:
        pytest.skip("нет шрифта с кириллицей")
    ocr = OcrService(["rus", "eng"], TesseractEngine())
    _, data = text_image("Квартальный отчёт", size=90)
    assert "артальный" in ocr.recognize(data).text
