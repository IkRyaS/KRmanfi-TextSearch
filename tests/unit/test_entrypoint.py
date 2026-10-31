import multiprocessing
import os
import subprocess
import sys
from pathlib import Path

import pytest

import krmanfi_search
from krmanfi_search import __main__ as entry
from krmanfi_search.presentation import app as app_module

SRC = Path(krmanfi_search.__file__).resolve().parents[1]


def child_env():
    return dict(
        os.environ, PYTHONPATH=str(SRC), PYTHONIOENCODING="utf-8", QT_QPA_PLATFORM="offscreen"
    )


def test_parser_accepts_optional_path():
    parser = entry.build_parser()
    assert parser.parse_args([]).path is None
    assert parser.parse_args(["/tmp/папка"]).path == Path("/tmp/папка")


def test_parser_rejects_unknown_options():
    with pytest.raises(SystemExit) as exit_:
        entry.build_parser().parse_args(["--nonsense"])
    assert exit_.value.code == 2


def test_main_starts_the_window_with_given_path(monkeypatch):
    calls = []
    monkeypatch.setattr(multiprocessing, "freeze_support", lambda: calls.append("freeze"))
    monkeypatch.setattr(
        multiprocessing,
        "set_start_method",
        lambda method, force=False: calls.append((method, force)),
    )
    monkeypatch.setattr(app_module, "run", lambda argv, path: calls.append(("run", path)) or 7)
    assert entry.main(["/tmp/папка"]) == 7
    assert calls == ["freeze", ("spawn", True), ("run", Path("/tmp/папка"))]


def test_main_without_path_passes_none(monkeypatch):
    seen = []
    monkeypatch.setattr(multiprocessing, "freeze_support", lambda: None)
    monkeypatch.setattr(multiprocessing, "set_start_method", lambda method, force=False: None)
    monkeypatch.setattr(app_module, "run", lambda argv, path: seen.append(path) or 0)
    assert entry.main([]) == 0 and seen == [None]


def test_module_help_runs_in_a_fresh_process():
    result = subprocess.run(
        [sys.executable, "-m", "krmanfi_search", "--help"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=child_env(),
        timeout=60,
        check=False,
    )
    assert result.returncode == 0 and "Поиск по документам" in result.stdout


def test_version_is_a_dotted_number():
    parts = krmanfi_search.__version__.split(".")
    assert len(parts) >= 2 and all(part.isdigit() for part in parts[:2])


def test_crash_notifier_throttles_dialogs(qtbot):
    notifier = app_module.CrashNotifier()
    notifier.failed.emit("первая ошибка")
    notifier.failed.emit("вторая сразу после первой")
    assert len(notifier._boxes) == 1
    assert "первая ошибка" in notifier._boxes[0].text()
    notifier._boxes[0].close()
    notifier._last -= app_module.CRASH_BOX_INTERVAL + 1
    notifier.failed.emit("третья позже")
    assert len(notifier._boxes) == 1 and "третья позже" in notifier._boxes[0].text()
    notifier._boxes[0].close()
