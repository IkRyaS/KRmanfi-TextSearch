import re
from pathlib import Path

import pytest
from PySide6.QtCore import QtMsgType, qInstallMessageHandler
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QWidget

from krmanfi_search.presentation import theme
from krmanfi_search.presentation.theme import AMBER, RED, SLATE, STYLESHEET, TEAL

SOURCES = Path(theme.__file__).parent
HEX = re.compile(r"^#[0-9a-f]{6}$")


@pytest.mark.parametrize("palette", [TEAL, SLATE])
def test_scales_have_all_ten_steps_in_hex(palette):
    assert list(palette) == [50, 100, 200, 300, 400, 500, 600, 700, 800, 900]
    assert all(HEX.match(value) for value in palette.values())


@pytest.mark.parametrize("palette", [TEAL, SLATE])
def test_scales_get_darker_step_by_step(palette):
    def brightness(value):
        return sum(int(value[i : i + 2], 16) for i in (1, 3, 5))

    levels = [brightness(palette[key]) for key in sorted(palette)]
    assert levels == sorted(levels, reverse=True)


@pytest.mark.parametrize("palette", [AMBER, RED])
def test_alert_palettes_define_three_colours(palette):
    assert set(palette) == {"bg", "border", "text"}
    assert all(HEX.match(value) for value in palette.values())


def test_highlight_colours_are_valid():
    assert theme.HIGHLIGHT_FILL.isValid() and theme.HIGHLIGHT_LINE.isValid()
    assert theme.FILE_ROW_BG.isValid() and theme.PAGE_ROW_BG.isValid()


def test_stylesheet_has_no_leftover_format_markers():
    assert "{{" not in STYLESHEET and "}}" not in STYLESHEET
    assert not re.search(r"\{[A-Z]+\[", STYLESHEET)
    assert STYLESHEET.count("{") == STYLESHEET.count("}")


def test_stylesheet_uses_only_palette_colours():
    colours = set(re.findall(r"#[0-9a-fA-F]{6}\b", STYLESHEET))
    allowed = {c.lower() for p in (TEAL, SLATE) for c in p.values()}
    allowed |= {v for p in (AMBER, RED) for v in p.values()} | {"#ffffff"}
    assert {c.lower() for c in colours} <= allowed


def object_names():
    names = set()
    for source in ("main_window.py", "page_preview.py"):
        text = (SOURCES / source).read_text(encoding="utf-8")
        names |= set(re.findall(r'setObjectName\("([A-Za-z]+)"\)', text))
    return names


def test_every_object_name_used_in_widgets_is_styled():
    missing = {name for name in object_names() if f"#{name}" not in STYLESHEET}
    assert not missing, missing


def test_stylesheet_is_accepted_by_qt(qapp):
    messages = []

    def handler(kind, context, message):
        if kind in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg):
            messages.append(message)

    previous = qInstallMessageHandler(handler)
    try:
        widget = QWidget()
        QLabel("текст", widget)
        QPushButton("кнопка", widget)
        widget.setStyleSheet(STYLESHEET)
        widget.ensurePolished()
        widget.show()
        QApplication.processEvents()
        widget.close()
    finally:
        qInstallMessageHandler(previous)
    assert not [m for m in messages if "parse" in m.lower() or "unknown property" in m.lower()]
