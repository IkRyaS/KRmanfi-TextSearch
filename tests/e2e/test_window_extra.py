import tempfile
from pathlib import Path

import pytest
from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QFileDialog, QMessageBox

from krmanfi_search.container import Container
from krmanfi_search.infrastructure.config import Settings
from krmanfi_search.infrastructure.search.service import TEMP_PREFIX
from krmanfi_search.presentation import main_window
from krmanfi_search.presentation.main_window import SearchWindow, format_duration
from krmanfi_search.presentation.page_preview import PagePreviewDialog
from krmanfi_search.presentation.results_model import NodeKind
from tests.conftest import PHRASE, needs_tesseract
from tests.helpers import make_text_pdf, make_zip

WAIT_MS = 30_000


@pytest.fixture
def window(qtbot, demo):
    win = SearchWindow(Container.build(Settings(workers=0)), demo / "документы")
    qtbot.addWidget(win)
    win.ocr_pdf.setChecked(False)
    win.show()
    return win


def run(qtbot, win, text=PHRASE):
    win.query.setText(text)
    win.start()
    qtbot.waitUntil(lambda: win._worker is None and win.start_btn.isEnabled(), timeout=WAIT_MS)


def find_hit(win, name):
    return next(h for h in win.hits if h.display_path.endswith(name))


def mime_for(*urls):
    data = QMimeData()
    data.setUrls([QUrl(u) for u in urls])
    return data


@pytest.mark.parametrize(
    ("seconds", "text"),
    [
        (0, "0 с"),
        (0.9, "0 с"),
        (59, "59 с"),
        (60, "1 мин 00 с"),
        (190, "3 мин 10 с"),
        (3599, "59 мин 59 с"),
        (3600, "1 ч 00 мин"),
        (3905, "1 ч 05 мин"),
        (36000, "10 ч 00 мин"),
    ],
)
def test_format_duration(seconds, text):
    assert format_duration(seconds) == text


def test_window_title_and_initial_state(qtbot, window):
    assert window.windowTitle() == main_window.WINDOW_TITLE
    assert window.stack.currentIndex() == main_window.EMPTY_PAGE
    assert window.empty_title.text() == main_window.START_TEXT[0]
    assert not window.stop_btn.isEnabled() and not window.export_btn.isEnabled()
    assert not window.problems_btn.isVisible() and not window.error_label.isVisible()


def test_default_checkboxes(qtbot, window):
    assert not window.case.isChecked() and not window.regex.isChecked()
    assert window.archives.isChecked()


def test_start_path_is_put_into_the_field(qtbot, demo):
    win = SearchWindow(Container.build(Settings(workers=0)), demo)
    qtbot.addWidget(win)
    assert win.path_edit.text() == str(demo)


def test_window_without_start_path_has_empty_field(qtbot):
    win = SearchWindow(Container.build(Settings(workers=0)))
    qtbot.addWidget(win)
    assert win.path_edit.text() == "" and not win.start_btn.isEnabled()


def test_whitespace_only_text_keeps_button_disabled(qtbot, window):
    window.query.setText("   ")
    assert not window.start_btn.isEnabled()


def test_enter_in_query_field_starts_search(qtbot, window):
    window.query.setText(PHRASE)
    qtbot.keyClick(window.query, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: window._worker is None and bool(window.hits), timeout=WAIT_MS)
    assert window.hits


def test_escape_stops_a_running_search(qtbot, demo):
    win = SearchWindow(Container.build(Settings(workers=0)), demo)
    qtbot.addWidget(win)
    win.show()
    win.query.setText(PHRASE)
    win.start()
    qtbot.keyClick(win, Qt.Key.Key_Escape)
    qtbot.waitUntil(lambda: win._worker is None, timeout=WAIT_MS)
    assert win.start_btn.isEnabled()


def test_stop_without_running_search_is_harmless(qtbot, window):
    window.stop()
    assert window._worker is None


def test_starting_twice_does_not_create_second_worker(qtbot, window):
    window.query.setText(PHRASE)
    window.start()
    first = window._worker
    window.start()
    assert window._worker is first
    qtbot.waitUntil(lambda: window._worker is None, timeout=WAIT_MS)


def test_buttons_during_and_after_search(qtbot, window):
    window.query.setText(PHRASE)
    window.start()
    assert window.stop_btn.isEnabled() and not window.start_btn.isEnabled()
    qtbot.waitUntil(lambda: window._worker is None, timeout=WAIT_MS)
    assert not window.stop_btn.isEnabled() and window.start_btn.isEnabled()
    assert window.export_btn.isEnabled()


