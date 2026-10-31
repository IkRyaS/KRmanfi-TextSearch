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
    """Сигналы доставляются в поток окна через очередь событий Qt."""

    progress = Signal(object, object, str)
    item = Signal(object)
    result = Signal(object)
    error = Signal(str)
    cancelled = Signal()
    finished = Signal()


class Worker(QRunnable):
    """Выполняет ``func(cancel, progress, emit)`` в пуле потоков."""

    def __init__(self, func: JobFunc):
        """Обернуть функцию ``func``."""
        super().__init__()
        self.setAutoDelete(True)
        self.func = func
        self.signals = WorkerSignals()
        self.cancel_token = CancelToken()
        self.detached = False

    def cancel(self):
        """Запросить мягкую отмену (сигналы ``finished`` и ``cancelled`` всё равно придут)."""
        self.cancel_token.cancel()

    def detach(self):
        """Отменить и отбросить все дальнейшие сигналы: нужно, когда новый запуск заменяет этот."""
        self.detached = True
        self.cancel_token.cancel()

    def run(self):
        """Точка входа ``QRunnable``."""
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
        """Передать прогресс в поток окна."""
        self.signals.progress.emit(done, total, message)

    def _emit(self, obj: object):
        """Передать промежуточный элемент в поток окна."""
        self.signals.item.emit(obj)


def _guarded(worker: Worker, name: str, slot: Callable[..., Any], owner: QObject | None):
    """Обернуть слот: пропускать отсоединённые задачи и удалённые виджеты, логировать исключения.

    Исключение, вылетевшее из слота Qt, PySide6 лишь печатает (в оконной сборке оно теряется),
    а окно остаётся обновлённым наполовину, поэтому здесь оно пишется в журнал.
    """

    def call(*args: object):
        """Доставить сигнал, если получатель всё ещё его ждёт."""
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
    """Создать задачу, подключить ``slots`` (по именам сигналов) и запустить её.

    Args:
        func: ``func(cancel, progress, emit)``, выполняется в потоке пула.
        owner: Виджет, для которого нужны результаты; после его удаления сигналы отбрасываются.
        pool: Пул потоков (по умолчанию глобальный).
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
    """Небольшой отдельный пул для просмотра папок: его не блокируют долгие анализы."""
    pool = QThreadPool()
    pool.setMaxThreadCount(2)
    return pool
