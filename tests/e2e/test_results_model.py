from pathlib import Path

import pytest
from PySide6.QtCore import QModelIndex, Qt

from krmanfi_search.domain import SearchHit
from krmanfi_search.presentation.results_model import (
    COL_CONTEXT,
    COL_FRAGMENT,
    COL_LOCATION,
    COL_WHERE,
    HEADERS,
    NodeKind,
    SearchResultsModel,
    SearchResultsProxy,
    file_label,
    location_label,
)


def hit(path="a.txt", location="стр. 1", page=1, occurrence=1, count=1, offset=0, fragment="слово"):
    return SearchHit(
        display_path=path,
        real_path=Path(path.split("!/")[0]),
        location=location,
        page=page,
        fragment=fragment,
        context=f"…{fragment}…",
        match_count=count,
        occurrence=occurrence,
        offset=offset,
    )


@pytest.fixture
def model(qapp):
    return SearchResultsModel()


@pytest.fixture
def proxy(model):
    result = SearchResultsProxy()
    result.setSourceModel(model)
    return result


def kinds(model, parent=None):
    parent = QModelIndex() if parent is None else parent
    return [model.kind_at(model.index(r, 0, parent)) for r in range(model.rowCount(parent))]


@pytest.mark.parametrize(
    ("path", "label"),
    [
        ("/data/отчёт.pdf", "отчёт.pdf"),
        ("C:\\docs\\a.docx", "a.docx"),
        ("/x/a.zip!/папка/b.pdf", "b.pdf"),
        ("/x/a.zip!/in.zip!/deep/c.txt", "c.txt"),
        ("/x/a.zip!/dir\\file.txt", "file.txt"),
        ("name.txt", "name.txt"),
    ],
)
def test_file_label_is_the_short_name(path, label):
    assert file_label(path) == label


def test_location_label_fallbacks():
    assert location_label(hit(location="лист «A»")) == "лист «A»"
    assert location_label(hit(location="", page=4)) == "стр. 4"
    assert location_label(hit(location="", page=None)) == "текст"


def test_headers_match_columns(model):
    assert [model.headerData(c, Qt.Orientation.Horizontal) for c in range(4)] == list(HEADERS)
    assert (COL_WHERE, COL_LOCATION, COL_FRAGMENT, COL_CONTEXT) == (0, 1, 2, 3)


def test_first_hit_creates_file_and_leaf(model):
    model.add_hit(hit())
    assert kinds(model) == [NodeKind.FILE]
    file_index = model.index(0, 0)
    assert kinds(model, file_index) == [NodeKind.HIT]
    leaf = model.index(0, 0, file_index)
    assert model.data(model.index(0, COL_FRAGMENT, file_index)) == "слово"
    assert model.data(leaf) == "стр. 1"


def test_second_hit_on_same_page_turns_leaf_into_group(model):
    model.add_hit(hit(occurrence=1, count=2, offset=0))
    model.add_hit(hit(occurrence=2, count=2, offset=9))
    file_index = model.index(0, 0)
    assert kinds(model, file_index) == [NodeKind.PAGE]
    group = model.index(0, 0, file_index)
    assert model.data(model.index(0, COL_FRAGMENT, file_index)) == "вхождений: 2"
    assert kinds(model, group) == [NodeKind.HIT, NodeKind.HIT]
    assert [model.data(model.index(r, 0, group)) for r in range(2)] == ["#1", "#2"]


def test_third_hit_joins_existing_group(model):
    for number in range(1, 5):
        model.add_hit(hit(occurrence=number, count=4, offset=number * 10))
    group = model.index(0, 0, model.index(0, 0))
    assert model.rowCount(group) == 4 and len(model.hits) == 4


def test_pages_of_one_file_stay_separate(model):
    model.add_hit(hit(location="стр. 1", page=1))
    model.add_hit(hit(location="стр. 3", page=3))
    assert model.rowCount(model.index(0, 0)) == 2 and model.rowCount() == 1


def test_files_are_separate_rows(model):
    model.add_hit(hit("a.txt"))
    model.add_hit(hit("b.txt"))
    model.add_hit(hit("a.txt", location="стр. 2", page=2))
    assert model.rowCount() == 2
    assert model.rowCount(model.index(0, 0)) == 2


def test_group_keeps_its_position_among_siblings(model):
    model.add_hit(hit(location="стр. 1", page=1, count=2))
    model.add_hit(hit(location="стр. 2", page=2))
    model.add_hit(hit(location="стр. 1", page=1, occurrence=2, count=2, offset=5))
    file_index = model.index(0, 0)
    assert kinds(model, file_index) == [NodeKind.PAGE, NodeKind.HIT]
    assert model.data(model.index(0, 0, file_index)) == "стр. 1"
    assert model.data(model.index(1, 0, file_index)) == "стр. 2"


def test_hit_at_returns_the_right_hit(model):
    first, second = hit("a.txt"), hit("b.txt", fragment="иное")
    model.add_hit(first)
    model.add_hit(second)
    assert model.hit_at(model.index(0, 0)) == first
    assert model.hit_at(model.index(1, 0)) == second
    leaf = model.index(0, 0, model.index(1, 0))
    assert model.hit_at(leaf) == second


