from __future__ import annotations

from enum import StrEnum
from pathlib import PurePosixPath
from typing import override

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtGui import QBrush, QStandardItem, QStandardItemModel

from krmanfi_search.domain import SearchHit
from krmanfi_search.presentation.theme import FILE_ROW_BG, FILE_ROW_FG, PAGE_ROW_BG

type Index = QModelIndex | QPersistentModelIndex

HIT_ROLE = Qt.ItemDataRole.UserRole + 20
KIND_ROLE = Qt.ItemDataRole.UserRole + 21
SORT_ROLE = Qt.ItemDataRole.UserRole + 22

COL_WHERE = 0
COL_LOCATION = 1
COL_FRAGMENT = 2
COL_CONTEXT = 3
HEADERS = ("Файл", "Место", "Совпадение", "Контекст")


class NodeKind(StrEnum):
    """Вид строки дерева."""

    FILE = "file"
    PAGE = "page"
    HIT = "hit"


def file_label(display_path: str):
    """Короткое имя файла (внутри архива: ``a.zip!/d/b.pdf`` → ``b.pdf``)."""
    inner = display_path.rsplit("!/", 1)[-1].replace("\\", "/")
    return PurePosixPath(inner).name or display_path


def location_label(hit: SearchHit):
    """Подпись страницы, листа или слайда."""
    return hit.location or (f"стр. {hit.page}" if hit.page else "текст")


def _sort_key(hit: SearchHit):
    """Порядок чтения: файл, страница, подпись места."""
    return f"{hit.display_path.lower()}\x00{hit.page or 0:08d}\x00{hit.location}"


def _row():
    """Строка из пустых нередактируемых ячеек."""
    items = []
    for _ in HEADERS:
        item = QStandardItem()
        item.setEditable(False)
        items.append(item)
    return items


def _paint_file_row(row: list[QStandardItem]):
    """Строка файла: светлый бирюзовый фон, тёмный жирный текст."""
    for item in row:
        font = item.font()
        font.setBold(True)
        item.setFont(font)
        item.setBackground(QBrush(FILE_ROW_BG))
        item.setForeground(QBrush(FILE_ROW_FG))


def _paint_page_row(row: list[QStandardItem]):
    """Строка-группа страницы: еле заметный серо-голубой фон."""
    for item in row:
        item.setBackground(QBrush(PAGE_ROW_BG))


