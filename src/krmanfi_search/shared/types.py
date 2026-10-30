"""Shared type aliases (PEP 695 ``type`` statements)."""

from __future__ import annotations

import threading
from collections.abc import Callable

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]
type JsonDict = dict[str, JsonValue]

type ProgressCallback = Callable[[int, int, str], None]
"""``callback(done, total, message)``; ``total == 0`` means indeterminate."""


class CancelToken:
    """Cooperative cancellation flag shared between UI and worker threads."""

    __slots__ = ("_event",)

    def __init__(self):
        """Create a non-cancelled token."""
        self._event = threading.Event()

    def cancel(self):
        """Request cancellation."""
        self._event.set()

    @property
    def cancelled(self):
        """Whether cancellation has been requested."""
        return self._event.is_set()

    def raise_if_cancelled(self):
        """Raise :class:`OperationCancelledError` when cancelled.

        Raises:
            OperationCancelledError: If :meth:`cancel` was called.
        """
        if self._event.is_set():
            from krmanfi_search.shared.exceptions import OperationCancelledError

            raise OperationCancelledError("cancelled")


def noop_progress(done: int, total: int, message: str):
    """Progress callback that ignores everything."""
    del done, total, message