def test_group_row_returns_its_first_hit(model):
    model.add_hit(hit(occurrence=1, count=2, fragment="первое"))
    model.add_hit(hit(occurrence=2, count=2, fragment="второе", offset=7))
    group = model.index(0, 0, model.index(0, 0))
    assert model.hit_at(group).fragment == "первое"


def test_invalid_index_gives_none(model):
    assert model.hit_at(QModelIndex()) is None and model.kind_at(QModelIndex()) is None


def test_clear_hits_resets_everything(model):
    model.add_hit(hit())
    model.clear_hits()
    assert model.rowCount() == 0 and model.hits == []
    model.add_hit(hit())
    assert model.rowCount() == 1 and len(model.hits) == 1


def test_hits_property_is_a_copy(model):
    model.add_hit(hit())
    model.hits.clear()
    assert len(model.hits) == 1


def test_cells_are_not_editable(model):
    model.add_hit(hit())
    for column in range(4):
        assert not (model.flags(model.index(0, column)) & Qt.ItemFlag.ItemIsEditable)


def test_tooltips_carry_full_path_and_text(model):
    model.add_hit(hit("/x/a.zip!/deep/b.txt", fragment="тест"))
    file_index = model.index(0, 0)
    assert model.data(file_index, Qt.ItemDataRole.ToolTipRole) == "/x/a.zip!/deep/b.txt"
    leaf_fragment = model.index(0, COL_FRAGMENT, file_index)
    assert model.data(leaf_fragment, Qt.ItemDataRole.ToolTipRole) == "тест"


def test_file_row_shows_short_name_and_full_path(model):
    model.add_hit(hit("/x/a.zip!/deep/b.txt"))
    assert model.data(model.index(0, COL_WHERE)) == "b.txt"
    assert model.data(model.index(0, COL_LOCATION)) == "/x/a.zip!/deep/b.txt"


def test_proxy_sorts_pages_numerically(model, proxy):
    model.add_hit(hit(location="стр. 10", page=10))
    model.add_hit(hit(location="стр. 2", page=2))
    model.add_hit(hit(location="стр. 1", page=1))
    proxy.sort(COL_WHERE, Qt.SortOrder.AscendingOrder)
    assert [h.page for h in proxy.visible_hits()] == [1, 2, 10]
    proxy.sort(COL_WHERE, Qt.SortOrder.DescendingOrder)
    assert [h.page for h in proxy.visible_hits()] == [10, 2, 1]


def test_proxy_sorts_files_alphabetically(model, proxy):
    for name in ("b.txt", "A.txt", "c.txt"):
        model.add_hit(hit(name))
    proxy.sort(COL_WHERE, Qt.SortOrder.AscendingOrder)
    assert [Path(h.display_path).name for h in proxy.visible_hits()] == ["A.txt", "b.txt", "c.txt"]


def test_proxy_sorts_occurrences_by_position(model, proxy):
    model.add_hit(hit(occurrence=1, count=2, offset=500))
    model.add_hit(hit(occurrence=2, count=2, offset=20))
    proxy.sort(COL_WHERE, Qt.SortOrder.AscendingOrder)
    assert [h.offset for h in proxy.visible_hits()] == [20, 500]


def test_proxy_sorts_by_other_columns_with_default_rule(model, proxy):
    model.add_hit(hit("a.txt", location="стр. 1", page=1, fragment="ббб"))
    model.add_hit(hit("a.txt", location="стр. 2", page=2, fragment="ааа"))
    proxy.sort(COL_FRAGMENT, Qt.SortOrder.AscendingOrder)
    assert [h.fragment for h in proxy.visible_hits()] == ["ааа", "ббб"]


def test_filter_is_case_insensitive_and_keeps_parents(model, proxy):
    model.add_hit(hit("a.txt", fragment="Квартал"))
    model.add_hit(hit("b.txt", fragment="иное"))
    proxy.setFilterFixedString("КВАРТАЛ")
    assert [Path(h.display_path).name for h in proxy.visible_hits()] == ["a.txt"]
    assert proxy.rowCount() == 1


def test_filter_by_file_name_shows_all_its_rows(model, proxy):
    model.add_hit(hit("report.pdf", location="стр. 1", page=1))
    model.add_hit(hit("report.pdf", location="стр. 2", page=2, fragment="другое"))
    model.add_hit(hit("note.txt"))
    proxy.setFilterFixedString("report")
    assert len(proxy.visible_hits()) == 2


def test_filter_matches_context_and_location(model, proxy):
    model.add_hit(hit("a.txt", location="лист «Платежи»", page=1))
    model.add_hit(hit("b.txt", location="слайд 3", page=3))
    proxy.setFilterFixedString("платежи")
    assert [Path(h.display_path).name for h in proxy.visible_hits()] == ["a.txt"]


def test_clearing_the_filter_restores_everything(model, proxy):
    model.add_hit(hit("a.txt"))
    model.add_hit(hit("b.txt", fragment="иное"))
    proxy.setFilterFixedString("иное")
    assert len(proxy.visible_hits()) == 1
    proxy.setFilterFixedString("")
    assert len(proxy.visible_hits()) == 2


def test_visible_hits_lists_leaves_of_groups(model, proxy):
    for number in range(1, 4):
        model.add_hit(hit(occurrence=number, count=3, offset=number))
    assert [h.occurrence for h in proxy.visible_hits()] == [1, 2, 3]


def test_visible_hits_of_empty_model(proxy):
    assert proxy.visible_hits() == []