class SearchResultsModel(QStandardItemModel):
    """Результаты поиска; страница с несколькими вхождениями становится раскрывающейся группой."""

    def __init__(self):
        """Создать пустую модель."""
        super().__init__(0, len(HEADERS))
        self.setHorizontalHeaderLabels(list(HEADERS))
        self._hits = []
        self._files = {}
        self._pages = {}

    @property
    def hits(self):
        """Все совпадения в порядке поступления."""
        return list(self._hits)

    def hit_at(self, index: Index):
        """Совпадение строки (для группы — первое) или ``None``."""
        if not index.isValid():
            return None
        value = self.index(index.row(), 0, index.parent()).data(HIT_ROLE)
        return None if value is None else self._hits[int(value)]

    def kind_at(self, index: Index):
        """Вид строки."""
        if not index.isValid():
            return None
        value = self.index(index.row(), 0, index.parent()).data(KIND_ROLE)
        return NodeKind(value) if value else None

    def clear_hits(self):
        """Удалить все строки и совпадения."""
        self._hits.clear()
        self._files.clear()
        self._pages.clear()
        self.removeRows(0, self.rowCount())

    def add_hit(self, hit: SearchHit):
        """Добавить совпадение в дерево."""
        number = len(self._hits)
        self._hits.append(hit)
        parent = self._file_item(hit, number)
        key = (hit.display_path, hit.location, hit.page)
        entry = self._pages.get(key)
        if entry is None:
            row = self._hit_row(hit, number, location_label(hit))
            parent.appendRow(row)
            self._pages[key] = (row[COL_WHERE], False)
            return
        node, grouped = entry
        if not grouped:
            first_number = int(node.data(HIT_ROLE))
            first = self._hits[first_number]
            position = node.row()
            parent.takeRow(position)
            group = self._page_group(first, first_number)
            parent.insertRow(position, group)
            group[COL_WHERE].appendRow(self._hit_row(first, first_number, f"#{first.occurrence}"))
            node = group[COL_WHERE]
            self._pages[key] = (node, True)
        node.appendRow(self._hit_row(hit, number, f"#{hit.occurrence}"))

    def _file_item(self, hit: SearchHit, number: int):
        """Строка-группа файла (создаётся при первом совпадении)."""
        item = self._files.get(hit.display_path)
        if item is not None:
            return item
        row = _row()
        row[COL_WHERE].setText(file_label(hit.display_path))
        row[COL_WHERE].setToolTip(hit.display_path)
        row[COL_WHERE].setData(NodeKind.FILE.value, KIND_ROLE)
        row[COL_WHERE].setData(number, HIT_ROLE)
        row[COL_WHERE].setData(hit.display_path.lower(), SORT_ROLE)
        row[COL_LOCATION].setText(hit.display_path)
        _paint_file_row(row)
        self.invisibleRootItem().appendRow(row)
        self._files[hit.display_path] = row[COL_WHERE]
        return row[COL_WHERE]

    def _page_group(self, hit: SearchHit, number: int):
        """Группа страницы с несколькими вхождениями."""
        row = _row()
        row[COL_WHERE].setText(location_label(hit))
        row[COL_WHERE].setToolTip(f"{hit.display_path}\n{location_label(hit)}")
        row[COL_WHERE].setData(NodeKind.PAGE.value, KIND_ROLE)
        row[COL_WHERE].setData(number, HIT_ROLE)
        row[COL_WHERE].setData(_sort_key(hit), SORT_ROLE)
        row[COL_LOCATION].setText(location_label(hit))
        row[COL_FRAGMENT].setText(f"вхождений: {hit.match_count}")
        _paint_page_row(row)
        return row

    def _hit_row(self, hit: SearchHit, number: int, label: str):
        """Строка одного вхождения."""
        row = _row()
        row[COL_WHERE].setText(label)
        row[COL_WHERE].setToolTip(f"{hit.display_path}\n{location_label(hit)}")
        row[COL_WHERE].setData(NodeKind.HIT.value, KIND_ROLE)
        row[COL_WHERE].setData(number, HIT_ROLE)
        row[COL_WHERE].setData(f"{_sort_key(hit)}\x00{hit.offset:012d}", SORT_ROLE)
        row[COL_LOCATION].setText(location_label(hit))
        row[COL_FRAGMENT].setText(hit.fragment)
        row[COL_FRAGMENT].setToolTip(hit.fragment)
        row[COL_CONTEXT].setText(hit.context)
        row[COL_CONTEXT].setToolTip(hit.context)
        return row


class SearchResultsProxy(QSortFilterProxyModel):
    """Фильтр по всем столбцам, сохраняющий родителей подходящих строк."""

    def __init__(self):
        """Включить рекурсивную фильтрацию без учёта регистра."""
        super().__init__()
        self.setRecursiveFilteringEnabled(True)
        self.setAutoAcceptChildRows(True)
        self.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.setFilterKeyColumn(-1)
        self.setSortCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

    @override
    def lessThan(self, source_left: Index, source_right: Index):
        """Первый столбец сортируется по положению в документе."""
        if source_left.column() == COL_WHERE:
            left = source_left.data(SORT_ROLE)
            right = source_right.data(SORT_ROLE)
            if left is not None and right is not None:
                return str(left) < str(right)
        return super().lessThan(source_left, source_right)

    def visible_hits(self):
        """Совпадения всех видимых листьев в порядке показа."""
        source = self.sourceModel()
        assert isinstance(source, SearchResultsModel)
        result = []

        def walk(parent: QModelIndex):
            """Собрать листья под ``parent``."""
            for row in range(self.rowCount(parent)):
                index = self.index(row, 0, parent)
                if self.hasChildren(index):
                    walk(index)
                    continue
                hit = source.hit_at(self.mapToSource(index))
                if hit is not None:
                    result.append(hit)

        walk(QModelIndex())
        return result
