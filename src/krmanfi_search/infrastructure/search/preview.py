"""Картинка страницы PDF с рамками вокруг найденных фрагментов."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from krmanfi_search.infrastructure.ocr.preprocessing import png_bytes
from krmanfi_search.infrastructure.ocr.service import OcrService
from krmanfi_search.infrastructure.search.extractors import page_zoom
from krmanfi_search.shared.optional import require

TEXT_ZOOM = 2.0
MAX_SIDE_PIXELS = 3200
MAX_TERMS = 50
NOT_MARKED = "Не удалось найти фрагмент на картинке страницы — показана страница без выделения."
NO_OCR = "Tesseract не найден: показана страница без выделения."

type Box = tuple[int, int, int, int]


@dataclass(frozen=True, slots=True)
class PagePreview:
    """Страница в PNG и рамки совпадений в пикселях этой картинки."""

    png: bytes
    width: int
    height: int
    boxes: tuple[Box, ...]
    note: str = ""


def _unique_boxes(boxes: Sequence[Box]):
    """Убрать повторяющиеся рамки, сохранив порядок."""
    seen = set()
    result = []
    for box in boxes:
        key = tuple(round(value / 3) for value in box)
        if key not in seen:
            seen.add(key)
            result.append(box)
    return result


def _terms(fragments: Sequence[str]):
    """Различные фрагменты (без учёта регистра и переносов строк), не более ``MAX_TERMS``."""
    unique = {}
    for fragment in fragments:
        term = " ".join(fragment.split())
        if term:
            unique.setdefault(term.lower(), term)
    return list(unique.values())[:MAX_TERMS]


def _text_layer(page: object, fragments: Sequence[str], note: str):
    """Страница с текстовым слоем: рамки берутся из поиска по слою."""
    pymupdf = require("pymupdf")
    longest = max(page.rect.width, page.rect.height) or 1.0
    zoom = min(TEXT_ZOOM, MAX_SIDE_PIXELS / longest)
    matrix = pymupdf.Matrix(zoom, zoom)
    pixmap = page.get_pixmap(matrix=matrix, colorspace=pymupdf.csRGB, alpha=False)
    boxes = []
    for term in _terms(fragments):
        for rect in page.search_for(term):
            boxes.append(
                (int(rect.x0 * zoom), int(rect.y0 * zoom), int(rect.x1 * zoom), int(rect.y1 * zoom))
            )
    boxes = _unique_boxes(boxes)
    shown_note = note or ("" if boxes else NOT_MARKED)
    return PagePreview(
        bytes(pixmap.tobytes("png")), pixmap.width, pixmap.height, tuple(boxes), shown_note
    )


def _scanned(page: object, matcher: object, ocr: OcrService, dpi: int):
    """Скан: страница распознаётся заново, рамки берутся из координат слов Tesseract."""
    pymupdf = require("pymupdf")
    zoom = page_zoom(page, dpi)
    matrix = pymupdf.Matrix(zoom, zoom)
    gray = bytes(page.get_pixmap(matrix=matrix, colorspace=pymupdf.csGRAY).tobytes("pgm"))
    colour = bytes(
        page.get_pixmap(matrix=matrix, colorspace=pymupdf.csRGB, alpha=False).tobytes("png")
    )
    image, boxes = ocr.locate(gray, colour, matcher)
    unique = _unique_boxes(boxes)
    return PagePreview(
        png_bytes(image), image.width, image.height, tuple(unique), "" if unique else NOT_MARKED
    )


def build_preview(
    pdf: Path,
    page_number: int,
    fragments: Sequence[str],
    matcher: object,
    ocr: OcrService,
    dpi: int,
    scanned: bool,
):
    """Нарисовать страницу PDF и найти на ней все совпадения.

    Args:
        pdf: Путь к PDF-файлу.
        page_number: Номер страницы с единицы.
        fragments: Найденные на этой странице фрагменты (для страниц с текстовым слоем).
        matcher: Стратегия сопоставления (для сканов: ищет по распознанному тексту).
        ocr: Сервис распознавания.
        dpi: Разрешение отрисовки скана.
        scanned: Страница распознавалась через OCR.

    Raises:
        ValueError: Если PDF зашифрован или в нём нет такой страницы.
    """
    pymupdf = require("pymupdf")
    with pymupdf.open(str(pdf)) as document:
        if document.needs_pass:
            raise ValueError("PDF зашифрован паролем")
        if not 1 <= page_number <= document.page_count:
            raise ValueError(f"В файле нет страницы {page_number}")
        page = document[page_number - 1]
        if scanned and ocr.available():
            return _scanned(page, matcher, ocr, dpi)
        return _text_layer(page, fragments, NO_OCR if scanned else "")
