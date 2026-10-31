from __future__ import annotations

import functools
from dataclasses import dataclass

from krmanfi_search.application import SearchText
from krmanfi_search.infrastructure.config import Settings
from krmanfi_search.infrastructure.ocr.service import OcrService, build_ocr_callable
from krmanfi_search.infrastructure.ocr.tesseract import TesseractEngine
from krmanfi_search.infrastructure.search.service import TextSearchService, default_workers


@dataclass(frozen=True, slots=True)
class Container:
    """Готовые сервисы приложения."""

    settings: Settings
    search_text: SearchText
    ocr: OcrService

    @classmethod
    def build(cls, settings: Settings | None = None):
        """Собрать сервисы по настройкам.

        Args:
            settings: Настройки (по умолчанию загружаются из файла).
        """
        settings = settings or Settings.load()
        languages = tuple(settings.ocr.languages)
        ocr = OcrService(languages, TesseractEngine(settings.ocr.tesseract_cmd))
        engine = TextSearchService(
            ocr_factory=functools.partial(
                build_ocr_callable, languages, settings.ocr.tesseract_cmd
            ),
            ocr_available=ocr.available,
            pdf_dpi=settings.ocr.pdf_dpi,
            workers=settings.workers or default_workers(),
        )
        return cls(settings=settings, search_text=SearchText(engine), ocr=ocr)
