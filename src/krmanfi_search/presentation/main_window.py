"""Главное окно: два шага (где и что искать), потоковые результаты, фильтр и экспорт."""

from __future__ import annotations

import shutil
import tempfile
import time
from pathlib import Path

from PySide6.QtCore import QModelIndex, Qt, QUrl
from PySide6.QtGui import (
    QCloseEvent,
    QDesktopServices,
    QDragEnterEvent,
    QDropEvent,
    QKeySequence,
    QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from krmanfi_search.container import Container
from krmanfi_search.domain import SearchHit, SearchMode, SearchQuery, SearchStats
from krmanfi_search.infrastructure.archives import extract_chain
from krmanfi_search.infrastructure.search.exporter import export_csv
from krmanfi_search.infrastructure.search.matchers import make_matcher
from krmanfi_search.infrastructure.search.preview import build_preview
from krmanfi_search.infrastructure.search.service import ARCHIVE_SEPARATOR, TEMP_PREFIX
from krmanfi_search.presentation.page_preview import PagePreviewDialog
from krmanfi_search.presentation.results_model import (
    COL_CONTEXT,
    COL_WHERE,
    NodeKind,
    SearchResultsModel,
    SearchResultsProxy,
    file_label,
    location_label,
)
from krmanfi_search.presentation.workers import Emit, submit
from krmanfi_search.shared.types import CancelToken, ProgressCallback

WINDOW_TITLE = "Поиск по документам"
ETA_MIN_ELAPSED = 5.0
COLUMN_WIDTHS = (300, 240, 220)
FILE_FILTER = (
    "Документы и архивы (*.zip *.pdf *.docx *.xlsx *.pptx *.txt *.md *.log *.csv);;Все файлы (*)"
)
EMPTY_PAGE, RESULTS_PAGE = 0, 1
START_TEXT = ("Здесь появятся результаты", "Выберите папку, введите слово и нажмите «Найти»")
SEARCHING_TEXT = ("Ищу…", "Результаты появятся здесь, как только что-нибудь найдётся")


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


def _card():
    """Белая карточка с вертикальной раскладкой."""
    frame = QFrame()
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(18, 14, 18, 14)
    layout.setSpacing(10)
    return frame, layout


def _card_title(number: str, text: str):
    """Строка заголовка карточки: кружок с номером шага и подпись."""
    row = QHBoxLayout()
    row.setSpacing(10)
    badge = QLabel(number)
    badge.setObjectName("step")
    title = QLabel(text)
    title.setObjectName("cardTitle")
    row.addWidget(badge)
    row.addWidget(title)
    row.addStretch(1)
    return row


class SearchWindow(QMainWindow):
    """Окно приложения «Поиск по документам»."""

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
        self._last_query = None
        self.setWindowTitle(WINDOW_TITLE)
        self.setAcceptDrops(True)
        self.resize(1100, 780)
        self.setMinimumSize(860, 620)
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_header())
        body = QVBoxLayout()
        body.setContentsMargins(20, 16, 20, 16)
        body.setSpacing(12)
        outer.addLayout(body, 1)
        warning = container.ocr.status_text()
        self.ocr_label = QLabel(warning or "")
        self.ocr_label.setObjectName("notice")
        self.ocr_label.setWordWrap(True)
        self.ocr_label.setVisible(bool(warning))
        body.addWidget(self.ocr_label)
        body.addWidget(self._build_where_card(start_path))
        body.addWidget(self._build_what_card())
        body.addLayout(self._build_status_area())
        body.addWidget(self._build_results_area(), 1)
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)
        QShortcut(QKeySequence("Ctrl+F"), self, activated=self.query.setFocus)
        QShortcut(QKeySequence("Ctrl+Shift+F"), self, activated=self.query.setFocus)
        QShortcut(QKeySequence("Escape"), self, activated=self.stop)
        self._update_start_enabled()
        self.query.setFocus()

    def _build_header(self):
        """Цветная полоса с названием."""
        header = QFrame()
        header.setObjectName("header")
        layout = QVBoxLayout(header)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.setSpacing(2)
        title = QLabel(WINDOW_TITLE)
        title.setObjectName("title")
        subtitle = QLabel("PDF и сканы, Word, Excel, PowerPoint, текст и ZIP")
        subtitle.setObjectName("subtitle")
        layout.addWidget(title)
        layout.addWidget(subtitle)
        return header

    def _build_where_card(self, start_path: Path | None):
        """Шаг 1: папка или архив."""
        card, layout = _card()
        layout.addLayout(_card_title("1", "Где искать"))
        row = QHBoxLayout()
        row.setSpacing(8)
        self.path_edit = QLineEdit(str(start_path) if start_path else "")
        self.path_edit.setPlaceholderText("Папка или архив — можно перетащить сюда")
        self.path_edit.textChanged.connect(self._update_start_enabled)
        choose = QPushButton("Выбрать…")
        menu = QMenu(choose)
        menu.addAction("Папку…", self._choose_folder)
        menu.addAction("Файл или архив…", self._choose_file)
        choose.setMenu(menu)
        row.addWidget(self.path_edit, 1)
        row.addWidget(choose)
        layout.addLayout(row)
        return card

    def _build_what_card(self):
        """Шаг 2: слово, кнопки и четыре настройки."""
        card, layout = _card()
        layout.addLayout(_card_title("2", "Что искать"))
        row = QHBoxLayout()
        row.setSpacing(8)
        self.query = QLineEdit()
        self.query.setObjectName("bigQuery")
        self.query.setPlaceholderText("Слово, фраза или номер…")
        self.query.setClearButtonEnabled(True)
        self.query.returnPressed.connect(self.start)
        self.query.textChanged.connect(self._update_start_enabled)
        self.start_btn = QPushButton("Найти")
        self.start_btn.setObjectName("primary")
        self.start_btn.clicked.connect(self.start)
        self.stop_btn = QPushButton("Стоп")
        self.stop_btn.setObjectName("danger")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop)
        row.addWidget(self.query, 1)
        row.addWidget(self.start_btn)
        row.addWidget(self.stop_btn)
        layout.addLayout(row)
        options = QHBoxLayout()
        options.setSpacing(18)
        self.case = QCheckBox("Учитывать регистр")
        self.regex = QCheckBox("Регулярное выражение")
        self.ocr_pdf = QCheckBox("Распознавать сканы")
        self.ocr_pdf.setChecked(True)
        self.archives = QCheckBox("Искать в ZIP")
        self.archives.setChecked(True)
        for box in (self.case, self.regex, self.ocr_pdf, self.archives):
            options.addWidget(box)
        options.addStretch(1)
        layout.addLayout(options)
        return card

    def _build_status_area(self):
        """Тонкий индикатор, строка состояния, ошибка и кнопка проблем."""
        column = QVBoxLayout()
        column.setSpacing(6)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        column.addWidget(self.progress)
        row = QHBoxLayout()
        self.status = QLabel("")
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        self.problems_btn = QPushButton("Файлы без текста и ошибки…")
        self.problems_btn.setObjectName("link")
        self.problems_btn.setVisible(False)
        self.problems_btn.clicked.connect(self._show_problems)
        row.addWidget(self.status, 1)
        row.addWidget(self.problems_btn)
        column.addLayout(row)
        self.error_label = QLabel("")
        self.error_label.setObjectName("error")
        self.error_label.setWordWrap(True)
        self.error_label.setVisible(False)
        column.addWidget(self.error_label)
        return column

    def _build_results_area(self):
        """Пустое состояние или список результатов с панелью инструментов."""
        self.stack = QStackedWidget()
        empty = QWidget()
        empty_layout = QVBoxLayout(empty)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_title = QLabel(START_TEXT[0])
        self.empty_title.setObjectName("empty")
        self.empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_hint = QLabel(START_TEXT[1])
        self.empty_hint.setObjectName("hint")
        self.empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self.empty_title)
        empty_layout.addWidget(self.empty_hint)
        self.stack.addWidget(empty)
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(8)
        page_layout.addLayout(self._build_toolbar())
        page_layout.addWidget(self._build_tree(), 1)
        self.stack.addWidget(page)
        return self.stack

    def _build_toolbar(self):
        """Фильтр, раскрытие и экспорт."""
        row = QHBoxLayout()
        row.setSpacing(8)
        self.result_filter = QLineEdit()
        self.result_filter.setPlaceholderText("Сузить список: файл, страница или слово…")
        self.result_filter.setClearButtonEnabled(True)
        self.result_filter.textChanged.connect(self._filter_changed)
        self._expand_btn = QPushButton("Развернуть")
        self._expand_btn.setObjectName("link")
        self._collapse_btn = QPushButton("Свернуть")
        self._collapse_btn.setObjectName("link")
        self.export_btn = QPushButton("Сохранить в CSV…")
        self.export_btn.setEnabled(False)
        self.export_btn.clicked.connect(self._export)
        row.addWidget(self.result_filter, 1)
        row.addWidget(self._expand_btn)
        row.addWidget(self._collapse_btn)
        row.addWidget(self.export_btn)
        return row

    def _build_tree(self):
        """Дерево результатов."""
        self.model = SearchResultsModel()
        self.proxy = SearchResultsProxy()
        self.proxy.setSourceModel(self.model)
        self.results = QTreeView()
        self.results.setModel(self.proxy)
        self.results.setUniformRowHeights(True)
        self.results.setAlternatingRowColors(False)
        self.results.setIndentation(18)
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

    def _show_empty(self, texts: tuple[str, str]):
        """Показать пустое состояние: заголовок и пояснение."""
        self.empty_title.setText(texts[0])
        self.empty_hint.setText(texts[1])
        self.stack.setCurrentIndex(EMPTY_PAGE)

    def dragEnterEvent(self, event: QDragEnterEvent):
        """Принять перетаскивание папки или файла."""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        """Подставить перетащенный путь в поле «Где искать»."""
        urls = event.mimeData().urls()
        if urls and urls[0].isLocalFile():
            self.path_edit.setText(urls[0].toLocalFile())

    def _choose_folder(self):
        """Выбрать папку для поиска."""
        folder = QFileDialog.getExistingDirectory(self, "Папка для поиска", self.path_edit.text())
        if folder:
            self.path_edit.setText(folder)

    def _choose_file(self):
        """Выбрать архив или документ."""
        name, _ = QFileDialog.getOpenFileName(
            self, "Файл или архив", self.path_edit.text(), FILE_FILTER
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
            mode=SearchMode.REGEX if self.regex.isChecked() else SearchMode.SUBSTRING,
            case_sensitive=self.case.isChecked(),
            context_chars=settings.context_chars,
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
        self._last_query = query
        self._hits.clear()
        self.model.clear_hits()
        self._show_empty(SEARCHING_TEXT)
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
        if self.stack.currentIndex() != RESULTS_PAGE:
            self.stack.setCurrentIndex(RESULTS_PAGE)

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
            self._show_empty(("Нечего просматривать", "Здесь нет поддерживаемых файлов"))
        elif not count:
            text = f"Готово: совпадений нет. Просмотрено {stats.scanned} файлов; без текста — "
            text += f"{stats.without_text}; ошибок — {stats.failed}"
            self._show_empty(("Ничего не найдено", "Попробуйте другое слово или снимите галочки"))
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
        if not self._hits:
            self._show_empty(("Поиск не выполнен", "Причина указана выше"))

    def _on_finished(self):
        """Вернуть кнопки в исходное состояние."""
        self._worker = None
        self.stop_btn.setEnabled(False)
        self.export_btn.setEnabled(bool(self._hits))
        self.progress.setRange(0, 1)
        self.progress.setValue(1)
        self._update_start_enabled()
        if not self._hits and self.empty_title.text() == SEARCHING_TEXT[0]:
            self._show_empty(START_TEXT)
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
        box.setWindowTitle("Файлы без текста и ошибки")
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
            self.show_hit(hit)

    def show_hit(self, hit: SearchHit):
        """PDF — показать страницу с подсветкой; остальные форматы — открыть программой."""
        is_pdf = file_label(hit.display_path).lower().endswith(".pdf")
        if is_pdf and hit.page and self._last_query is not None:
            self._preview_page(hit, self._last_query)
        else:
            self.open_hit(hit)

    def _preview_page(self, hit: SearchHit, query: SearchQuery):
        """Окно со страницей PDF; картинка готовится в фоне, подсвечиваются все совпадения."""
        dialog = PagePreviewDialog(self, file_label(hit.display_path), location_label(hit))
        dialog.open_requested.connect(lambda: self.open_hit(hit))
        same_page = [
            h for h in self._hits if h.display_path == hit.display_path and h.page == hit.page
        ]
        fragments = [h.fragment for h in same_page]
        folder = None
        if ARCHIVE_SEPARATOR in hit.display_path:
            folder = Path(tempfile.mkdtemp(prefix=TEMP_PREFIX))
            self._temp_copies.append(folder)
        container = self._container
        scanned = "OCR" in hit.location

        def job(cancel: CancelToken, progress: ProgressCallback, emit: Emit):
            """Фоновая задача: достать файл из архива, нарисовать страницу, найти рамки."""
            del cancel, progress, emit
            pdf = extract_chain(hit.display_path, folder) if folder else hit.real_path
            return build_preview(
                pdf,
                hit.page or 1,
                fragments,
                make_matcher(query),
                container.ocr,
                container.settings.ocr.pdf_dpi,
                scanned,
            )

        worker = submit(job, owner=dialog, result=dialog.show_preview, error=dialog.show_error)
        dialog.finished.connect(lambda _code: worker.detach())
        dialog.show()

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
            self, "Сохранить результаты", "search_results.csv", "CSV (*.csv)"
        )
        if not name:
            return
        hits = self.proxy.visible_hits()
        try:
            export_csv(hits, Path(name))
        except OSError as exc:
            self._show_error(f"Не удалось записать файл: {exc}")
            return
        self.status.setText(f"Сохранено строк: {len(hits)} — {name}")

    def closeEvent(self, event: QCloseEvent):
        """Остановить поиск и удалить временные копии при закрытии окна."""
        if self._worker is not None:
            self._worker.detach()
        for folder in self._temp_copies:
            shutil.rmtree(folder, ignore_errors=True)
        super().closeEvent(event)
