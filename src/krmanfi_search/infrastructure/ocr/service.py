"""Распознавание страницы: предобработка, пустые страницы, поворот, запасные варианты."""

from __future__ import annotations

import io
import sys
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from PIL import Image

from krmanfi_search.infrastructure.ocr.preprocessing import (
    PreprocessOptions,
    detect_orientation,
    png_bytes,
    preprocess,
)
from krmanfi_search.infrastructure.ocr.tesseract import TesseractEngine
from krmanfi_search.shared.exceptions import DependencyMissingError
from krmanfi_search.shared.logging import get_logger

log = get_logger(__name__)

BLANK_INK_RATIO = 0.0015
MIN_TRUSTED_LETTERS = 40
HIGH_CONFIDENCE = 85.0
MIN_CONFIDENCE = 60.0
BINARIZATIONS = ("auto", "sauvola", "none")


@dataclass(frozen=True, slots=True)
class OcrResult:
    """Итог распознавания одной страницы."""

    text: str
    confidence: float
    rotation: int = 0


def _score(text: str, confidence: float):
    """Оценка результата: уверенность, умноженная на объём текста."""
    return confidence * sum(ch.isalnum() for ch in text)


def _good_enough(text: str, confidence: float):
    """Можно ли принять результат без дополнительных попыток."""
    letters = sum(ch.isalnum() for ch in text)
    if confidence < MIN_CONFIDENCE or letters == 0:
        return False
    return letters >= MIN_TRUSTED_LETTERS or confidence >= HIGH_CONFIDENCE


def is_blank(processed: Image.Image, options: PreprocessOptions):
    """Почти без «чернил» после бинаризации: пустую страницу не распознают."""
    if options.binarization == "none":
        return False
    return float((np.asarray(processed) < 128).mean()) < BLANK_INK_RATIO


class OcrService:
    """Распознаёт изображение страницы лучшим из нескольких вариантов предобработки."""

    def __init__(self, languages: Sequence[str], engine: TesseractEngine):
        """Создать сервис.

        Args:
            languages: Коды языков Tesseract, например ``["rus", "eng"]``.
            engine: Движок распознавания.
        """
        self._languages = list(languages)
        self._engine = engine

    def available(self):
        """Можно ли распознавать на этом компьютере."""
        return self._engine.available()

    def status_text(self):
        """Предупреждение для пользователя, если OCR недоступен или неполон."""
        if not self.available():
            hint = (
                "установите Tesseract (winget install UB-Mannheim.TesseractOCR)"
                if sys.platform == "win32"
                else "sudo apt install tesseract-ocr tesseract-ocr-rus"
            )
            return (
                "Tesseract не найден: обычные документы ищутся, сканы PDF не будут "
                f"распознаны — {hint}"
            )
        missing = [x for x in self._languages if x not in self._engine.installed_languages()]
        if missing:
            return f"В Tesseract нет языков: {', '.join(missing)} — качество распознавания ниже"
        return None

    def _variants(self):
        """Варианты предобработки: сначала основной, затем запасные."""
        return [
            PreprocessOptions(binarization=mode, upscale_min_side=1000) for mode in BINARIZATIONS
        ]

    def _attempt(
        self,
        image: Image.Image,
        rotation: int,
        options: PreprocessOptions,
        first: Image.Image | None,
    ):
        """Один проход: поворот, предобработка, распознавание."""
        if first is not None:
            processed = first.rotate(-rotation, expand=True) if rotation else first
        else:
            turned = image.rotate(-rotation, expand=True) if rotation else image
            processed, _ = preprocess(turned, options)
        text, confidence = self._engine.recognize(png_bytes(processed), self._languages)
        return OcrResult(text, round(confidence, 2), rotation)

    def recognize(self, image: bytes):
        """Распознать изображение страницы.

        Raises:
            DependencyMissingError: Если Tesseract недоступен.
        """
        if not self._engine.available():
            raise DependencyMissingError("tesseract")
        picture = Image.open(io.BytesIO(image)).convert("RGB")
        variants = self._variants()
        first, _ = preprocess(picture, variants[0])
        if is_blank(first, variants[0]):
            return OcrResult("", 0.0)
        best = self._attempt(picture, 0, variants[0], first)
        if _good_enough(best.text, best.confidence):
            return best
        if best.confidence < MIN_CONFIDENCE:
            detected = detect_orientation(first)
            order = [detected] + [r for r in (90, 270, 180) if r != detected]
            for turn in (r for r in order if r != 0):
                result = self._attempt(picture, turn, variants[0], first)
                if _score(result.text, result.confidence) > _score(best.text, best.confidence):
                    best = result
                if _good_enough(result.text, result.confidence):
                    return result
        for options in variants[1:]:
            result = self._attempt(picture, best.rotation, options, None)
            if _score(result.text, result.confidence) > _score(best.text, best.confidence):
                best = result
            if _good_enough(result.text, result.confidence):
                break
        return best

    def as_callable(self):
        """Адаптер «изображение → текст» для извлекателя PDF."""

        def run(image: bytes):
            """Распознать и вернуть только текст."""
            return self.recognize(image).text

        return run


def build_ocr_callable(languages: tuple[str, ...], tesseract_cmd: str | None):
    """Фабрика для рабочих процессов: возвращает функцию распознавания или ``None``.

    Args:
        languages: Коды языков Tesseract.
        tesseract_cmd: Явный путь к программе или ``None``.
    """
    service = OcrService(languages, TesseractEngine(tesseract_cmd))
    if not service.available():
        log.warning("ocr.unavailable")
        return None
    return service.as_callable()