def test_results_page_replaces_empty_state(qtbot, window):
    run(qtbot, window)
    assert window.stack.currentIndex() == main_window.RESULTS_PAGE


def test_nothing_found_message_and_empty_state(qtbot, window):
    run(qtbot, window, "такого-слова-нет-нигде-qqq")
    assert "совпадений нет" in window.status.text()
    assert window.empty_title.text() == "Ничего не найдено"
    assert window.stack.currentIndex() == main_window.EMPTY_PAGE
    assert not window.export_btn.isEnabled()


def test_second_run_after_empty_result_shows_new_hits(qtbot, window):
    run(qtbot, window, "такого-слова-нет-нигде-qqq")
    run(qtbot, window, PHRASE)
    assert window.hits and window.stack.currentIndex() == main_window.RESULTS_PAGE


def test_case_sensitive_checkbox_changes_results(qtbot, window):
    run(qtbot, window, "КВАРТАЛЬНЫЙ ОТЧЁТ")
    insensitive = len(window.hits)
    window.case.setChecked(True)
    run(qtbot, window, "КВАРТАЛЬНЫЙ ОТЧЁТ")
    assert 0 < len(window.hits) < insensitive


def test_regex_checkbox_enables_patterns(qtbot, window):
    window.regex.setChecked(True)
    run(qtbot, window, r"\d{4}-К")
    assert {h.fragment for h in window.hits} == {"4711-К", "4712-К"}


def test_zip_checkbox_controls_archive_search(qtbot, demo):
    win = SearchWindow(Container.build(Settings(workers=0)), demo / "архивы")
    qtbot.addWidget(win)
    win.ocr_pdf.setChecked(False)
    win.archives.setChecked(False)
    run(qtbot, win)
    assert win.hits == [] and "подходящих файлов не найдено" in win.status.text()


def test_problems_button_lists_errors_without_text_and_skipped(qtbot, demo, monkeypatch):
    win = SearchWindow(Container.build(Settings(workers=0)), demo)
    qtbot.addWidget(win)
    win.ocr_pdf.setChecked(False)
    run(qtbot, win)
    shown = {}

    def fake_exec(box):
        shown["title"] = box.windowTitle()
        shown["text"] = box.text()
        shown["details"] = box.detailedText()
        return 0

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    win.problems_btn.click()
    assert shown["title"] == "Файлы без текста и ошибки"
    assert "Ошибки" in shown["details"] and "12_битый_архив.zip" in shown["details"]
    assert "Файлы без текста" in shown["details"]
    assert f"Ошибок: {win.stats.failed}" in shown["text"]


def test_hint_about_tesseract_when_scans_have_no_text(qtbot, demo, monkeypatch):
    from krmanfi_search.infrastructure.ocr import tesseract

    monkeypatch.setattr(tesseract, "find_tesseract", lambda explicit=None: None)
    win = SearchWindow(Container.build(Settings(workers=0)), demo / "сканы")
    qtbot.addWidget(win)
    assert not win.ocr_label.isHidden() and "Tesseract не найден" in win.ocr_label.text()
    run(qtbot, win)
    assert "нужен Tesseract" in win.status.text()


def test_ocr_warning_label_is_hidden_when_ocr_works(qtbot, window):
    from krmanfi_search.infrastructure.ocr import tesseract

    if tesseract.find_tesseract() is None:
        pytest.skip("Tesseract не установлен")
    assert not window.ocr_label.isVisible()


def test_progress_shows_estimate_after_a_while(qtbot, window):
    import time

    window._started = time.monotonic() - 100
    window._on_progress(10, 100, "файл.pdf")
    assert window.status.text().startswith("10/100 — файл.pdf")
    assert "осталось" in window.status.text()
    assert (window.progress.minimum(), window.progress.maximum(), window.progress.value()) == (
        0,
        100,
        10,
    )


def test_progress_has_no_estimate_at_the_start(qtbot, window):
    import time

    window._started = time.monotonic()
    window._on_progress(10, 100, "файл.pdf")
    assert "осталось" not in window.status.text()


def test_unknown_total_shows_busy_indicator(qtbot, window):
    window._on_progress(0, 0, "Сбор файлов…")
    assert window.progress.maximum() == 0
    assert window.status.text() == "0/? — Сбор файлов…"


