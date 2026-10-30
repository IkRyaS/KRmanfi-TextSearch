import threading

import pytest
import shiboken6
from PySide6.QtCore import QObject, QThreadPool

from krmanfi_search.presentation import workers
from krmanfi_search.presentation.workers import Worker, _guarded, listing_pool, submit
from krmanfi_search.shared.exceptions import OperationCancelledError, SearchError


class Recorder:
    def __init__(self):
        self.events = []

    def slot(self, name):
        return lambda *args: self.events.append((name, *args))

    def names(self):
        return [event[0] for event in self.events]


def run_job(qtbot, func, **extra):
    recorder = Recorder()
    slots = {
        name: recorder.slot(name)
        for name in ("progress", "item", "result", "error", "cancelled", "finished")
    }
    worker = submit(func, **slots, **extra)
    qtbot.waitUntil(lambda: "finished" in recorder.names(), timeout=10_000)
    return worker, recorder


def test_result_and_finished_are_delivered(qtbot):
    worker, recorder = run_job(qtbot, lambda cancel, progress, emit: 42)
    assert recorder.events == [("result", 42), ("finished",)]
    assert not worker.detached


def test_progress_and_items_arrive_in_order(qtbot):
    def job(cancel, progress, emit):
        for number in range(3):
            progress(number, 3, f"шаг {number}")
            emit(f"элемент {number}")
        return "готово"

    _, recorder = run_job(qtbot, job)
    items = [e[1] for e in recorder.events if e[0] == "item"]
    steps = [e[3] for e in recorder.events if e[0] == "progress"]
    assert items == ["элемент 0", "элемент 1", "элемент 2"]
    assert steps == ["шаг 0", "шаг 1", "шаг 2"]
    assert recorder.names()[-2:] == ["result", "finished"]


def test_search_error_text_goes_to_error_signal(qtbot):
    def job(cancel, progress, emit):
        raise SearchError("понятная причина")

    _, recorder = run_job(qtbot, job)
    assert ("error", "понятная причина") in recorder.events and "result" not in recorder.names()


def test_unexpected_exception_is_reported_with_type(qtbot):
    def job(cancel, progress, emit):
        raise ValueError("boom")

    _, recorder = run_job(qtbot, job)
    assert ("error", "ValueError: boom") in recorder.events
    assert recorder.names()[-1] == "finished"


def test_cancellation_exception_becomes_cancelled_signal(qtbot):
    def job(cancel, progress, emit):
        raise OperationCancelledError("stop")

    _, recorder = run_job(qtbot, job)
    assert recorder.names() == ["cancelled", "finished"]


def test_cancel_flag_turns_result_into_cancelled(qtbot):
    started, release = threading.Event(), threading.Event()

    def job(cancel, progress, emit):
        started.set()
        release.wait(5)
        return "поздно"

    recorder = Recorder()
    worker = submit(job, result=recorder.slot("result"), cancelled=recorder.slot("cancelled"),
                    finished=recorder.slot("finished"))
    assert started.wait(5)
    worker.cancel()
    release.set()
    qtbot.waitUntil(lambda: "finished" in recorder.names(), timeout=10_000)
    assert recorder.names() == ["cancelled", "finished"]


def test_job_sees_the_cancel_token(qtbot):
    seen = []

    def job(cancel, progress, emit):
        seen.append(cancel.cancelled)
        return None

    run_job(qtbot, job)
    assert seen == [False]


def test_detached_worker_drops_signals(qtbot):
    started, release = threading.Event(), threading.Event()
    recorder = Recorder()

    def job(cancel, progress, emit):
        started.set()
        release.wait(5)
        emit("поздний элемент")
        return "поздний результат"

    worker = submit(job, item=recorder.slot("item"), result=recorder.slot("result"),
                    finished=recorder.slot("finished"))
    assert started.wait(5)
    worker.detach()
    release.set()
    qtbot.wait(300)
    assert worker.detached and worker.cancel_token.cancelled
    assert recorder.events == []


def test_signals_for_deleted_owner_are_dropped(qtbot):
    owner = QObject()
    recorder = Recorder()
    worker = Worker(lambda cancel, progress, emit: 1)
    call = _guarded(worker, "result", recorder.slot("result"), owner)
    call("жив")
    shiboken6.delete(owner)
    call("мёртв")
    assert recorder.events == [("result", "жив")]


def test_slot_exception_is_logged_not_raised():
    worker = Worker(lambda cancel, progress, emit: 1)

    def broken(*args):
        raise ZeroDivisionError("в слоте")

    _guarded(worker, "result", broken, None)(1)


def test_deleted_widget_runtime_error_is_swallowed():
    worker = Worker(lambda cancel, progress, emit: 1)

    def gone(*args):
        raise RuntimeError("Internal C++ object (X) already deleted.")

    _guarded(worker, "result", gone, None)(1)


def test_other_runtime_errors_are_also_contained():
    worker = Worker(lambda cancel, progress, emit: 1)

    def odd(*args):
        raise RuntimeError("что-то другое")

    _guarded(worker, "result", odd, None)(1)


def test_unknown_slot_name_is_rejected():
    with pytest.raises(AttributeError):
        submit(lambda cancel, progress, emit: 1, nonsense=lambda: None)


def test_custom_pool_is_used(qtbot):
    pool = QThreadPool()
    pool.setMaxThreadCount(1)
    recorder = Recorder()
    submit(lambda cancel, progress, emit: "в своём пуле", pool=pool,
           result=recorder.slot("result"), finished=recorder.slot("finished"))
    qtbot.waitUntil(lambda: "finished" in recorder.names(), timeout=10_000)
    assert recorder.events[0] == ("result", "в своём пуле")
    pool.waitForDone(2000)


def test_listing_pool_is_a_cached_small_pool():
    pool = listing_pool()
    assert pool is listing_pool() and pool.maxThreadCount() == 2
    assert pool is not QThreadPool.globalInstance()


def test_worker_module_exposes_expected_signals():
    assert {"progress", "item", "result", "error", "cancelled", "finished"} <= set(
        dir(workers.WorkerSignals)
    )
