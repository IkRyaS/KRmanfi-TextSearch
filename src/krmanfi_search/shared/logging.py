from __future__ import annotations

import contextlib
import logging
import logging.handlers
import re
import sys
import threading
import traceback
from collections.abc import Callable
from types import TracebackType

import structlog

from krmanfi_search.shared.runtime import log_dir

LOG_FILE_NAME = "krmanfi-search.log"
LOG_FILE_BYTES = 5 * 1024 * 1024
LOG_FILE_BACKUPS = 3
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_STATE = {}
STRUCTLOG_RECORD = "krmanfi_search.structlog"


class _FileFormatter(logging.Formatter):
    """Строки structlog уже отрисованы; записям stdlib добавляется отметка времени."""

    def __init__(self):
        """Использовать формат stdlib для чужих записей."""
        super().__init__("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    def format(self, record: logging.LogRecord):
        """Отрисовать одну запись."""
        if record.name == STRUCTLOG_RECORD:
            return record.getMessage()
        return super().format(record)


class _Stderr:
    """Поток ``sys.stderr``, который определяется в момент записи.

    * У оконных запусков Windows (pythonw) ``sys.stderr is None``: запись отбрасывается;
    * текущий ``sys.stderr`` берётся при каждой записи, поэтому перенаправления (тесты,
      консоли IDE) не оставляют логгеры на закрытом потоке.
    """

    def write(self, text: str):
        """Записать в текущий ``sys.stderr``, если он есть."""
        stream = sys.stderr
        if stream is None:
            return len(text)
        try:
            return stream.write(text)
        except UnicodeEncodeError:
            encoding = getattr(stream, "encoding", None) or "ascii"
            return stream.write(text.encode(encoding, "replace").decode(encoding, "replace"))
        except (ValueError, OSError):
            return len(text)

    def flush(self):
        """Сбросить буфер текущего ``sys.stderr``."""
        stream = sys.stderr
        if stream is not None:
            with contextlib.suppress(ValueError, OSError):
                stream.flush()

    def isatty(self):
        """Является ли текущий ``sys.stderr`` терминалом."""
        stream = sys.stderr
        try:
            return bool(stream is not None and stream.isatty())
        except (ValueError, OSError):
            return False


class StderrLogger:
    """Логгер structlog: печатает готовые события в stderr и в файл журнала.

    Стандартный вывод остаётся для данных.
    """

    def __init__(self, stream: _Stderr):
        """Привязать поток, определяемый в момент записи."""
        self._stream = stream

    def msg(self, message: str):
        """Напечатать одну готовую строку журнала."""
        self._stream.write(message + "\n")
        self._stream.flush()
        handler = _STATE.get("file")
        if handler is not None:
            text = _ANSI.sub("", message)
            record = logging.LogRecord(STRUCTLOG_RECORD, logging.INFO, "", 0, text, None, None)
            with contextlib.suppress(Exception):
                handler.emit(record)

    log = debug = info = warn = warning = err = error = critical = exception = fatal = msg


def log_file():
    """Путь к текущему файлу журнала."""
    return log_dir() / LOG_FILE_NAME


def _file_handler(level: int):
    """Файловый обработчик с ротацией (UTF-8) или ``None``, если папка недоступна для записи."""
    try:
        folder = log_dir()
        folder.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            folder / LOG_FILE_NAME,
            maxBytes=LOG_FILE_BYTES,
            backupCount=LOG_FILE_BACKUPS,
            encoding="utf-8",
            errors="backslashreplace",
            delay=True,
        )
    except OSError:
        return None
    handler.setLevel(level)
    handler.setFormatter(_FileFormatter())
    return handler


def configure_logging(level: str = "INFO", json: bool = False, to_file: bool = True):
    """Один раз при запуске настроить structlog и стандартное логирование.

    Args:
        level: Имя уровня журнала.
        json: Выводить строки JSON вместо цветной консоли.
        to_file: Дополнительно писать файл журнала с ротацией.
    """
    numeric = logging.getLevelNamesMapping().get(level.upper(), logging.INFO)
    stream = _Stderr()
    console = logging.StreamHandler(stream)
    console.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    previous = _STATE.pop("file", None)
    if previous is not None:
        with contextlib.suppress(Exception):
            previous.close()
    handler = _file_handler(numeric) if to_file else None
    if handler is not None:
        _STATE["file"] = handler
    handlers = [h for h in (console, handler) if h is not None]
    logging.basicConfig(level=numeric, handlers=handlers, force=True)
    renderer = (
        structlog.processors.JSONRenderer()
        if json
        else structlog.dev.ConsoleRenderer(colors=stream.isatty())
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric),
        logger_factory=lambda *args: StderrLogger(stream),
        cache_logger_on_first_use=True,
    )


def install_excepthooks(on_error: Callable[[str], object] | None = None):
    """Записывать в журнал необработанные исключения главного потока и рабочих потоков.

    Args:
        on_error: Необязательная функция ``callable(текст)``, показывающая ошибку пользователю.
    """
    log = get_logger("krmanfi_search.crash")

    def report(
        kind: str, exc_type: type[BaseException], exc: BaseException, tb: TracebackType | None
    ):
        """Записать трассировку в журнал и сообщить окну."""
        if issubclass(exc_type, KeyboardInterrupt):
            return
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        log.critical("uncaught", where=kind, error=f"{exc_type.__name__}: {exc}", tb=text)
        if on_error is not None:
            with contextlib.suppress(Exception):
                on_error(f"{exc_type.__name__}: {exc}")

    def main_hook(exc_type: type[BaseException], exc: BaseException, tb: TracebackType | None):
        """Обработчик ``sys.excepthook``."""
        report("main", exc_type, exc, tb)

    def thread_hook(args: threading.ExceptHookArgs):
        """Обработчик ``threading.excepthook``."""
        if args.exc_type is not None and args.exc_value is not None:
            name = args.thread.name if args.thread else "?"
            report(f"thread {name}", args.exc_type, args.exc_value, args.exc_traceback)

    sys.excepthook = main_hook
    threading.excepthook = thread_hook


def get_logger(name: str):
    """Вернуть привязанный логгер для ``name``."""
    return structlog.get_logger(name)
