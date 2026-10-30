import logging
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from krmanfi_search.shared import logging as app_logging
from krmanfi_search.shared import optional, process, runtime
from krmanfi_search.shared.exceptions import (
    DependencyMissingError,
    OperationCancelledError,
    SearchError,
    SecurityLimitError,
)
from krmanfi_search.shared.types import CancelToken, noop_progress

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def reset_runtime_caches():
    runtime.vendor_tesseract.cache_clear()
    runtime.vendor_tessdata.cache_clear()
    yield
    runtime.vendor_tesseract.cache_clear()
    runtime.vendor_tessdata.cache_clear()


def test_exception_hierarchy():
    for error in (DependencyMissingError, SecurityLimitError, OperationCancelledError):
        assert issubclass(error, SearchError)


def test_dependency_error_names_the_package():
    error = DependencyMissingError("pytesseract")
    assert error.package == "pytesseract" and "pytesseract" in str(error)


def test_cancel_token_lifecycle():
    token = CancelToken()
    assert not token.cancelled
    token.raise_if_cancelled()
    token.cancel()
    assert token.cancelled
    with pytest.raises(OperationCancelledError):
        token.raise_if_cancelled()


def test_cancel_token_is_visible_from_another_thread():
    token = CancelToken()
    seen = []
    thread = threading.Thread(target=lambda: seen.append(token.cancelled))
    token.cancel()
    thread.start()
    thread.join()
    assert seen == [True]


def test_noop_progress_returns_nothing():
    assert noop_progress(1, 2, "x") is None


def test_not_frozen_in_tests():
    assert not runtime.is_frozen()
    assert runtime.app_dir() == ROOT == runtime.bundle_dir()
    assert (runtime.app_dir() / "pyproject.toml").is_file()


def test_frozen_layout(monkeypatch, tmp_path):
    exe = tmp_path / "app" / "KRmanfiSearch"
    exe.parent.mkdir()
    exe.write_text("", encoding="utf-8")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    monkeypatch.setattr(sys, "_MEIPASS", str(exe.parent / "_internal"), raising=False)
    assert runtime.is_frozen()
    assert runtime.app_dir() == exe.parent.resolve()
    assert runtime.bundle_dir() == exe.parent / "_internal"
    expected = [exe.parent.resolve() / "vendor", exe.parent / "_internal" / "vendor"]
    assert runtime.vendor_roots() == expected


def test_vendor_roots_start_with_override(monkeypatch, tmp_path):
    monkeypatch.setenv("KRMANFI_VENDOR_DIR", str(tmp_path))
    roots = runtime.vendor_roots()
    assert roots[0] == tmp_path and roots.count(ROOT / "vendor") == 1


def test_vendor_tessdata_needs_traineddata(monkeypatch, tmp_path):
    monkeypatch.setenv("KRMANFI_VENDOR_DIR", str(tmp_path))
    folder = tmp_path / "tesseract" / "tessdata"
    folder.mkdir(parents=True)
    assert runtime.vendor_tessdata() != folder
    runtime.vendor_tessdata.cache_clear()
    (folder / "rus.traineddata").write_bytes(b"x")
    assert runtime.vendor_tessdata() == folder


def test_vendor_tesseract_is_none_when_absent(monkeypatch, tmp_path):
    monkeypatch.setenv("KRMANFI_VENDOR_DIR", str(tmp_path))
    found = runtime.vendor_tesseract()
    assert found is None or found.is_relative_to(ROOT)


def test_data_dir_override_and_children(monkeypatch, tmp_path):
    monkeypatch.setenv("KRMANFI_SEARCH_DATA_DIR", str(tmp_path))
    assert runtime.data_dir() == tmp_path
    assert runtime.log_dir() == tmp_path / "logs"


def test_data_dir_default_is_user_folder(monkeypatch):
    monkeypatch.delenv("KRMANFI_SEARCH_DATA_DIR", raising=False)
    assert runtime.APP_NAME in str(runtime.data_dir())
    assert not runtime.data_dir().is_relative_to(ROOT)


def test_settings_file_prefers_user_copy(monkeypatch, tmp_path):
    monkeypatch.setenv("KRMANFI_SEARCH_DATA_DIR", str(tmp_path))
    assert runtime.settings_file() == ROOT / "settings.toml"
    (tmp_path / "settings.toml").write_text("workers = 2", encoding="utf-8")
    assert runtime.settings_file() == tmp_path / "settings.toml"


def test_resources_dir_has_icons():
    assert (runtime.resources_dir() / "icons" / "app.png").is_file()


def test_child_environment_adds_and_overrides(monkeypatch):
    monkeypatch.setenv("KR_TEST", "old")
    env = process.child_environment({"KR_TEST": "new", "OTHER": "1"})
    assert env["KR_TEST"] == "new" and env["OTHER"] == "1"