def test_drop_of_local_folder_fills_the_path(qtbot, window, tmp_path):
    data = mime_for(QUrl.fromLocalFile(str(tmp_path)).toString())
    event = QDropEvent(
        QPointF(5, 5), Qt.DropAction.CopyAction, data, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    window.dropEvent(event)
    assert window.path_edit.text() == str(tmp_path)


def test_drop_of_remote_url_is_ignored(qtbot, window):
    before = window.path_edit.text()
    data = mime_for("https://example.com/file.pdf")
    event = QDropEvent(
        QPointF(5, 5), Qt.DropAction.CopyAction, data, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    window.dropEvent(event)
    assert window.path_edit.text() == before


def test_drag_enter_accepts_urls_only(qtbot, window):
    urls = mime_for("file:///tmp")
    accepted = QDragEnterEvent(
        QPoint(1, 1), Qt.DropAction.CopyAction, urls,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
    )
    accepted.ignore()
    window.dragEnterEvent(accepted)
    assert accepted.isAccepted()
    text = QMimeData()
    text.setText("просто текст")
    rejected = QDragEnterEvent(
        QPoint(1, 1), Qt.DropAction.CopyAction, text, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    rejected.ignore()
    window.dragEnterEvent(rejected)
    assert not rejected.isAccepted()


def test_choose_folder_sets_path_and_cancel_keeps_it(qtbot, window, tmp_path, monkeypatch):
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: str(tmp_path))
    window._choose_folder()
    assert window.path_edit.text() == str(tmp_path)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: "")
    window._choose_folder()
    assert window.path_edit.text() == str(tmp_path)


def test_choose_file_sets_path_and_cancel_keeps_it(qtbot, window, tmp_path, monkeypatch):
    target = tmp_path / "a.zip"
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(target), ""))
    window._choose_file()
    assert window.path_edit.text() == str(target)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: ("", ""))
    window._choose_file()
    assert window.path_edit.text() == str(target)


def test_build_query_reflects_form_and_settings(qtbot, window):
    window.query.setText("слово")
    window.case.setChecked(True)
    window.regex.setChecked(True)
    window.archives.setChecked(False)
    query = window.build_query()
    assert query.text == "слово" and query.case_sensitive and not query.include_archives
    assert query.mode.value == "regex" and not query.ocr_scanned_pdfs
    assert query.context_chars == 60 and query.max_file_size == 200 * 1024 * 1024


def test_build_query_expands_home_and_strips_spaces(qtbot, window):
    window.query.setText("слово")
    window.path_edit.setText("  ~/какая-то-папка  ")
    assert window.build_query().root == Path("~/какая-то-папка").expanduser()


def test_build_query_rejects_empty_text(qtbot, window):
    window.query.setText("")
    with pytest.raises(ValueError):
        window.build_query()


def test_filter_expands_results_and_clearing_restores(qtbot, window):
    run(qtbot, window)
    total = len(window.proxy.visible_hits())
    window.result_filter.setText("docx")
    assert len(window.proxy.visible_hits()) < total
    window.result_filter.setText("")
    assert len(window.proxy.visible_hits()) == total


def test_expand_and_collapse_buttons(qtbot, window):
    run(qtbot, window)
    window._collapse_btn.click()
    first = window.proxy.index(0, 0)
    assert not window.results.isExpanded(first)
    window._expand_btn.click()
    assert window.results.isExpanded(first)


def test_double_click_on_file_row_toggles_it(qtbot, window):
    run(qtbot, window)
    index = window.proxy.index(0, 0)
    assert window.model.kind_at(window.proxy.mapToSource(index)) is NodeKind.FILE
    expanded = window.results.isExpanded(index)
    window._activate(index)
    assert window.results.isExpanded(index) is not expanded


def test_sorting_is_applied_after_search(qtbot, window):
    run(qtbot, window)
    paths = [window.proxy.index(r, 1).data() for r in range(window.proxy.rowCount())]
    assert len(paths) > 3 and paths == sorted(paths, key=str.lower)


def test_show_hit_routes_pdf_to_preview(qtbot, window, monkeypatch):
    run(qtbot, window)
    calls = []
    monkeypatch.setattr(window, "_preview_page", lambda hit, query: calls.append(hit))
    window.show_hit(find_hit(window, "01_текстовый_слой.pdf"))
    assert len(calls) == 1


def test_show_hit_routes_other_formats_to_default_program(qtbot, window, monkeypatch):
    run(qtbot, window)
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url) or True)
    hit = find_hit(window, "04_протокол.docx")
    window.show_hit(hit)
    assert opened and opened[0].toLocalFile() == str(hit.real_path)
    assert not window.error_label.isVisible()


