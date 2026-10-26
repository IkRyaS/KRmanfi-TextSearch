"""Сценарий SearchText: проверка запроса и запуск движка."""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Protocol

from krmanfi_search.domain import SearchHit, SearchQuery, SearchStats
from krmanfi_search.shared.exceptions import SearchError
from krmanfi_search.shared.types import CancelToken, ProgressCallback, noop_progress


class TextSearchPort(Protocol):
    """Движок поиска, который реализует инфраструктура."""

    def search(
        self,
        query: SearchQuery,
        *,
        progress: ProgressCallback,
        cancel: CancelToken,
        stats: SearchStats,
    ) -> Iterator[SearchHit]:
        """Выдавать совпадения по мере обработки файлов."""
        raise NotImplementedError


class SearchText:
    """Проверяет входные данные и делегирует поиск движку."""

    def __init__(self, engine: TextSearchPort):
        """Привязать движок.

        Args:
            engine: Реализация поиска.
        """
        self._engine = engine

    def __call__(
        self,
        query: SearchQuery,
        *,
        progress: ProgressCallback = noop_progress,
        cancel: CancelToken | None = None,
        stats: SearchStats | None = None,
    ):
        """Выполнить поиск.

        Args:
            query: Что и где искать.
            progress: Колбэк ``(сделано, всего, сообщение)``.
            cancel: Токен отмены.
            stats: Объект статистики, который будет заполнен.

        Raises:
            SearchError: Если текст пуст, папка недоступна или регулярное выражение неверно.
        """
        if not query.text.strip():
            raise SearchError("Введите текст для поиска")
        root = query.root
        if not root.exists():
            raise SearchError(f"Путь не существует: {root}")
        if not (root.is_file() or root.is_dir()):
            raise SearchError(f"Не файл и не папка: {root}")
        if not os.access(root, os.R_OK):
            raise SearchError(f"Нет доступа к {root}")
        return self._engine.search(
            query,
            progress=progress,
            cancel=cancel or CancelToken(),
            stats=stats if stats is not None else SearchStats(),
        )
