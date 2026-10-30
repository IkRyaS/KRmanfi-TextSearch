"""Background jobs on ``QThreadPool`` with Qt-signal progress (Observer) and cancellation."""

from __future__ import annotations

import functools
import traceback
from collections.abc import Callable
from typing import Any

import shiboken6
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from krmanfi_search.shared.exceptions import OperationCancelledError, SearchError
from krmanfi_search.shared.logging import get_logger
from krmanfi_search.shared.types import CancelToken, ProgressCallback

log = get_logger(__name__)

type Emit = Callable[[object], None]
type JobFunc = Callable[[CancelToken, ProgressCallback, Emit], object]


class WorkerSignals(QObject):
    """Signals are delivered to the GUI thread via queued connections."""

    progress = Signal(object, object, str)
    item = Signal(object)
    result = Signal(object)
    error = Signal(str)
    cancelled = Signal()
    finished = Signal()


class Worker(QRunnable):
    """Runs ``func(cancel, progress, emit)`` in the thread pool."""

    def __init__(self, func: JobFunc):
        """Wrap ``func``."""
        super().__init__()
        self.setAutoDelete(True)
        self.func = func
        self.signals = WorkerSignals()
        self.cancel_token = CancelToken()
        self.detached = False

    def cancel(self):
        """Request cooperative cancellation (``finished`` / ``cancelled`` still arrive)."""
        self.cancel_token.cancel()

    def detach(self):
        """Cancel and drop every further signal: used when a new run replaces this one."""
        self.detached = True
        self.cancel_token.cancel()

    def run(self):
        """QRunnable entry point."""
        sig = self.signals
        try:
            out = self.func(self.cancel_token, self._progress, self._emit)
        except OperationCancelledError:
            sig.cancelled.emit()
        except SearchError as exc:
            sig.error.emit(str(exc))
        except Exception as exc:
            log.exception("worker.failed", error=str(exc), tb=traceback.format_exc())
            sig.error.emit(f"{type(exc).__name__}: {exc}")
        else:
            if not self.cancel_token.cancelled:
                sig.result.emit(out)
            else:
                sig.cancelled.emit()
        finally:
            sig.finished.emit()

    def _progress(self, done: int, total: int, message: str):
        """Forward progress to the GUI thread."""
        self.signals.progress.emit(done, total, message)

    def _emit(self, obj: object):
        """Forward an intermediate item to the GUI thread."""
        self.signals.item.emit(obj)


def _guarded(worker: Worker, name: str, slot: Callable[..., Any], owner: QObject | None):
    """Wrap a slot: skip detached workers and deleted widgets, log slot exceptions.

    An exception escaping a Qt slot is only printed by PySide6 (and lost in the
    windowed build) and leaves the UI half updated, so it is logged here instead.
    """

    def call(*args: object):
        """Deliver the signal if the receiver still wants it."""
        if worker.detached:
            return
        if owner is not None and not shiboken6.isValid(owner):
            return
        try:
            slot(*args)
        except RuntimeError as exc:
            if "already deleted" in str(exc):
                return
            log.exception("worker.slot_failed", signal=name, error=str(exc))
        except Exception as exc:
            log.exception("worker.slot_failed", signal=name, error=str(exc))

    return call


def submit(
    func: JobFunc,
    *,
    owner: QObject | None = None,
    pool: QThreadPool | None = None,
    **slots: Callable[..., Any],
):
    """Create a worker, connect ``slots`` (by signal name) and start it.

    Args:
        func: ``func(cancel, progress, emit)`` run in a pool thread.
        owner: Widget the results are for; signals are dropped once it is deleted.
        pool: Thread pool (default: the global one).
        **slots: ``progress``, ``item``, ``result``, ``error``, ``cancelled``, ``finished``.

    Example:
        ``submit(job, owner=self, result=self._on_done, error=self._on_error)``
    """
    worker = Worker(func)
    for name, slot in slots.items():
        getattr(worker.signals, name).connect(_guarded(worker, name, slot, owner))
    (pool or QThreadPool.globalInstance()).start(worker)
    return worker


@functools.cache
def listing_pool():
    """Small dedicated pool for directory listings, never blocked by long analyses."""
    pool = QThreadPool()
    pool.setMaxThreadCount(2)
    return pool
