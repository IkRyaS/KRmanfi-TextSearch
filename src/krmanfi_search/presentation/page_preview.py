from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QPainter, QPen, QPixmap, QResizeEvent
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from krmanfi_search.infrastructure.search.preview import PagePreview
from krmanfi_search.presentation.theme import HIGHLIGHT_FILL, HIGHLIGHT_LINE, SLATE

ZOOM_STEP = 1.25
MIN_WIDTH = 200
SCROLL_MARGIN = 140


def paint_highlights(preview: PagePreview):
    """Страница в виде картинки с жёлтой подсветкой и тонкой рамкой вокруг совпадений."""
    pixmap = QPixmap()
    pixmap.loadFromData(preview.png, "PNG")
    if not preview.boxes:
        return pixmap
    pad = max(2.0, pixmap.width() / 450)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    rects = [
        QRectF(x0 - pad, y0 - pad, x1 - x0 + 2 * pad, y1 - y0 + 2 * pad)
        for x0, y0, x1, y1 in preview.boxes
    ]
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Multiply)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(HIGHLIGHT_FILL))
    for rect in rects:
        painter.drawRoundedRect(rect, pad, pad)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
    painter.setPen(QPen(HIGHLIGHT_LINE, max(1.5, pad / 2)))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    for rect in rects:
        painter.drawRoundedRect(rect, pad, pad)
    painter.end()
    return pixmap


class PagePreviewDialog(QDialog):
    """Страница документа с подсветкой; можно приблизить и открыть файл целиком."""

    open_requested = Signal()

    def __init__(self, parent: QWidget, title: str, place: str):
        """Создать окно в состоянии «Готовлю страницу…».

        Args:
            parent: Главное окно.
            title: Имя файла.
            place: Страница или место в файле.
        """
        super().__init__(parent)
        self.setWindowTitle(f"{title} — {place}")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.resize(940, 900)
        self._pixmap = None
        self._first_y = 0
        self._factor = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)
        self._title = QLabel(f"{title} · {place}")
        self._title.setObjectName("cardTitle")
        self._count = QLabel("Готовлю страницу…")
        self._count.setObjectName("hint")
        layout.addWidget(self._title)
        layout.addWidget(self._count)
        self._notice = QLabel("")
        self._notice.setObjectName("notice")
        self._notice.setWordWrap(True)
        self._notice.setVisible(False)
        layout.addWidget(self._notice)
        self._image = QLabel("")
        self._image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._scroll = QScrollArea()
        self._scroll.setWidget(self._image)
        self._scroll.setWidgetResizable(False)
        self._scroll.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self._scroll.setStyleSheet(
            f"QScrollArea {{ background: {SLATE[200]}; border-radius: 10px; }}"
        )
        layout.addWidget(self._scroll, 1)
        layout.addLayout(self._build_buttons())

    def _build_buttons(self):
        """Масштаб слева, «Открыть файл» и «Закрыть» справа."""
        row = QHBoxLayout()
        row.setSpacing(8)
        out_btn = QPushButton("−")
        in_btn = QPushButton("+")
        fit_btn = QPushButton("По ширине")
        for button in (out_btn, in_btn):
            button.setFixedWidth(44)
        out_btn.clicked.connect(lambda: self._zoom(1 / ZOOM_STEP))
        in_btn.clicked.connect(lambda: self._zoom(ZOOM_STEP))
        fit_btn.clicked.connect(self._fit)
        open_btn = QPushButton("Открыть файл целиком")
        open_btn.clicked.connect(self.open_requested.emit)
        close_btn = QPushButton("Закрыть")
        close_btn.setObjectName("primary")
        close_btn.clicked.connect(self.close)
        for button in (out_btn, in_btn, fit_btn):
            row.addWidget(button)
        row.addStretch(1)
        row.addWidget(open_btn)
        row.addWidget(close_btn)
        for button in (out_btn, in_btn, fit_btn, open_btn, close_btn):
            button.setAutoDefault(False)
        return row

    def show_preview(self, preview: object):
        """Показать готовую страницу."""
        assert isinstance(preview, PagePreview)
        self._pixmap = paint_highlights(preview)
        self._first_y = min((box[1] for box in preview.boxes), default=0)
        count = len(preview.boxes)
        self._count.setText(
            f"Выделено фрагментов на странице: {count}" if count else "Совпадения не выделены"
        )
        self._notice.setText(preview.note)
        self._notice.setVisible(bool(preview.note))
        self._factor = None
        self._apply_scale(scroll_to_first=True)

    def show_error(self, message: str):
        """Показать причину, по которой страницу не удалось подготовить."""
        self._count.setText("Страницу показать не удалось")
        self._notice.setObjectName("error")
        self._notice.style().unpolish(self._notice)
        self._notice.style().polish(self._notice)
        self._notice.setText(message)
        self._notice.setVisible(True)

    def _current_factor(self):
        """Текущий масштаб картинки относительно оригинала."""
        if self._pixmap is None:
            return 1.0
        if self._factor is not None:
            return self._factor
        width = max(self._scroll.viewport().width() - 4, MIN_WIDTH)
        return width / self._pixmap.width()

    def _zoom(self, ratio: float):
        """Приблизить или отдалить."""
        if self._pixmap is None:
            return
        self._factor = min(max(self._current_factor() * ratio, 0.1), 3.0)
        self._apply_scale()

    def _fit(self):
        """Подогнать страницу по ширине окна."""
        self._factor = None
        self._apply_scale()

    def _apply_scale(self, scroll_to_first: bool = False):
        """Перерисовать картинку в нужном масштабе."""
        if self._pixmap is None:
            return
        factor = self._current_factor()
        width = max(int(self._pixmap.width() * factor), MIN_WIDTH)
        scaled = self._pixmap.scaledToWidth(width, Qt.TransformationMode.SmoothTransformation)
        self._image.setPixmap(scaled)
        self._image.resize(scaled.size())
        if scroll_to_first:
            target = int(self._first_y * factor) - SCROLL_MARGIN
            QTimer.singleShot(0, lambda: self._scroll.verticalScrollBar().setValue(max(target, 0)))

    def resizeEvent(self, event: QResizeEvent):
        """При изменении размера окна подгонять страницу по ширине."""
        super().resizeEvent(event)
        if self._factor is None:
            self._apply_scale()
