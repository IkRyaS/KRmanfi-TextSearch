"""Извлечение текста по форматам: каждый кусок получает метку места."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from krmanfi_search.domain import TextChunk
from krmanfi_search.shared.optional import optional_import, require
from krmanfi_search.shared.types import CancelToken

if TYPE_CHECKING:
    import pymupdf

type ImageOcr = Callable[[bytes], str]

MAX_TEXT_FILE = 64 * 1024 * 1024
LINES_PER_CHUNK = 500
PARAGRAPHS_PER_CHUNK = 50
MIN_TEXT_LAYER_CHARS = 50
MAX_OCR_RENDER_PIXELS = 5000
TEXT_EXTENSIONS = frozenset({"txt", "md", "log", "csv"})
DOCUMENT_EXTENSIONS = frozenset({"pdf", "docx", "xlsx", "pptx"}) | TEXT_EXTENSIONS


def decode_text(raw: bytes):
    """Декодировать байты: BOM, UTF-8, затем CP1251, затем Latin-1."""
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16", "replace")
    for encoding in ("utf-8-sig", "cp1251"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def _batched(items: list[str], size: int, label: str):
    """Сгруппировать строки в куски по ``size`` с меткой диапазона."""
    chunks = []
    for start in range(0, len(items), size):
        text = "\n".join(items[start : start + size]).strip()
        if text:
            end = min(start + size, len(items))
            chunks.append(TextChunk(location=f"{label} {start + 1}–{end}", text=text))
    return chunks


def extract_plain(path: Path, cancel: CancelToken):
    """TXT, MD, LOG, CSV: куски по строкам."""
    del cancel
    with path.open("rb") as handle:
        text = decode_text(handle.read(MAX_TEXT_FILE))
    return _batched(text.splitlines(), LINES_PER_CHUNK, "строки")


def extract_docx(path: Path, cancel: CancelToken):
    """DOCX: абзацы, таблицы, колонтитулы."""
    del cancel
    document = require("docx").Document(str(path))
    paragraphs = [p.text for p in document.paragraphs if p.text.strip()]
    for table in document.tables:
        for row in table.rows:
            paragraphs.append("\t".join(cell.text for cell in row.cells))
    chunks = _batched(paragraphs, PARAGRAPHS_PER_CHUNK, "абзацы")
    extra = []
    for section in document.sections:
        for part in (section.header, section.footer):
            extra.extend(p.text for p in part.paragraphs if p.text.strip())
    if extra:
        chunks.append(TextChunk(location="колонтитулы", text="\n".join(extra)))
    return chunks


def extract_xlsx(path: Path, cancel: CancelToken):
    """XLSX: один кусок на лист (значения, не формулы)."""
    workbook = require("openpyxl").load_workbook(str(path), read_only=True, data_only=True)
    chunks = []
    try:
        for number, sheet in enumerate(workbook.worksheets, start=1):
            lines = []
            for row in sheet.iter_rows(values_only=True):
                cancel.raise_if_cancelled()
                cells = [str(v) for v in row if v is not None]
                if cells:
                    lines.append("\t".join(cells))
            if lines:
                chunks.append(
                    TextChunk(location=f"лист «{sheet.title}»", page=number, text="\n".join(lines))
                )
    finally:
        workbook.close()
    return chunks


def extract_pptx(path: Path, cancel: CancelToken):
    """PPTX: один кусок на слайд, включая заметки докладчика."""
    presentation = require("pptx").Presentation(str(path))
    chunks = []
    for number, slide in enumerate(presentation.slides, start=1):
        cancel.raise_if_cancelled()
        parts = [s.text_frame.text for s in slide.shapes if getattr(s, "has_text_frame", False)]
        for shape in slide.shapes:
            if getattr(shape, "has_table", False):
                parts.extend(c.text for r in shape.table.rows for c in r.cells)
        if slide.has_notes_slide:
            parts.append(slide.notes_slide.notes_text_frame.text)
        text = "\n".join(p for p in parts if p.strip())
        if text:
            chunks.append(TextChunk(location=f"слайд {number}", page=number, text=text))
    return chunks


def image_coverage(page: pymupdf.Page):
    """Доля площади страницы, занятая растровыми изображениями (0…1)."""
    pymupdf = require("pymupdf")
    area = page.rect.get_area() or 1.0
    covered = 0.0
    for info in page.get_image_info():
        box = pymupdf.Rect(info["bbox"]) & page.rect
        if not box.is_empty:
            covered += box.get_area()
    return min(covered / area, 1.0)


def page_needs_ocr(page: pymupdf.Page, text: str):
    """Нужна ли странице PDF распознавание.

    Есть изображение и либо в текстовом слое меньше 50 букв, либо изображение
    занимает не меньше половины страницы, а букв меньше 300.
    """
    letters = sum(ch.isalnum() for ch in text)
    coverage = image_coverage(page)
    if coverage <= 0:
        return False
    if letters < MIN_TEXT_LAYER_CHARS:
        return True
    return coverage >= 0.5 and letters < 6 * MIN_TEXT_LAYER_CHARS


def page_zoom(page: pymupdf.Page, dpi: int):
    """Масштаб отрисовки страницы для заданного разрешения (с ограничением по размеру)."""
    longest = max(page.rect.width, page.rect.height) or 1.0
    return min(dpi / 72.0, MAX_OCR_RENDER_PIXELS / longest)


def render_page_image(page: pymupdf.Page, dpi: int):
    """Отрисовать страницу в оттенках серого (PGM) для распознавания."""
    pymupdf = require("pymupdf")
    zoom = page_zoom(page, dpi)
    pixmap = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), colorspace=pymupdf.csGRAY)
    return bytes(pixmap.tobytes("pgm"))


def pdf_page_count(path: Path):
    """Число страниц PDF; 0, если файл не открывается или зашифрован."""
    pymupdf = optional_import("pymupdf")
    if pymupdf is None:
        return 0
    try:
        with pymupdf.open(str(path)) as document:
            return 0 if document.needs_pass else int(document.page_count)
    except Exception:
        return 0


class PdfExtractor:
    """PDF: текстовый слой, а сканы и фото страниц распознаются через OCR."""

    extensions = frozenset({"pdf"})

    def __init__(self, ocr: ImageOcr | None = None, dpi: int = 300):
        """Создать извлекатель.

        Args:
            ocr: Функция «PGM/PNG-байты → текст» или ``None`` (без OCR).
            dpi: Разрешение отрисовки страниц для OCR.
        """
        self._ocr = ocr
        self._dpi = dpi

    def extract(self, path: Path, cancel: CancelToken):
        """Извлечь все страницы."""
        return self.extract_pages(path, 0, None, cancel)

    def extract_pages(self, path: Path, start: int, stop: int | None, cancel: CancelToken):
        """Извлечь страницы ``start`` … ``stop - 1`` (с нуля; ``None`` — до конца).

        Raises:
            OperationCancelledError: Если поиск отменён.
        """
        pymupdf = require("pymupdf")
        chunks = []
        with pymupdf.open(str(path)) as document:
            if document.needs_pass:
                raise ValueError("PDF зашифрован паролем")
            end = document.page_count if stop is None else min(stop, document.page_count)
            for number in range(max(start, 0), end):
                cancel.raise_if_cancelled()
                page = document[number]
                text = page.get_text("text")
                label = f"стр. {number + 1}"
                if self._ocr is not None and page_needs_ocr(page, text):
                    recognised = self._ocr(render_page_image(page, self._dpi))
                    if recognised.strip():
                        text = f"{text.strip()}\n{recognised}" if text.strip() else recognised
                        label += " (OCR)"
                if text.strip():
                    chunks.append(TextChunk(location=label, page=number + 1, text=text))
        return chunks


class ExtractorRegistry:
    """Выбор стратегии извлечения по расширению файла."""

    def __init__(self, ocr: ImageOcr | None = None, pdf_dpi: int = 300):
        """Зарегистрировать стратегии.

        Args:
            ocr: Функция распознавания для PDF-сканов (``None`` — без OCR).
            pdf_dpi: Разрешение отрисовки страниц для OCR.
        """
        self._pdf = PdfExtractor(ocr, pdf_dpi)
        self._functions = {
            **dict.fromkeys(TEXT_EXTENSIONS, extract_plain),
            "docx": extract_docx,
            "xlsx": extract_xlsx,
            "pptx": extract_pptx,
        }

    def extract(
        self, path: Path, ext: str, cancel: CancelToken, pages: tuple[int, int | None] | None
    ):
        """Извлечь текст файла или диапазон страниц PDF.

        Args:
            path: Файл.
            ext: Расширение в нижнем регистре без точки.
            cancel: Токен отмены.
            pages: Диапазон страниц PDF ``(начало, конец)`` или ``None``.
        """
        if ext == "pdf":
            if pages is None:
                return self._pdf.extract(path, cancel)
            return self._pdf.extract_pages(path, pages[0], pages[1], cancel)
        function = self._functions.get(ext)
        return function(path, cancel) if function is not None else []
