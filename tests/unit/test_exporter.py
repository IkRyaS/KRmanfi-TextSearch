import csv

from krmanfi_search.domain import SearchHit
from krmanfi_search.infrastructure.search.exporter import csv_safe, export_csv


def hit(fragment):
    return SearchHit(
        display_path="a.zip!/b.txt",
        real_path="a.zip",
        location="строки 1–2",
        fragment=fragment,
        context="…" + fragment + "…",
        match_count=2,
        occurrence=1,
    )


def test_csv_has_bom_header_and_rows(tmp_path):
    target = tmp_path / "r.csv"
    export_csv([hit("слово")], target)
    assert target.read_bytes().startswith(b"\xef\xbb\xbf")
    rows = list(csv.reader(target.read_text(encoding="utf-8-sig").splitlines()))
    assert rows[0][0] == "Файл" and rows[1][3] == "слово" and rows[1][5] == "2"


def test_formula_cells_are_neutralised():
    assert csv_safe("=1+1") == "'=1+1"
    assert csv_safe("обычный") == "обычный"
