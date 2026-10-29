import io

import pytest
from PIL import Image

from krmanfi_search.container import Container
from krmanfi_search.domain import SearchMode, SearchQuery
from krmanfi_search.infrastructure.config import Settings
from krmanfi_search.infrastructure.search import preview
from krmanfi_search.infrastructure.search.matchers import make_matcher
from krmanfi_search.infrastructure.search.preview import (
    MAX_TERMS,
    NO_OCR,
    NOT_MARKED,
    PagePreview,
    _terms,
    _unique_boxes,
    build_preview,
)
from tests.conftest import PHRASE, needs_tesseract
from tests.helpers import make_text_pdf


class OcrOff:
    def available(self):
        return False


def matcher_for(text, tmp_path, **options):
    return make_matcher(SearchQuery(text=text, root=tmp_path, **options))


def decode(preview_):
    return Image.open(io.BytesIO(preview_.png))


def test_terms_are_deduplicated_ignoring_case_and_whitespace():
    terms = _terms(["Слово  одно", "слово одно", "слово\nодно", "Другое"])
    assert terms == ["Слово одно", "Другое"]


def test_terms_drop_empty_fragments():
    assert _terms(["", "   ", "\n"]) == []


def test_terms_are_capped():
    assert len(_terms([f"слово{n}" for n in range(MAX_TERMS + 30)])) == MAX_TERMS


def test_unique_boxes_merges_near_duplicates_and_keeps_order():
    boxes = [(0, 0, 10, 10), (1, 1, 10, 10), (50, 50, 90, 70), (0, 0, 10, 10)]
    assert _unique_boxes(boxes) == [(0, 0, 10, 10), (50, 50, 90, 70)]


def test_unique_boxes_keeps_distinct_boxes():
    boxes = [(0, 0, 10, 10), (0, 20, 10, 30)]
    assert _unique_boxes(boxes) == boxes


def test_text_layer_boxes_are_found_and_inside_the_image(tmp_path):
    pdf = make_text_pdf(tmp_path / "t.pdf", ["alpha beta gamma", "second beta page"])
    result = build_preview(pdf, 1, ["beta"], matcher_for("beta", tmp_path), OcrOff(), 300, False)
    assert len(result.boxes) == 1 and result.note == ""
    image = decode(result)
    assert (image.width, image.height) == (result.width, result.height)
    x0, y0, x1, y1 = result.boxes[0]
    assert 0 <= x0 < x1 <= result.width and 0 <= y0 < y1 <= result.height


def test_every_occurrence_on_the_page_is_marked(tmp_path):
    pdf = make_text_pdf(tmp_path / "t.pdf", ["beta one beta two beta three"])
    result = build_preview(pdf, 1, ["beta"], matcher_for("beta", tmp_path), OcrOff(), 300, False)
    assert len(result.boxes) == 3


def test_missing_fragment_gives_hint_instead_of_boxes(tmp_path):
    pdf = make_text_pdf(tmp_path / "t.pdf", ["alpha"])
    result = build_preview(pdf, 1, ["zzz"], matcher_for("zzz", tmp_path), OcrOff(), 300, False)
    assert result.boxes == () and result.note == NOT_MARKED


def test_page_is_chosen_by_number(tmp_path):
    pdf = make_text_pdf(tmp_path / "t.pdf", ["first only", "second only"])
    matcher = matcher_for("only", tmp_path)
    on_second = build_preview(pdf, 2, ["second only"], matcher, OcrOff(), 300, False)
    on_first = build_preview(pdf, 1, ["second only"], matcher, OcrOff(), 300, False)
    assert len(on_second.boxes) == 1 and on_first.boxes == ()


@pytest.mark.parametrize("number", [0, -1, 3, 99])
def test_page_out_of_range_is_a_value_error(tmp_path, number):
    pdf = make_text_pdf(tmp_path / "t.pdf", ["a", "b"])
    with pytest.raises(ValueError, match="нет страницы"):
        build_preview(pdf, number, ["a"], matcher_for("a", tmp_path), OcrOff(), 300, False)


def test_encrypted_pdf_is_refused(tmp_path):
    pdf = make_text_pdf(tmp_path / "e.pdf", ["secret"], password="pw")
    with pytest.raises(ValueError, match="зашифрован"):
        build_preview(pdf, 1, ["secret"], matcher_for("secret", tmp_path), OcrOff(), 300, False)


def test_not_a_pdf_raises(tmp_path):
    path = tmp_path / "fake.pdf"
    path.write_text("not a pdf", encoding="utf-8")
    with pytest.raises((RuntimeError, ValueError)):
        build_preview(path, 1, ["x"], matcher_for("x", tmp_path), OcrOff(), 300, False)


def test_scan_without_tesseract_shows_plain_page_with_note(tmp_path):
    pdf = make_text_pdf(tmp_path / "t.pdf", ["alpha"])
    result = build_preview(pdf, 1, ["alpha"], matcher_for("alpha", tmp_path), OcrOff(), 300, True)
    assert result.note == NO_OCR and decode(result).width > 0


def test_large_page_is_limited_in_pixels(tmp_path):
    import pymupdf

    document = pymupdf.open()
    page = document.new_page(width=6000, height=4000)
    page.insert_text((100, 200), "wide", fontsize=40)
    path = tmp_path / "wide.pdf"
    document.save(str(path))
    document.close()
    result = build_preview(path, 1, ["wide"], matcher_for("wide", tmp_path), OcrOff(), 300, False)
    assert max(result.width, result.height) <= preview.MAX_SIDE_PIXELS


def test_preview_value_object_is_immutable():
    result = PagePreview(b"", 1, 1, ())
    with pytest.raises(AttributeError):
        result.note = "x"


@needs_tesseract
def test_scanned_page_gets_boxes_from_ocr(demo):
    container = Container.build(Settings(workers=0))
    matcher = matcher_for(PHRASE, demo)
    result = build_preview(
        demo / "сканы" / "02_скан_книги.pdf", 2, [PHRASE], matcher, container.ocr, 300, True
    )
    assert result.boxes and result.note == ""
    image = decode(result)
    assert all(0 <= x0 < x1 <= image.width and 0 <= y0 < y1 <= image.height
               for x0, y0, x1, y1 in result.boxes)


@needs_tesseract
def test_rotated_scan_is_straightened_before_marking(demo):
    container = Container.build(Settings(workers=0))
    matcher = matcher_for(PHRASE, demo)
    result = build_preview(
        demo / "сканы" / "19_повёрнутый_скан.pdf", 1, [PHRASE], matcher, container.ocr, 300, True
    )
    assert result.boxes


@needs_tesseract
def test_regex_query_marks_scanned_words(demo):
    container = Container.build(Settings(workers=0))
    matcher = matcher_for(r"квартал\w+", demo, mode=SearchMode.REGEX)
    result = build_preview(
        demo / "сканы" / "02_скан_книги.pdf", 2, [PHRASE], matcher, container.ocr, 300, True
    )
    assert result.boxes


def test_text_layer_preview_of_demo_pdf(demo):
    result = build_preview(
        demo / "документы" / "01_текстовый_слой.pdf",
        2,
        [PHRASE],
        matcher_for(PHRASE, demo),
        OcrOff(),
        300,
        False,
    )
    assert result.boxes and decode(result).format == "PNG"
