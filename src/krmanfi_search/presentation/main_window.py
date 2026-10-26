"""Главное окно: форма запроса, потоковые результаты, фильтр, экспорт и открытие файла."""

from __future__ import annotations

import shutil
import tempfile
import time
from pathlib import Path

from PySide6.QtCore import QModelIndex, Qt, QUrl
from PySide6.QtGui import QCloseEvent, QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from krmanfi_search import __version__
from krmanfi_search.container import Container
from krmanfi_search.domain import SearchHit, SearchMode, SearchQuery, SearchStats
from krmanfi_search.infrastructure.archives import extract_chain
from krmanfi_search.infrastructure.search.exporter import export_csv
from krmanfi_search.infrastructure.search.service import ARCHIVE_SEPARATOR, TEMP_PREFIX
from krmanfi_search.presentation.results_model import (
    COL_CONTEXT,
    COL_WHERE,
    NodeKind,
    SearchResultsModel,
    SearchResultsProxy,
)
from krmanfi_search.presentation.workers import Emit, submit
from krmanfi_search.shared.types import CancelToken, ProgressCallback

WINDOW_TITLE = "KRmanfi Text Search"
MODES = {"Подстрока": SearchMode.SUBSTRING, "Регулярное выражение": SearchMode.REGEX}
ETA_MIN_ELAPSED = 5.0
COLUMN_WIDTHS = (320, 260, 200)
FILE_FILTER = (
    "Документы и архивы (*.zip *.pdf *.docx *.xlsx *.pptx *.txt *.md *.log *.csv);;Все файлы (*)"
)


def format_duration(seconds: float):
    """``45 с``, ``3 мин 10 с``, ``1 ч 05 мин``."""
    total = int(seconds)
    if total < 60:
        return f"{total} с"
    minutes, sec = divmod(total, 60)
    if minutes < 60:
        return f"{minutes} мин {sec:02d} с"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} ч {minutes:02d} мин"


