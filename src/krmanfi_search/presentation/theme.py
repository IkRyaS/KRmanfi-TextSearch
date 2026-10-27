"""Оформление: один цвет в разных оттенках (бирюзовый) и нейтральные серо-синие тона."""

from __future__ import annotations

from PySide6.QtGui import QColor

TEAL = {
    50: "#f0fdfa",
    100: "#ccfbf1",
    200: "#99f6e4",
    300: "#5eead4",
    400: "#2dd4bf",
    500: "#14b8a6",
    600: "#0d9488",
    700: "#0f766e",
    800: "#115e59",
    900: "#134e4a",
}
SLATE = {
    50: "#f8fafc",
    100: "#f1f5f9",
    200: "#e2e8f0",
    300: "#cbd5e1",
    400: "#94a3b8",
    500: "#64748b",
    600: "#475569",
    700: "#334155",
    800: "#1e293b",
    900: "#0f172a",
}
AMBER = {"bg": "#fef3c7", "border": "#fcd34d", "text": "#92400e"}
RED = {"bg": "#fee2e2", "border": "#fca5a5", "text": "#991b1b"}

HIGHLIGHT_FILL = QColor("#fde047")
HIGHLIGHT_LINE = QColor("#d97706")
FILE_ROW_BG = QColor(TEAL[50])
PAGE_ROW_BG = QColor(SLATE[50])
FILE_ROW_FG = QColor(TEAL[900])

STYLESHEET = f"""
* {{
    font-family: "Segoe UI", "Noto Sans", "Ubuntu", "DejaVu Sans", sans-serif;
    font-size: 10pt;
    color: {SLATE[800]};
}}
QMainWindow, QWidget#root {{ background: {SLATE[100]}; }}

QFrame#header {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {TEAL[900]}, stop:1 {TEAL[700]});
}}
QLabel#title {{ color: white; font-size: 17pt; font-weight: 600; }}
QLabel#subtitle {{ color: {TEAL[100]}; font-size: 10pt; }}

QFrame#card {{
    background: white;
    border: 1px solid {SLATE[200]};
    border-radius: 12px;
}}
QLabel#step {{
    background: {TEAL[100]};
    color: {TEAL[800]};
    border-radius: 12px;
    font-weight: 700;
    min-width: 24px; max-width: 24px; min-height: 24px; max-height: 24px;
    qproperty-alignment: AlignCenter;
}}
QLabel#cardTitle {{ font-weight: 600; color: {SLATE[700]}; }}
QLabel#hint {{ color: {SLATE[500]}; }}

QLineEdit {{
    background: {SLATE[50]};
    border: 1px solid {SLATE[300]};
    border-radius: 8px;
    padding: 8px 10px;
    selection-background-color: {TEAL[200]};
    selection-color: {TEAL[900]};
}}
QLineEdit:hover {{ border-color: {TEAL[300]}; }}
QLineEdit:focus {{ background: white; border: 2px solid {TEAL[500]}; padding: 7px 9px; }}
QLineEdit#bigQuery {{ font-size: 12pt; padding: 10px 12px; }}
QLineEdit#bigQuery:focus {{ padding: 9px 11px; }}

QPushButton {{
    background: white;
    border: 1px solid {SLATE[300]};
    border-radius: 8px;
    padding: 8px 14px;
    color: {SLATE[700]};
}}
QPushButton:hover {{ background: {TEAL[50]}; border-color: {TEAL[300]}; color: {TEAL[800]}; }}
QPushButton:pressed {{ background: {TEAL[100]}; }}
QPushButton:disabled {{ background: {SLATE[100]}; color: {SLATE[400]}; border-color: {SLATE[200]}; }}
QPushButton:focus {{ border-color: {TEAL[500]}; }}

QPushButton#primary {{
    background: {TEAL[600]};
    border: 1px solid {TEAL[700]};
    color: white;
    font-weight: 600;
    padding: 10px 28px;
    font-size: 11pt;
}}
QPushButton#primary:hover {{ background: {TEAL[500]}; border-color: {TEAL[600]}; color: white; }}
QPushButton#primary:pressed {{ background: {TEAL[700]}; }}
QPushButton#primary:disabled {{ background: {TEAL[100]}; border-color: {TEAL[100]}; color: {TEAL[400]}; }}

QPushButton#danger {{ color: {RED['text']}; }}
QPushButton#danger:hover {{ background: {RED['bg']}; border-color: {RED['border']}; color: {RED['text']}; }}
QPushButton#danger:disabled {{ color: {SLATE[400]}; }}

QPushButton#link {{
    background: transparent; border: none; color: {TEAL[700]}; padding: 4px 8px;
}}
QPushButton#link:hover {{ background: {TEAL[50]}; color: {TEAL[900]}; }}

QCheckBox {{ spacing: 8px; padding: 4px 2px; }}
QCheckBox::indicator {{
    width: 18px; height: 18px; border-radius: 5px;
    border: 1px solid {SLATE[400]}; background: white;
}}
QCheckBox::indicator:hover {{ border-color: {TEAL[500]}; }}
QCheckBox::indicator:checked {{ background: {TEAL[600]}; border: 4px solid {TEAL[600]}; }}
QCheckBox::indicator:checked:hover {{ background: {TEAL[500]}; border-color: {TEAL[500]}; }}

QProgressBar {{ background: {SLATE[200]}; border: none; border-radius: 3px; max-height: 6px; min-height: 6px; }}
QProgressBar::chunk {{ background: {TEAL[500]}; border-radius: 3px; }}

QLabel#status {{ color: {SLATE[600]}; }}
QLabel#notice {{
    background: {AMBER['bg']}; color: {AMBER['text']};
    border: 1px solid {AMBER['border']}; border-radius: 8px; padding: 8px 12px;
}}
QLabel#error {{
    background: {RED['bg']}; color: {RED['text']};
    border: 1px solid {RED['border']}; border-radius: 8px; padding: 8px 12px;
}}
QLabel#empty {{ color: {SLATE[500]}; font-size: 11pt; }}
QLabel#emptyIcon {{ color: {TEAL[300]}; font-size: 40pt; }}

QTreeView {{
    background: white;
    alternate-background-color: white;
    border: 1px solid {SLATE[200]};
    border-radius: 12px;
    outline: none;
    padding: 4px;
}}
QTreeView::item {{ padding: 5px 4px; border-radius: 4px; }}
QTreeView::item:hover {{ background: {TEAL[50]}; }}
QTreeView::item:selected {{ background: {TEAL[100]}; color: {TEAL[900]}; }}
QHeaderView::section {{
    background: white; color: {SLATE[500]};
    border: none; border-bottom: 1px solid {SLATE[200]};
    padding: 8px 6px; font-weight: 600;
}}

QScrollBar:vertical {{ background: transparent; width: 12px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {SLATE[300]}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {TEAL[400]}; }}
QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {SLATE[300]}; border-radius: 4px; min-width: 30px; }}
QScrollBar::handle:horizontal:hover {{ background: {TEAL[400]}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}

QToolTip {{
    background: {SLATE[800]}; color: white; border: none; padding: 6px 8px;
}}
QMenu {{ background: white; border: 1px solid {SLATE[200]}; border-radius: 8px; padding: 4px; }}
QMenu::item {{ padding: 8px 18px; border-radius: 6px; }}
QMenu::item:selected {{ background: {TEAL[100]}; color: {TEAL[900]}; }}
"""
