from __future__ import annotations

import threading
from collections.abc import Callable

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]
type JsonDict = dict[str, JsonValue]

type ProgressCallback = Callable[[int, int, str], None]
"""``callback(done, total, message)``; ``total == 0`` означает неопределённый прогресс."""


class CancelToken:
    """Флаг мягкой отмены, общий для потока окна и рабочих потоков."""

    __slots__ = ("_event",)

    def __init__(self):
        """Создать токен без отмены."""
        self._event = threading.Event()

    def cancel(self):
        """Запросить отмену."""
        self._event.set()

    @property
    def cancelled(self):
        """Запрошена ли отмена."""
        return self._event.is_set()

    def raise_if_cancelled(self):
        """Выбросить :class:`OperationCancelledError`, если отмена запрошена.

        Raises:
            OperationCancelledError: Если был вызван :meth:`cancel`.
        """
        if self._event.is_set():
            from krmanfi_search.shared.exceptions import OperationCancelledError

            raise OperationCancelledError("cancelled")


def noop_progress(done: int, total: int, message: str):
    """Колбэк прогресса, который ничего не делает."""
    del done, total, message