class SearchWindow(QMainWindow):
    """Окно приложения «Найти текст в документах»."""

    def __init__(self, container: Container, start_path: Path | None = None):
        """Построить окно.

        Args:
            container: Готовые сервисы.
            start_path: Папка или архив, подставляемые в поле пути.
        """
        super().__init__()
        self._container = container
        self._hits = []
        self._worker = None
        self._stats = SearchStats()
        self._started = time.monotonic()
        self._temp_copies = []
        self._ocr_requested = True
        self.setWindowTitle(f"{WINDOW_TITLE} {__version__}")
        self.resize(1180, 760)
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        warning = container.ocr.status_text()
        self.ocr_label = QLabel(f"⚠ {warning}" if warning else "")
        self.ocr_label.setWordWrap(True)
        self.ocr_label.setStyleSheet("color: #8a5a00; background: #fff4d6; padding: 4px;")
        self.ocr_label.setVisible(bool(warning))
        layout.addWidget(self.ocr_label)
        layout.addWidget(self._build_form(start_path))
        layout.addLayout(self._build_controls())
        layout.addLayout(self._build_status_row())
        layout.addLayout(self._build_filter_row())
        layout.addWidget(self._build_results(), 1)
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)
        QShortcut(QKeySequence("Ctrl+Shift+F"), self, activated=self.query.setFocus)
        QShortcut(QKeySequence("Escape"), self, activated=self.stop)
        self._update_start_enabled()
        self.query.setFocus()

    def _build_form(self, start_path: Path | None):
        """Группа с полями запроса."""
        box = QGroupBox("Параметры")
        form = QFormLayout(box)
        path_row = QHBoxLayout()
        self.path_edit = QLineEdit(str(start_path) if start_path else "")
        self.path_edit.setPlaceholderText("Папка или архив (.zip), где искать")
        folder_btn = QPushButton("Папка…")
        folder_btn.clicked.connect(self._choose_folder)
        file_btn = QPushButton("Файл / архив…")
        file_btn.clicked.connect(self._choose_file)
        for widget in (self.path_edit, folder_btn, file_btn):
            path_row.addWidget(widget, 1 if widget is self.path_edit else 0)
        form.addRow("Где:", path_row)
        self.query = QLineEdit()
        self.query.setPlaceholderText("Что искать…")
        self.query.returnPressed.connect(self.start)
        self.query.textChanged.connect(self._update_start_enabled)
        self.path_edit.textChanged.connect(self._update_start_enabled)
        form.addRow("Текст:", self.query)
        row = QHBoxLayout()
        self.mode = QComboBox()
        self.mode.addItems(list(MODES))
        self.case = QCheckBox("Учитывать регистр")
        self.context = QSpinBox()
        self.context.setRange(0, 2000)
        self.context.setValue(self._container.settings.context_chars)
        self.context.setSuffix(" символов контекста")
        self.ocr_pdf = QCheckBox("OCR сканов PDF")
        self.ocr_pdf.setChecked(True)
        self.archives = QCheckBox("Искать в архивах")
        self.archives.setChecked(True)
        for widget in (self.mode, self.case, self.context, self.ocr_pdf, self.archives):
            row.addWidget(widget)
        row.addStretch(1)
        form.addRow("Режим:", row)
        return box

    def _build_controls(self):
        """Кнопки и индикатор выполнения."""
        controls = QHBoxLayout()
        self.start_btn = QPushButton("Найти")
        self.start_btn.clicked.connect(self.start)
        self.stop_btn = QPushButton("Стоп")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop)
        self.export_btn = QPushButton("Экспорт (CSV)…")
        self.export_btn.setEnabled(False)
        self.export_btn.clicked.connect(self._export)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        for widget in (self.start_btn, self.stop_btn, self.export_btn):
            controls.addWidget(widget)
        controls.addWidget(self.progress, 1)
        return controls

    def _build_status_row(self):
        """Строка состояния, сообщение об ошибке и кнопка проблем."""
        row = QHBoxLayout()
        column = QVBoxLayout()
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: #b00020;")
        self.error_label.setWordWrap(True)
        self.error_label.setVisible(False)
        column.addWidget(self.status)
        column.addWidget(self.error_label)
        row.addLayout(column, 1)
        self.problems_btn = QPushButton("Файлы без текста / ошибки…")
        self.problems_btn.setVisible(False)
        self.problems_btn.clicked.connect(self._show_problems)
        row.addWidget(self.problems_btn)
        return row

    def _build_filter_row(self):
        """Фильтр результатов и кнопки раскрытия."""
        row = QHBoxLayout()
        self.result_filter = QLineEdit()
        self.result_filter.setPlaceholderText("Фильтр результатов: файл, страница, текст…")
        self.result_filter.setClearButtonEnabled(True)
        self.result_filter.textChanged.connect(self._filter_changed)
        expand = QPushButton("Развернуть всё")
        collapse = QPushButton("Свернуть всё")
        row.addWidget(self.result_filter, 1)
        row.addWidget(expand)
        row.addWidget(collapse)
        self._expand_btn = expand
        self._collapse_btn = collapse
        return row

    def _build_results(self):
        """Дерево результатов."""
        self.model = SearchResultsModel()
        self.proxy = SearchResultsProxy()
        self.proxy.setSourceModel(self.model)
        self.results = QTreeView()
        self.results.setModel(self.proxy)
        self.results.setUniformRowHeights(True)
        self.results.setAlternatingRowColors(True)
        self.results.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.results.setExpandsOnDoubleClick(False)
        self.results.doubleClicked.connect(self._activate)
        header = self.results.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(COL_CONTEXT, QHeaderView.ResizeMode.Stretch)
        for column, width in enumerate(COLUMN_WIDTHS):
            self.results.setColumnWidth(column, width)
        self.model.rowsInserted.connect(self._auto_expand)
        self._expand_btn.clicked.connect(self.results.expandAll)
        self._collapse_btn.clicked.connect(self.results.collapseAll)
        return self.results

    def _choose_folder(self):
        """Выбрать папку для поиска."""
        folder = QFileDialog.getExistingDirectory(self, "Папка для поиска", self.path_edit.text())
        if folder:
            self.path_edit.setText(folder)

    def _choose_file(self):
        """Выбрать архив или документ."""
        name, _ = QFileDialog.getOpenFileName(
            self,
            "Файл или архив",
            self.path_edit.text(),
            FILE_FILTER,
        )
        if name:
            self.path_edit.setText(name)

    def _update_start_enabled(self):
        """Кнопка «Найти» доступна, когда есть текст и путь и поиск не идёт."""
        ready = bool(self.query.text().strip() and self.path_edit.text().strip())
        self.start_btn.setEnabled(ready and self._worker is None)

    def _filter_changed(self, text: str):
        """Фильтровать результаты; подходящие строки сохраняют родителей."""
        self.proxy.setFilterFixedString(text)
        if text:
            self.results.expandAll()

    def _auto_expand(self, parent: QModelIndex, first: int, last: int):
        """Раскрывать файлы по мере появления, чтобы страницы были видны."""
        del first, last
        if parent.isValid() and self.model.kind_at(parent) is NodeKind.FILE:
            self.results.expand(self.proxy.mapFromSource(parent))

    def build_query(self):
        """Собрать запрос из формы.

        Raises:
            ValueError: Если поля заполнены некорректно.
        """
        settings = self._container.settings
        return SearchQuery(
            text=self.query.text(),
            root=Path(self.path_edit.text().strip()).expanduser(),
            mode=MODES[self.mode.currentText()],
            case_sensitive=self.case.isChecked(),
            context_chars=self.context.value(),
            include_archives=self.archives.isChecked(),
            ocr_scanned_pdfs=self.ocr_pdf.isChecked(),
            max_file_size=settings.max_file_size_mb * 1024 * 1024,
        )

    def _show_error(self, text: str):
        """Показать ошибку под строкой состояния (без модального окна)."""
        self.error_label.setText(text)
        self.error_label.setVisible(bool(text))

    def start(self):
        """Начать новый поиск; результаты прошлого прогона удаляются."""
        if self._worker is not None or not self.start_btn.isEnabled():
            return
        self._show_error("")
        try:
            query = self.build_query()
        except ValueError as exc:
            self._show_error(str(exc))
            return
        self._hits.clear()
        self.model.clear_hits()
        self._ocr_requested = query.ocr_scanned_pdfs
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.export_btn.setEnabled(False)
        self.problems_btn.setVisible(False)
        self.progress.setRange(0, 0)
        self._started = time.monotonic()
        stats = self._stats = SearchStats()
        search = self._container.search_text

        def job(cancel: CancelToken, progress: ProgressCallback, emit: Emit):
            """Фоновая задача: передаёт совпадения окну по мере нахождения."""
            count = 0
            for hit in search(query, progress=progress, cancel=cancel, stats=stats):
                emit(hit)
                count += 1
            return count

        self._worker = submit(
            job,
            owner=self,
            item=self._add_hit,
            progress=self._on_progress,
            result=self._on_done,
            error=self._on_error,
            cancelled=lambda: self.status.setText("Остановлено"),
            finished=self._on_finished,
        )

    def stop(self):
        """Остановить поиск."""
        if self._worker is not None:
            self._worker.cancel()

    def _add_hit(self, hit: object):
        """Добавить совпадение в дерево."""
        assert isinstance(hit, SearchHit)
        self._hits.append(hit)
        self.model.add_hit(hit)

    def _on_progress(self, done: int, total: int, message: str):
        """Показать прогресс и оценку оставшегося времени."""
        if total <= 0:
            self.progress.setRange(0, 0)
        else:
            self.progress.setRange(0, total)
            self.progress.setValue(min(done, total))
        text = f"{done}/{total or '?'} — {message}"
        elapsed = time.monotonic() - self._started
        if done and total > done and elapsed > ETA_MIN_ELAPSED:
            text += f" · осталось ≈ {format_duration(elapsed / done * (total - done))}"
        self.status.setText(text)

    def _on_done(self, count: object):
        """Показать итог поиска."""
        stats = self._stats
        if not stats.files_total:
            text = (
                "Готово: подходящих файлов не найдено "
                "(PDF, DOCX, XLSX, PPTX, TXT, MD, LOG, CSV, ZIP)."
            )
        elif not count:
            text = f"Готово: совпадений нет. Просмотрено {stats.scanned} файлов; без текста — "
            text += f"{stats.without_text}; ошибок — {stats.failed}"
        else:
            text = f"Готово: {stats.summary()}"
        if self._ocr_requested and not stats.ocr_available and stats.without_text:
            text += ". Часть файлов без текстового слоя (сканы) — нужен Tesseract."
        self.status.setText(text)
        self.problems_btn.setVisible(
            bool(stats.errors or stats.no_text_files or stats.skipped_files)
        )

    def _on_error(self, message: str):
        """Показать ошибку поиска."""
        self.status.setText("Поиск не выполнен")
        self._show_error(message)

    def _on_finished(self):
        """Вернуть кнопки в исходное состояние."""
        self._worker = None
        self.stop_btn.setEnabled(False)
        self.export_btn.setEnabled(bool(self._hits))
        self.progress.setRange(0, 1)
        self.progress.setValue(1)
        self._update_start_enabled()
        self.results.setSortingEnabled(True)
        self.results.sortByColumn(COL_WHERE, Qt.SortOrder.AscendingOrder)

    def _show_problems(self):
        """Список файлов без текста, ошибок и пропущенных файлов."""
        stats = self._stats
        lines = []
        if stats.errors:
            lines.append(f"Ошибки ({stats.failed}):")
            lines += [f"  {path}\n      {reason}" for path, reason in stats.errors]
        if stats.no_text_files:
            lines.append(f"\nФайлы без текста ({stats.without_text}):")
            lines += [f"  {path}" for path in stats.no_text_files]
        if stats.skipped_files:
            lines.append(f"\nПропущено — файл больше лимита ({stats.skipped}):")
            lines += [f"  {path}" for path in stats.skipped_files]
        box = QMessageBox(self)
        box.setWindowTitle("Файлы без текста / ошибки")
        box.setText(
            f"Ошибок: {stats.failed}; без текста: {stats.without_text}; пропущено: {stats.skipped}"
        )
        box.setDetailedText("\n".join(lines))
        box.exec()

    @property
    def stats(self):
        """Статистика последнего прогона."""
        return self._stats

    @property
    def hits(self):
        """Совпадения, полученные к этому моменту."""
        return list(self._hits)

    def _activate(self, index: QModelIndex):
        """Двойной щелчок: открыть файл или раскрыть/свернуть группу файла."""
        source = self.proxy.mapToSource(index)
        if self.model.kind_at(source) is NodeKind.FILE:
            self.results.setExpanded(index, not self.results.isExpanded(index))
            return
        hit = self.model.hit_at(source)
        if hit is not None:
            self.open_hit(hit)

    def open_hit(self, hit: SearchHit):
        """Открыть файл программой по умолчанию; файл из архива — из временной копии."""
        target = hit.real_path
        if ARCHIVE_SEPARATOR in hit.display_path:
            folder = Path(tempfile.mkdtemp(prefix=TEMP_PREFIX))
            self._temp_copies.append(folder)
            try:
                target = extract_chain(hit.display_path, folder)
            except Exception as exc:
                self._show_error(f"Не удалось извлечь файл из архива: {exc}")
                return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(target))):
            self._show_error(f"Не удалось открыть {target}")

    def _export(self):
        """Сохранить видимые (отфильтрованные) строки в CSV."""
        name, _ = QFileDialog.getSaveFileName(
            self, "Экспорт результатов", "search_results.csv", "CSV (*.csv)"
        )
        if not name:
            return
        hits = self.proxy.visible_hits()
        try:
            export_csv(hits, Path(name))
        except OSError as exc:
            self._show_error(f"Не удалось записать файл: {exc}")
            return
        self.status.setText(f"Экспортировано строк: {len(hits)} — {name}")

    def closeEvent(self, event: QCloseEvent):
        """Остановить поиск и удалить временные копии при закрытии окна."""
        if self._worker is not None:
            self._worker.detach()
        for folder in self._temp_copies:
            shutil.rmtree(folder, ignore_errors=True)
        super().closeEvent(event)
