import csv
from pathlib import Path

import pytest

from krmanfi_search.domain import SearchHit
from krmanfi_search.infrastructure.search.exporter import HEADER, csv_safe, export_csv


def hit(**overrides):
    values = {
        "display_path": "папка/файл.txt",
        "real_path": Path("папка/файл.txt"),
        "location": "стр. 2",
        "fragment": "слово",
        "context": "…левое слово правое…",
        "match_count": 3,
        "occurrence": 2,
    }
    return SearchHit(**{**values, **overrides})


def read_rows(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.reader(handle))


def test_empty_export_contains_only_header(tmp_path):
    target = tmp_path / "empty.csv"
    export_csv([], target)
    assert read_rows(target) == [list(HEADER)]


def test_file_starts_with_bom_for_excel(tmp_path):
    target = tmp_path / "bom.csv"
    export_csv([hit()], target)
    assert target.read_bytes().startswith(b"\xef\xbb\xbf")


def test_row_values_in_header_order(tmp_path):
    target = tmp_path / "row.csv"
    export_csv([hit()], target)
    assert read_rows(target)[1] == [
        "папка/файл.txt",
        "стр. 2",
        "2",
        "слово",
        "…левое слово правое…",
        "3",
    ]


def test_commas_quotes_and_newlines_survive(tmp_path):
    target = tmp_path / "tricky.csv"
    tricky = 'a, "b"\nвторая строка; c'
    export_csv([hit(fragment=tricky, context=tricky)], target)
    row = read_rows(target)[1]
    assert row[3] == tricky and row[4] == tricky


@pytest.mark.parametrize("prefix", ["=", "+", "-", "@", "\t", "\r"])
def test_every_formula_prefix_is_neutralised(prefix):
    assert csv_safe(f"{prefix}SUM(A1)").startswith("'")


def test_ordinary_text_is_untouched():
    assert csv_safe("обычный текст") == "обычный текст"
    assert csv_safe("") == ""
    assert csv_safe("5 + 3") == "5 + 3"


def test_formula_like_cells_are_neutralised_in_every_text_column(tmp_path):
    target = tmp_path / "formula.csv"
    evil = "=HYPERLINK(\"http://x\")"
    export_csv([hit(display_path=evil, location=evil, fragment=evil, context=evil)], target)
    row = read_rows(target)[1]
    assert [row[0], row[1], row[3], row[4]] == [f"'{evil}"] * 4


def test_many_rows_keep_order(tmp_path):
    target = tmp_path / "many.csv"
    hits = [hit(display_path=f"f{n}.txt", occurrence=1) for n in range(500)]
    export_csv(hits, target)
    rows = read_rows(target)
    assert len(rows) == 501 and rows[1][0] == "f0.txt" and rows[-1][0] == "f499.txt"


def test_unwritable_target_raises_os_error(tmp_path):
    with pytest.raises(OSError):
        export_csv([hit()], tmp_path / "нет_папки" / "out.csv")
