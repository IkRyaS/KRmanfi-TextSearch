"""structlog configuration: console (stderr) plus a rotating log file.

The log file lives in :func:`krmanfi_search.shared.runtime.log_dir` (``krmanfi-search.log``,
5 MB × 3 files). It is the only diagnostic channel of the windowed Windows build,
where ``sys.stderr`` is ``None``.
"""

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
    """structlog lines are already rendered; stdlib records get a time stamp and level."""

    def __init__(self):
        """Use the stdlib layout for foreign records."""
        super().__init__("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    def format(self, record: logging.LogRecord):
        """Render one record."""
        if record.name == STRUCTLOG_RECORD:
            return record.getMessage()
        return super().format(record)


class _Stderr:
    """Late-bound ``sys.stderr``.

    * GUI launchers on Windows (pythonw) have ``sys.stderr is None``: writes are dropped;
    * the current ``sys.stderr`` is looked up on every write, so redirections (tests,
      IDE consoles) never leave loggers pointing at a closed stream.
    """

    def write(self, text: str):
        """Write to the current ``sys.stderr`` if there is one."""
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
        """Flush the current ``sys.stderr``."""
        stream = sys.stderr
        if stream is not None:
            with contextlib.suppress(ValueError, OSError):
                stream.flush()

    def isatty(self):
        """Whether the current ``sys.stderr`` is a terminal."""
        stream = sys.stderr
        try:
            return bool(stream is not None and stream.isatty())
        except (ValueError, OSError):
            return False


class StderrLogger:
    """structlog logger that prints rendered events to stderr and the log file.

    Standard output stays reserved for data: ``--analyze`` prints JSON there.
    """

    def __init__(self, stream: _Stderr):
        """Bind the late-bound stream."""
        self._stream = stream

    def msg(self, message: str):
        """Print one rendered log line."""
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
    """Path of the current log file."""
    return log_dir() / LOG_FILE_NAME


def _file_handler(level: int):
    """Rotating UTF-8 file handler, or ``None`` if the folder is not writable."""
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
    """Configure structlog + stdlib logging once at start-up.

    Args:
        level: Log level name.
        json: Emit JSON lines instead of coloured console output.
        to_file: Also write the rotating log file.
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
    """Log uncaught exceptions of the main thread and of worker threads.

    Args:
        on_error: Optional ``callable(text)`` that shows the error to the user.
    """
    log = get_logger("krmanfi_search.crash")

    def report(
        kind: str, exc_type: type[BaseException], exc: BaseException, tb: TracebackType | None
    ):
        """Write the traceback to the log and notify the UI."""
        if issubclass(exc_type, KeyboardInterrupt):
            return
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        log.critical("uncaught", where=kind, error=f"{exc_type.__name__}: {exc}", tb=text)
        if on_error is not None:
            with contextlib.suppress(Exception):
                on_error(f"{exc_type.__name__}: {exc}")

    def main_hook(exc_type: type[BaseException], exc: BaseException, tb: TracebackType | None):
        """``sys.excepthook``."""
        report("main", exc_type, exc, tb)

    def thread_hook(args: threading.ExceptHookArgs):
        """``threading.excepthook``."""
        if args.exc_type is not None and args.exc_value is not None:
            name = args.thread.name if args.thread else "?"
            report(f"thread {name}", args.exc_type, args.exc_value, args.exc_traceback)

    sys.excepthook = main_hook
    threading.excepthook = thread_hook


def get_logger(name: str):
    """Return a bound logger for ``name``."""
    return structlog.get_logger(name)
