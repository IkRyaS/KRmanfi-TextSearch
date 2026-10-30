"""Загрузка настроек из TOML с безопасными значениями по умолчанию."""

from __future__ import annotations

import tomllib
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from krmanfi_search.shared.runtime import settings_file


class OcrSettings(BaseModel):
    """Параметры распознавания."""

    languages: list[str] = Field(default_factory=lambda: ["rus", "eng"])
    tesseract_cmd: str | None = None
    pdf_dpi: int = Field(default=300, ge=72, le=600)


class Settings(BaseModel):
    """Все настройки приложения."""

    ocr: OcrSettings = Field(default_factory=OcrSettings)
    workers: int = Field(default=0, ge=0, le=64)
    context_chars: int = Field(default=60, ge=0, le=2000)
    max_file_size_mb: int = Field(default=200, ge=1)
    log_level: str = "INFO"
    load_error: str | None = Field(default=None, exclude=True)

    @classmethod
    def load(cls, path: Path | None = None):
        """Прочитать настройки; при любой ошибке вернуть значения по умолчанию.

        Args:
            path: Файл настроек (по умолчанию ``settings.toml`` рядом с программой
                или в папке данных пользователя).
        """
        target = path or settings_file()
        if not target.is_file():
            return cls()
        try:
            with target.open("rb") as handle:
                return cls.model_validate(tomllib.load(handle))
        except (OSError, tomllib.TOMLDecodeError, ValidationError) as exc:
            return cls(load_error=f"{target}: {exc}")
