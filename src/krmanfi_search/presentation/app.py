"""Запуск Qt-приложения."""

from __future__ import annotations

import sys
import time
from collections.abc import Sequence
from pathlib import Path

from PySide6.QtCore import QObject, QThreadPool, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from krmanfi_search import __version__
from krmanfi_search.container import Container
from krmanfi_search.infrastructure.config import Settings
from krmanfi_search.presentation.main_window import WINDOW_TITLE, SearchWindow
from krmanfi_search.presentation.theme import STYLESHEET
from krmanfi_search.shared.logging import (
    configure_logging,
    get_logger,
    install_excepthooks,
    log_file,
)
from krmanfi_search.shared.runtime import resources_dir

CRASH_BOX_INTERVAL = 3.0


class CrashNotifier(QObject):
    """Показывает необработанные ошибки любого потока в главном потоке."""

    failed = Signal(str)

    def __init__(self):
        """Подключить сигнал к окну сообщения."""
        super().__init__()
        self.failed.connect(self._show)
        self._last = 0.0
        self._boxes = []

    def _show(self, text: str):
        """Неблокирующее окно ошибки не чаще раза в несколько секунд."""
        now = time.monotonic()
        if now - self._last < CRASH_BOX_INTERVAL:
            return
        self._last = now
        box = QMessageBox(QMessageBox.Icon.Critical, f"{WINDOW_TITLE}: ошибка", text)
        box.setInformativeText(f"Подробности записаны в журнал:\n{log_file()}")
        box.setModal(False)
        box.finished.connect(lambda _code: self._boxes.remove(box))
        self._boxes.append(box)
        box.show()


def run(argv: Sequence[str], start_path: Path | None = None, settings: Settings | None = None):
    """Создать приложение, показать окно и запустить цикл событий.

    Args:
        argv: Аргументы командной строки для Qt.
        start_path: Папка или архив для поля «Где».
        settings: Готовые настройки (по умолчанию читаются из файла).

    Returns:
        Код завершения процесса.
    """
    settings = settings or Settings.load()
    configure_logging(settings.log_level)
    log = get_logger(__name__)
    app = QApplication(list(argv))
    app.setStyle("Fusion")
    app.setStyleSheet(STYLESHEET)
    notifier = CrashNotifier()
    install_excepthooks(notifier.failed.emit)
    app.setApplicationName(WINDOW_TITLE)
    app.setApplicationVersion(__version__)
    icon = resources_dir() / "icons" / "app.png"
    if icon.is_file():
        app.setWindowIcon(QIcon(str(icon)))
    window = SearchWindow(Container.build(settings), start_path)
    window.show()
    log.info("app.started", version=__version__, platform=sys.platform, log=str(log_file()))
    if settings.load_error:
        QMessageBox.warning(
            window,
            WINDOW_TITLE,
            "Файл настроек не прочитан, используются значения по умолчанию:\n"
            f"{settings.load_error}",
        )
    try:
        return app.exec()
    finally:
        QThreadPool.globalInstance().waitForDone(3000)