def test_child_environment_does_not_touch_os_environ(monkeypatch):
    monkeypatch.setenv("KR_TEST", "old")
    process.child_environment({"KR_TEST": "new"})
    assert __import__("os").environ["KR_TEST"] == "old"


def test_frozen_child_environment_restores_system_libraries(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("LD_LIBRARY_PATH", "/bundle/lib")
    monkeypatch.setenv("LD_LIBRARY_PATH_ORIG", "/usr/lib/original")
    monkeypatch.setenv("LIBPATH", "/bundle/libpath")
    monkeypatch.delenv("LIBPATH_ORIG", raising=False)
    env = process.child_environment()
    assert env["LD_LIBRARY_PATH"] == "/usr/lib/original"
    assert "LD_LIBRARY_PATH_ORIG" not in env and "LIBPATH" not in env


def test_no_window_flags_per_platform(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert process.no_window_flags() == 0
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    assert process.no_window_flags() == 0x08000000


def test_optional_import_returns_module_or_none():
    assert optional.optional_import("json").dumps({}) == "{}"
    assert optional.optional_import("definitely_not_installed_module") is None


def test_require_raises_for_missing_module():
    with pytest.raises(DependencyMissingError) as caught:
        optional.require("definitely_not_installed_module")
    assert caught.value.package == "definitely_not_installed_module"


def test_which_finds_program_on_path():
    optional.which.cache_clear()
    assert optional.which("python3") or optional.which("python")
    assert optional.which("definitely-no-such-program") is None


@pytest.fixture
def restore_logging():
    yield
    app_logging.configure_logging("WARNING", to_file=False)
    sys.excepthook = sys.__excepthook__
    threading.excepthook = threading.__excepthook__


def test_logging_writes_file_in_data_dir(monkeypatch, tmp_path, restore_logging):
    monkeypatch.setenv("KRMANFI_SEARCH_DATA_DIR", str(tmp_path))
    app_logging.configure_logging("INFO", to_file=True)
    app_logging.get_logger("test").info("тестовое событие", number=7)
    for handler in logging.getLogger().handlers:
        handler.flush()
    text = (tmp_path / "logs" / app_logging.LOG_FILE_NAME).read_text(encoding="utf-8")
    assert "тестовое событие" in text and "number" in text


def test_logging_level_filters_messages(capsys, restore_logging):
    app_logging.configure_logging("ERROR", to_file=False)
    app_logging.get_logger("test").info("тихо")
    app_logging.get_logger("test").error("громко")
    err = capsys.readouterr().err
    assert "громко" in err and "тихо" not in err


def test_logging_json_mode(capsys, restore_logging):
    app_logging.configure_logging("INFO", json=True, to_file=False)
    app_logging.get_logger("test").info("событие", key="v")
    assert '"key": "v"' in capsys.readouterr().err


def test_logging_survives_missing_stderr(monkeypatch, restore_logging):
    app_logging.configure_logging("INFO", to_file=False)
    monkeypatch.setattr(sys, "stderr", None)
    app_logging.get_logger("test").error("в пустоту")


def test_stderr_writer_replaces_unencodable_characters(monkeypatch):
    class Narrow:
        encoding = "ascii"

        def __init__(self):
            self.parts = []

        def write(self, text):
            text.encode("ascii")
            self.parts.append(text)

        def flush(self):
            pass

        def isatty(self):
            return False

    stream = Narrow()
    monkeypatch.setattr(sys, "stderr", stream)
    app_logging._Stderr().write("привет")
    assert stream.parts == ["??????"]


def test_excepthook_logs_and_notifies(restore_logging):
    messages = []
    app_logging.install_excepthooks(messages.append)
    sys.excepthook(ValueError, ValueError("плохо"), None)
    assert messages == ["ValueError: плохо"]


def test_excepthook_ignores_keyboard_interrupt(restore_logging):
    messages = []
    app_logging.install_excepthooks(messages.append)
    sys.excepthook(KeyboardInterrupt, KeyboardInterrupt(), None)
    assert messages == []


def test_thread_excepthook_reports_thread_errors(restore_logging):
    messages = []
    app_logging.install_excepthooks(messages.append)
    args = threading.ExceptHookArgs((RuntimeError, RuntimeError("в потоке"), None, None))
    threading.excepthook(args)
    assert messages == ["RuntimeError: в потоке"]


def test_failing_notifier_does_not_break_hook(restore_logging):
    def broken(text):
        raise RuntimeError("уведомитель сломан")

    app_logging.install_excepthooks(broken)
    sys.excepthook(ValueError, ValueError("x"), None)
