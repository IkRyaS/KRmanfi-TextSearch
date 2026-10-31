import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QPushButton

from krmanfi_search.infrastructure.search.preview import PagePreview
from krmanfi_search.presentation import page_preview
from krmanfi_search.presentation.page_preview import (
    MIN_WIDTH,
    ZOOM_STEP,
    PagePreviewDialog,
    paint_highlights,
)
from tests.helpers import solid_png


def make_preview(boxes=(), note="", width=400, height=300):
    return PagePreview(solid_png(width, height), width, height, tuple(boxes), note)


def pixel(pixmap, x, y):
    return QColor(pixmap.toImage().pixel(x, y))


def button(dialog, text):
    return next(b for b in dialog.findChildren(QPushButton) if b.text() == text)


@pytest.fixture
def dialog(qtbot):
    widget = PagePreviewDialog(None, "отчёт.pdf", "стр. 2")
    widget.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
    qtbot.addWidget(widget)
    widget.show()
    return widget


def test_painting_without_boxes_leaves_the_page_untouched(qapp):
    pixmap = paint_highlights(make_preview())
    assert (pixmap.width(), pixmap.height()) == (400, 300)
    assert pixel(pixmap, 100, 100) == QColor("white")


def test_painting_marks_inside_and_leaves_outside(qapp):
    pixmap = paint_highlights(make_preview([(100, 100, 200, 130)]))
    inside, outside = pixel(pixmap, 150, 115), pixel(pixmap, 300, 250)
    assert outside == QColor("white")
    assert inside.blue() < 150 and inside.red() > 200


def test_painting_keeps_the_picture_size(qapp):
    boxes = [(10, 10, 60, 30), (200, 200, 390, 290)]
    pixmap = paint_highlights(make_preview(boxes))
    assert (pixmap.width(), pixmap.height()) == (400, 300)


def test_boxes_near_the_edge_do_not_break_painting(qapp):
    pixmap = paint_highlights(make_preview([(-5, -5, 20, 20), (380, 280, 420, 320)]))
    assert pixmap.width() == 400


def test_highlight_is_multiplied_so_text_stays_readable(qapp):
    image = QImage(200, 100, QImage.Format.Format_RGB32)
    image.fill(QColor("white"))
    for x in range(40, 60):
        image.setPixelColor(x, 50, QColor("black"))
    from PySide6.QtCore import QBuffer, QByteArray

    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QBuffer.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    result = paint_highlights(PagePreview(bytes(data), 200, 100, ((30, 40, 80, 60),)))
    assert pixel(result, 50, 50).value() < 40


def test_new_dialog_says_it_is_preparing(dialog):
    assert dialog.windowTitle() == "отчёт.pdf — стр. 2"
    assert dialog._count.text() == "Готовлю страницу…"
    assert not dialog._notice.isVisible()


def test_preview_with_boxes_shows_their_number(dialog):
    dialog.show_preview(make_preview([(10, 10, 50, 30), (10, 60, 50, 80)]))
    assert dialog._count.text() == "Выделено фрагментов на странице: 2"
    assert not dialog._notice.isVisible()
    assert dialog._image.pixmap() is not None


def test_preview_without_boxes_says_so(dialog):
    dialog.show_preview(make_preview())
    assert dialog._count.text() == "Совпадения не выделены"


def test_note_is_shown_when_present(dialog):
    dialog.show_preview(make_preview(note="Tesseract не найден"))
    assert dialog._notice.isVisible() and dialog._notice.text() == "Tesseract не найден"
    dialog.show_preview(make_preview())
    assert not dialog._notice.isVisible()


def test_error_replaces_the_page_with_a_message(dialog):
    dialog.show_error("PDF зашифрован паролем")
    assert dialog._count.text() == "Страницу показать не удалось"
    assert dialog._notice.isVisible() and dialog._notice.text() == "PDF зашифрован паролем"
    assert dialog._notice.objectName() == "error"


def test_zoom_in_and_out_change_the_factor(dialog):
    dialog.show_preview(make_preview())
    start = dialog._current_factor()
    dialog._zoom(ZOOM_STEP)
    assert dialog._factor == pytest.approx(start * ZOOM_STEP)
    dialog._zoom(1 / ZOOM_STEP)
    assert dialog._factor == pytest.approx(start)


def test_zoom_is_clamped(dialog):
    dialog.show_preview(make_preview())
    for _ in range(40):
        dialog._zoom(ZOOM_STEP)
    assert dialog._factor == 3.0
    for _ in range(80):
        dialog._zoom(1 / ZOOM_STEP)
    assert dialog._factor == 0.1


def test_zoom_before_a_page_is_loaded_does_nothing(dialog):
    dialog._zoom(ZOOM_STEP)
    dialog._fit()
    assert dialog._factor is None and dialog._image.pixmap().isNull()


def test_fit_resets_manual_zoom(dialog):
    dialog.show_preview(make_preview())
    dialog._zoom(2.0)
    button(dialog, "По ширине").click()
    assert dialog._factor is None


def test_scaled_image_is_never_narrower_than_minimum(dialog):
    dialog.show_preview(make_preview(width=800, height=600))
    dialog._factor = 0.1
    dialog._apply_scale()
    assert dialog._image.pixmap().width() == max(int(800 * 0.1), MIN_WIDTH)


def test_resizing_the_window_refits_the_page(dialog, qtbot):
    dialog.show_preview(make_preview(width=1000, height=800))
    dialog.resize(600, 700)
    qtbot.waitUntil(lambda: dialog._image.pixmap().width() <= 600, timeout=3000)
    dialog.resize(900, 700)
    qtbot.waitUntil(lambda: dialog._image.pixmap().width() > 600, timeout=3000)


def test_manual_zoom_survives_resizing(dialog):
    dialog.show_preview(make_preview(width=1000, height=800))
    dialog._zoom(1.0)
    width = dialog._image.pixmap().width()
    dialog.resize(500, 500)
    assert dialog._image.pixmap().width() == width


def test_open_button_emits_signal(dialog, qtbot):
    with qtbot.waitSignal(dialog.open_requested, timeout=1000):
        button(dialog, "Открыть файл целиком").click()


def test_close_button_closes_the_dialog(dialog):
    button(dialog, "Закрыть").click()
    assert not dialog.isVisible()


def test_buttons_do_not_steal_enter_key(dialog):
    assert not any(b.autoDefault() for b in dialog.findChildren(QPushButton))


def test_first_match_position_is_remembered_for_scrolling(dialog):
    dialog.show_preview(make_preview([(10, 200, 50, 220), (10, 50, 50, 70)]))
    assert dialog._first_y == 50


def test_module_constants_are_sane():
    assert ZOOM_STEP > 1 and MIN_WIDTH > 0 and page_preview.SCROLL_MARGIN >= 0
