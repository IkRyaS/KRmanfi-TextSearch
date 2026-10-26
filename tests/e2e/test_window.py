import csv
from pathlib import Path

import pytest
from PySide6.QtCore import QModelIndex

from krmanfi_search.container import Container
from krmanfi_search.infrastructure.config import Settings
from krmanfi_search.presentation.main_window import SearchWindow
from krmanfi_search.presentation.results_model import NodeKind
from tests.conftest import PHRASE, needs_tesseract

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


def test_find_button_needs_text_and_path(qtbot, window):
    assert not window.start_btn.isEnabled()
    window.query.setText("слово")
    assert window.start_btn.isEnabled()
    window.path_edit.setText("")
    assert not window.start_btn.isEnabled()


def test_results_form_file_page_hit_tree(qtbot, window):
    run(qtbot, window)
    assert window.hits and window.export_btn.isEnabled()
    top = [window.model.index(r, 0) for r in range(window.model.rowCount())]
    assert all(window.model.kind_at(i) is NodeKind.FILE for i in top)
    pdf = next(i for i in top if window.model.data(i).startswith("03_повторы"))
    group = window.model.index(0, 0, pdf)
    assert window.model.kind_at(group) is NodeKind.PAGE
    assert window.model.rowCount(group) == 3


def test_summary_line_reports_numbers(qtbot, window):
    run(qtbot, window)
    text = window.status.text()
    assert "найдено" in text and "просмотрено" in text and "без текста" in text and "ошибок" in text


def test_filter_keeps_matching_rows_only(qtbot, window):
    run(qtbot, window)
    total = len(window.proxy.visible_hits())
    window.result_filter.setText("xlsx")
    visible = window.proxy.visible_hits()
    assert 0 < len(visible) < total
    assert all(h.display_path.endswith(".xlsx") for h in visible)


def test_export_writes_only_visible_rows(qtbot, window, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog

    run(qtbot, window)
    window.result_filter.setText("csv")
    target = tmp_path / "out.csv"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), ""))
    window._export()
    rows = list(csv.reader(target.read_text(encoding="utf-8-sig").splitlines()))
    assert len(rows) == 2 and rows[1][0].endswith("09_данные.csv")


def test_invalid_regex_shows_message_and_keeps_window_alive(qtbot, window):
    window.mode.setCurrentText("Регулярное выражение")
    run(qtbot, window, "(")
    assert "Некорректное регулярное выражение" in window.error_label.text()
    assert window.start_btn.isEnabled() and not window.hits


def test_missing_folder_is_reported(qtbot, window):
    window.path_edit.setText("/нет/такой/папки")
    run(qtbot, window, "слово")
    assert "не существует" in window.error_label.text()


def test_second_run_replaces_previous_results(qtbot, window):
    run(qtbot, window)
    first = len(window.hits)
    run(qtbot, window, "годовой")
    assert 0 < len(window.hits) < first
    assert window.model.rowCount() <= 2


def test_stop_cancels_running_search(qtbot, window, tmp_path):
    folder = tmp_path / "many"
    folder.mkdir()
    for i in range(400):
        (folder / f"{i}.txt").write_text("слово\n" * 5000, encoding="utf-8")
    window.path_edit.setText(str(folder))
    window.query.setText("слово")
    window.start()
    qtbot.waitUntil(lambda: len(window.hits) > 0, timeout=WAIT_MS)
    window.stop()
    qtbot.waitUntil(lambda: window._worker is None, timeout=WAIT_MS)
    assert window.status.text() == "Остановлено"
    assert window.start_btn.isEnabled()


def test_problems_button_appears_after_errors(qtbot, window, demo):
    window.path_edit.setText(str(demo / "для_проверки_ошибок"))
    run(qtbot, window)
    assert window.problems_btn.isVisibleTo(window)
    assert window.stats.failed == 3


def test_open_hit_from_archive_uses_temporary_copy(qtbot, window, demo, monkeypatch):
    from PySide6.QtGui import QDesktopServices

    opened = []
    monkeypatch.setattr(
        QDesktopServices, "openUrl", lambda url: opened.append(url.toLocalFile()) or True
    )
    window.path_edit.setText(str(demo / "архивы"))
    run(qtbot, window)
    hit = next(h for h in window.hits if h.display_path.endswith("заметка.txt"))
    window.open_hit(hit)
    assert Path(opened[0]).name == "заметка.txt" and "krmanfi-search-" in opened[0]
    window.close()
    assert not Path(opened[0]).exists()


def test_no_supported_files_message(qtbot, window, tmp_path):
    empty = tmp_path / "пусто"
    empty.mkdir()
    (empty / "x.bin").write_bytes(b"1")
    window.path_edit.setText(str(empty))
    run(qtbot, window, "слово")
    assert "подходящих файлов не найдено" in window.status.text()
    assert QModelIndex().isValid() is False


@needs_tesseract
def test_closing_window_during_ocr_stops_processes_and_cleans_temp(qtbot, demo, tmp_path):
    import multiprocessing
    import shutil
    import tempfile
    from pathlib import Path as P

    from PySide6.QtCore import QThreadPool

    folder = tmp_path / "много_сканов"
    folder.mkdir()
    for i in range(8):
        shutil.copy(demo / "сканы" / "19_повёрнутый_скан.pdf", folder / f"{i}.pdf")
    before = {p.name for p in P(tempfile.gettempdir()).glob("krmanfi-search-*")}
    win = SearchWindow(Container.build(Settings(workers=2)), folder)
    qtbot.addWidget(win)
    win.show()
    win.query.setText("слово")
    win.start()
    qtbot.waitUntil(
        lambda: "/" in win.status.text() and bool(multiprocessing.active_children()),
        timeout=WAIT_MS,
    )
    win.close()
    assert QThreadPool.globalInstance().waitForDone(20_000)
    qtbot.waitUntil(lambda: not multiprocessing.active_children(), timeout=20_000)
    after = {p.name for p in P(tempfile.gettempdir()).glob("krmanfi-search-*")}
    assert after <= before
