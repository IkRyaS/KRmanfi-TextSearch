"""Предметные сущности поиска: запрос, фрагмент текста, совпадение, статистика."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

_FROZEN = ConfigDict(frozen=True)
DEFAULT_MAX_FILE_SIZE = 200 * 1024 * 1024
MAX_STORED_PROBLEMS = 200


class SearchMode(StrEnum):
    """Способ сравнения."""

    SUBSTRING = "substring"
    REGEX = "regex"


class SearchQuery(BaseModel):
    """Параметры одного поиска."""

    model_config = _FROZEN

    text: str = Field(min_length=1)
    root: Path
    mode: SearchMode = SearchMode.SUBSTRING
    case_sensitive: bool = False
    context_chars: int = Field(default=60, ge=0, le=2000)
    include_archives: bool = True
    ocr_scanned_pdfs: bool = True
    max_file_size: int = Field(default=DEFAULT_MAX_FILE_SIZE, gt=0)


class TextChunk(BaseModel):
    """Кусок извлечённого текста с указанием места (страница, лист, слайд, строки)."""

    model_config = _FROZEN

    location: str
    page: int | None = None
    text: str


class SearchHit(BaseModel):
    """Одно вхождение искомого текста."""

    model_config = _FROZEN

    display_path: str
    real_path: Path
    location: str
    page: int | None = None
    fragment: str
    context: str
    match_count: int = Field(ge=1)
    occurrence: int = Field(default=1, ge=1)
    offset: int = 0


@dataclass
class SearchStats:
    """Статистика одного прогона; показывается пользователю по окончании."""

    files_total: int = 0
    scanned: int = 0
    with_text: int = 0
    without_text: int = 0
    failed: int = 0
    skipped: int = 0
    archives: int = 0
    hits: int = 0
    hit_files: int = 0
    ocr_available: bool = False
    no_text_files: list[str] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)
    skipped_files: list[str] = field(default_factory=list)

    def add_error(self, key: str, reason: str):
        """Записать ошибку файла (список ограничен по длине)."""
        self.failed += 1
        if len(self.errors) < MAX_STORED_PROBLEMS:
            self.errors.append((key, reason[:300]))

    def add_no_text(self, key: str):
        """Записать файл, из которого не удалось получить текст."""
        self.without_text += 1
        if len(self.no_text_files) < MAX_STORED_PROBLEMS:
            self.no_text_files.append(key)

    def add_skipped(self, key: str):
        """Записать файл, пропущенный из-за лимита размера."""
        self.skipped += 1
        if len(self.skipped_files) < MAX_STORED_PROBLEMS:
            self.skipped_files.append(key)

    def summary(self):
        """Итоговая строка для окна."""
        parts = [
            f"найдено {self.hits} фрагментов в {self.hit_files} файлах",
            f"просмотрено {self.scanned} файлов",
            f"без текста — {self.without_text}",
            f"ошибок — {self.failed}",
        ]
        if self.skipped:
            parts.append(f"пропущено (слишком большие) — {self.skipped}")
        return "; ".join(parts)
