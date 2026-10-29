"""Tesseract через pytesseract: поиск программы и распознавание изображения."""

from __future__ import annotations

import io
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import numpy as np
from PIL import Image

from krmanfi_search.shared.exceptions import DependencyMissingError
from krmanfi_search.shared.optional import optional_import, which
from krmanfi_search.shared.process import child_environment
from krmanfi_search.shared.runtime import vendor_tessdata, vendor_tesseract

WINDOWS_SUBDIRS = ("Tesseract-OCR", "Programs/Tesseract-OCR")
PSM_AUTO = "--psm 3"


@dataclass(frozen=True, slots=True)
class OcrWord:
    """Слово, распознанное на изображении, и его рамка в пикселях."""

    text: str
    left: int
    top: int
    width: int
    height: int
    line: tuple[int, int, int]


def find_tesseract(explicit: str | None = None):
    """Найти ``tesseract``: ``vendor``, явный путь, ``TESSERACT_CMD``, ``PATH``, папки Windows."""
    candidates = []
    bundled = vendor_tesseract()
    if bundled is not None:
        candidates.append(bundled)
    if explicit:
        candidates.append(Path(explicit).expanduser())
    if os.environ.get("TESSERACT_CMD"):
        candidates.append(Path(os.environ["TESSERACT_CMD"]))
    found = which("tesseract")
    if found:
        candidates.append(Path(found))
    if sys.platform == "win32":
        bases = [os.environ.get(v) for v in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")]
        for base in [b for b in bases if b]:
            candidates += [Path(base) / sub / "tesseract.exe" for sub in WINDOWS_SUBDIRS]
    return next((str(c) for c in candidates if c.is_file()), None)


class TesseractEngine:
    """Распознавание текста программой Tesseract (работает без интернета)."""

    name = "tesseract"

    def __init__(self, cmd: str | None = None):
        """Запомнить явно заданный путь к программе.

        Args:
            cmd: Путь к ``tesseract`` или ``None`` для автоматического поиска.
        """
        self._cmd = cmd
        self.executable = None

    def available(self):
        """Установлены ли pytesseract и сама программа."""
        pytesseract = optional_import("pytesseract")
        if pytesseract is None:
            return False
        if self.executable is None:
            self.executable = find_tesseract(self._cmd)
            if self.executable is not None:
                pytesseract.pytesseract.tesseract_cmd = self.executable
                extra = {"OMP_THREAD_LIMIT": os.environ.get("OMP_THREAD_LIMIT", "1")}
                tessdata = vendor_tessdata()
                if tessdata is not None:
                    extra["TESSDATA_PREFIX"] = str(tessdata)
                pytesseract.pytesseract.environ = child_environment(extra)
        return self.executable is not None

    @staticmethod
    @cache
    def installed_languages():
        """Языки, для которых есть файлы ``traineddata``."""
        pytesseract = optional_import("pytesseract")
        if pytesseract is None:
            return frozenset()
        try:
            return frozenset(pytesseract.get_languages(config=""))
        except Exception:
            return frozenset()

    def recognize(self, image: bytes, languages: Sequence[str]):
        """Распознать изображение; вернуть текст и среднюю уверенность 0–100.

        Raises:
            DependencyMissingError: Если pytesseract не установлен.
        """
        pytesseract = optional_import("pytesseract")
        if pytesseract is None:
            raise DependencyMissingError("pytesseract")
        installed = self.installed_languages()
        langs = [lang for lang in languages if lang in installed] or ["eng"]
        data = pytesseract.image_to_data(
            Image.open(io.BytesIO(image)).convert("RGB"),
            lang="+".join(langs),
            config=PSM_AUTO,
            output_type=pytesseract.Output.DICT,
            timeout=120,
        )
        lines = {}
        confidences = []
        for index, word in enumerate(data["text"]):
            confidence = float(data["conf"][index])
            if confidence < 0 or not str(word).strip():
                continue
            key = (data["block_num"][index], data["par_num"][index], data["line_num"][index])
            lines.setdefault(key, []).append(str(word))
            confidences.append(confidence)
        text = "\n".join(" ".join(words) for _, words in sorted(lines.items()))
        return text, float(np.mean(confidences)) if confidences else 0.0

    def words(self, image: bytes, languages: Sequence[str]):
        """Распознать изображение и вернуть слова с координатами в порядке чтения.

        Raises:
            DependencyMissingError: Если pytesseract не установлен.
        """
        pytesseract = optional_import("pytesseract")
        if pytesseract is None:
            raise DependencyMissingError("pytesseract")
        installed = self.installed_languages()
        langs = [lang for lang in languages if lang in installed] or ["eng"]
        data = pytesseract.image_to_data(
            Image.open(io.BytesIO(image)).convert("RGB"),
            lang="+".join(langs),
            config=PSM_AUTO,
            output_type=pytesseract.Output.DICT,
            timeout=120,
        )
        result = []
        for index, word in enumerate(data["text"]):
            if float(data["conf"][index]) < 0 or not str(word).strip():
                continue
            line = (data["block_num"][index], data["par_num"][index], data["line_num"][index])
            result.append(
                OcrWord(
                    text=str(word),
                    left=int(data["left"][index]),
                    top=int(data["top"][index]),
                    width=int(data["width"][index]),
                    height=int(data["height"][index]),
                    line=line,
                )
            )
        return result