def test_open_failure_is_shown_in_the_window(qtbot, window, monkeypatch):
    run(qtbot, window)
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: False)
    window.open_hit(find_hit(window, "07_заметки.txt"))
    assert "Не удалось открыть" in window.error_label.text()


def test_open_from_broken_archive_member_reports_error(qtbot, window, tmp_path):
    from krmanfi_search.domain import SearchHit

    archive = make_zip(tmp_path / "a.zip", {"x.txt": "слово"})
    hit = SearchHit(
        display_path=f"{archive}!/нет_такого.txt",
        real_path=archive,
        location="строки 1–1",
        fragment="слово",
        context="слово",
        match_count=1,
    )
    window.open_hit(hit)
    assert "Не удалось извлечь файл из архива" in window.error_label.text()


def test_temp_copies_are_removed_on_close(qtbot, demo, monkeypatch):
    win = SearchWindow(Container.build(Settings(workers=0)), demo / "архивы")
    qtbot.addWidget(win)
    win.ocr_pdf.setChecked(False)
    win.show()
    run(qtbot, win)
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: True)
    before = set(Path(tempfile.gettempdir()).glob(f"{TEMP_PREFIX}*"))
    win.open_hit(win.hits[0])
    created = set(Path(tempfile.gettempdir()).glob(f"{TEMP_PREFIX}*")) - before
    assert created
    win.close()
    assert not any(p.exists() for p in created)


def test_closing_during_search_does_not_crash(qtbot, demo):
    win = SearchWindow(Container.build(Settings(workers=0)), demo)
    win.show()
    win.query.setText(PHRASE)
    win.start()
    win.close()
    qtbot.wait(500)


def test_pdf_preview_opens_with_highlights(qtbot, window):
    run(qtbot, window)
    window.show_hit(find_hit(window, "01_текстовый_слой.pdf"))
    dialog = window.findChild(PagePreviewDialog)
    assert dialog is not None and "01_текстовый_слой.pdf" in dialog.windowTitle()
    qtbot.waitUntil(lambda: dialog._pixmap is not None, timeout=WAIT_MS)
    assert dialog._count.text().startswith("Выделено фрагментов на странице:")
    dialog.close()


def test_preview_open_button_opens_the_file(qtbot, window, monkeypatch):
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url) or True)
    run(qtbot, window)
    window.show_hit(find_hit(window, "01_текстовый_слой.pdf"))
    dialog = window.findChild(PagePreviewDialog)
    qtbot.waitUntil(lambda: dialog._pixmap is not None, timeout=WAIT_MS)
    dialog.open_requested.emit()
    assert opened and opened[0].toLocalFile().endswith("01_текстовый_слой.pdf")
    dialog.close()


def test_preview_error_for_removed_file(qtbot, window):
    run(qtbot, window)
    hit = find_hit(window, "01_текстовый_слой.pdf")
    hit.real_path.unlink()
    window.show_hit(hit)
    dialog = window.findChild(PagePreviewDialog)
    qtbot.waitUntil(lambda: dialog._count.text() == "Страницу показать не удалось", timeout=WAIT_MS)
    assert dialog._notice.isVisible()
    dialog.close()


def test_preview_of_text_pdf_inside_archive(qtbot, tmp_path):
    pdf = make_text_pdf(tmp_path / "inner.pdf", ["alpha beta gamma"])
    make_zip(tmp_path / "a.zip", {"папка/inner.pdf": pdf.read_bytes()})
    pdf.unlink()
    win = SearchWindow(Container.build(Settings(workers=0)), tmp_path)
    qtbot.addWidget(win)
    win.ocr_pdf.setChecked(False)
    win.show()
    run(qtbot, win, "beta")
    win.show_hit(win.hits[0])
    dialog = win.findChild(PagePreviewDialog)
    qtbot.waitUntil(lambda: dialog._pixmap is not None, timeout=WAIT_MS)
    assert dialog._count.text() == "Выделено фрагментов на странице: 1"
    dialog.close()
    win.close()


@needs_tesseract
def test_scan_preview_in_nested_archive_marks_words(qtbot, demo):
    win = SearchWindow(Container.build(Settings(workers=0)), demo / "архивы")
    qtbot.addWidget(win)
    win.show()
    run(qtbot, win)
    hit = next(h for h in win.hits if "скан_во_вложенном.pdf" in h.display_path)
    win.show_hit(hit)
    dialog = win.findChild(PagePreviewDialog)
    qtbot.waitUntil(lambda: dialog._pixmap is not None, timeout=WAIT_MS * 2)
    assert dialog._count.text().startswith("Выделено фрагментов")
    dialog.close()
    win.close()
