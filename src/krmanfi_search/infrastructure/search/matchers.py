from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from krmanfi_search.domain import SearchMode, SearchQuery
from krmanfi_search.shared.exceptions import SearchError


@dataclass(frozen=True, slots=True)
class Match:
    """Границы совпадения внутри текста."""

    start: int
    end: int


class Matcher(Protocol):
    """Интерфейс стратегии сопоставления."""

    def find(self, text: str):
        """Найти все совпадения в ``text``."""
        raise NotImplementedError


def fold(text: str):
    """Привести к нижнему регистру и считать «ё» равной «е», не меняя длину строки.

    ``str.lower`` превращает некоторые символы в два, что сдвигает позиции совпадений;
    Tesseract часто теряет точки над «ё», поэтому «отчёт» должен находить «отчет».
    """
    lowered = text.lower()
    if len(lowered) != len(text):
        lowered = "".join(ch.lower()[:1] or ch for ch in text)
    return lowered.replace("ё", "е")


class SubstringMatcher:
    """Подстрока без перекрытий; без учёта регистра «е» и «ё» считаются одной буквой."""

    def __init__(self, needle: str, case_sensitive: bool):
        """Подготовить искомую строку."""
        self._case = case_sensitive
        self._needle = needle if case_sensitive else fold(needle)

    def find(self, text: str):
        """Найти непересекающиеся вхождения."""
        haystack = text if self._case else fold(text)
        size = len(self._needle)
        result = []
        index = haystack.find(self._needle)
        while index != -1 and size:
            result.append(Match(index, index + size))
            index = haystack.find(self._needle, index + size)
        return result


class RegexMatcher:
    """Регулярное выражение Python (``re``) с флагом MULTILINE."""

    def __init__(self, pattern: str, case_sensitive: bool):
        """Скомпилировать выражение.

        Raises:
            SearchError: Если выражение некорректно.
        """
        flags = re.MULTILINE | (0 if case_sensitive else re.IGNORECASE)
        try:
            self._re = re.compile(pattern, flags)
        except re.error as exc:
            raise SearchError(f"Некорректное регулярное выражение: {exc}") from exc

    def find(self, text: str):
        """Все непустые совпадения."""
        return [Match(m.start(), m.end()) for m in self._re.finditer(text) if m.end() > m.start()]


def make_matcher(query: SearchQuery):
    """Создать стратегию по режиму запроса."""
    if query.mode is SearchMode.REGEX:
        return RegexMatcher(query.text, query.case_sensitive)
    return SubstringMatcher(query.text, query.case_sensitive)
