import threading
import zipfile

import pytest

from krmanfi_search.domain import SearchQuery, SearchStats
from krmanfi_search.shared.exceptions import OperationCancelledError, SearchError
from krmanfi_search.shared.types import CancelToken


def test_empty_query_is_rejected(container, tmp_path):
    with pytest.raises(ValueError):
        SearchQuery(text="", root=tmp_path)
    with pytest.raises(SearchError, match="Введите текст"):
        container.search_text(SearchQuery(text="   ", root=tmp_path))


def test_missing_folder_is_reported(container, tmp_path):
    with pytest.raises(SearchError, match="не существует"):
        container.search_text(SearchQuery(text="a", root=tmp_path / "нет"))


def test_bad_regex_raises_when_search_starts(container, tmp_path):
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    hits = container.search_text(SearchQuery(text="(", root=tmp_path, mode="regex"))
    with pytest.raises(SearchError, match="регулярное"):
        list(hits)


def test_broken_zip_goes_to_errors_and_search_continues(run_search, tmp_path):
    (tmp_path / "bad.zip").write_bytes(b"PK\x03\x04 not an archive")
    (tmp_path / "ok.txt").write_text("нужное слово", encoding="utf-8")
    hits, stats = run_search(tmp_path, "нужное", ocr_scanned_pdfs=False)
    assert len(hits) == 1
    assert [p.endswith("bad.zip") for p, _ in stats.errors] == [True]


def test_corrupt_office_file_does_not_stop_search(run_search, tmp_path):
    (tmp_path / "bad.docx").write_bytes(b"not a docx")
    (tmp_path / "ok.txt").write_text("слово", encoding="utf-8")
    hits, stats = run_search(tmp_path, "слово", ocr_scanned_pdfs=False)
    assert len(hits) == 1 and stats.failed == 1


def test_traversal_and_encrypted_pdf_are_errors(run_search, demo):
    _, stats = run_search(demo / "для_проверки_ошибок", ocr_scanned_pdfs=False)
    reasons = " ".join(reason for _, reason in stats.errors)
    assert "недопустимый путь" in reasons
    assert "зашифрован" in reasons
    assert any(path.endswith("12_битый_архив.zip") for path, _ in stats.errors)


def test_traversal_never_writes_outside_temp(run_search, demo):
    run_search(demo / "для_проверки_ошибок", ocr_scanned_pdfs=False)
    assert not list(demo.parent.rglob("evil.txt"))


def test_oversized_file_is_skipped_and_listed(run_search, tmp_path):
    (tmp_path / "big.txt").write_text("слово" * 1000, encoding="utf-8")
    hits, stats = run_search(tmp_path, "слово", max_file_size=100, ocr_scanned_pdfs=False)
    assert hits == [] and stats.skipped == 1 and stats.skipped_files[0].endswith("big.txt")


def test_zip_bomb_member_is_recorded_as_error(run_search, tmp_path):
    with zipfile.ZipFile(tmp_path / "bomb.zip", "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("zeros.txt", b"a" * 30 * 1024 * 1024)
    hits, stats = run_search(tmp_path, "слово", ocr_scanned_pdfs=False)
    assert hits == [] and any("zip-бомба" in r for _, r in stats.errors)


def test_cancel_stops_and_removes_temp_folders(container, tmp_path, monkeypatch):
    import tempfile

    created = []
    real = tempfile.mkdtemp

    def tracking(*args, **kwargs):
        path = real(*args, **kwargs)
        created.append(path)
        return path

    monkeypatch.setattr(tempfile, "mkdtemp", tracking)
    with zipfile.ZipFile(tmp_path / "a.zip", "w") as zf:
        for i in range(50):
            zf.writestr(f"{i}.txt", "слово " * 100)
    token = CancelToken()
    stream = container.search_text(
        SearchQuery(text="слово", root=tmp_path, ocr_scanned_pdfs=False),
        cancel=token,
        stats=SearchStats(),
    )
    next(stream)
    token.cancel()
    with pytest.raises(OperationCancelledError):
        list(stream)
    import os

    assert created and not any(os.path.exists(p) for p in created)
    assert threading.active_count() >= 1


def test_search_twice_gives_independent_results(run_search, tmp_path):
    (tmp_path / "a.txt").write_text("слово", encoding="utf-8")
    first, _ = run_search(tmp_path, "слово", ocr_scanned_pdfs=False)
    second, stats = run_search(tmp_path, "слово", ocr_scanned_pdfs=False)
    assert len(first) == len(second) == 1 and stats.hits == 1
