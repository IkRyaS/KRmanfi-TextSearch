import os
import tempfile
from pathlib import Path

import pytest
from docx import Document

from krmanfi_search.container import Container
from krmanfi_search.domain import SearchQuery, SearchStats
from krmanfi_search.infrastructure.config import Settings
from krmanfi_search.infrastructure.search import service
from krmanfi_search.infrastructure.search.service import (
    ARCHIVE_SEPARATOR,
    MAX_HITS_PER_LOCATION,
    TEMP_PREFIX,
    TextSearchService,
)
from krmanfi_search.shared.exceptions import OperationCancelledError
from krmanfi_search.shared.types import CancelToken
from tests.helpers import flag_member_as_encrypted, make_image_pdf, make_text_pdf, make_zip


def search(root, text="слово", workers=0, **options):
    container = Container.build(Settings(workers=workers))
    stats = SearchStats()
    progress = []
    query = SearchQuery(text=text, root=root, ocr_scanned_pdfs=False, **options)
    hits = list(
        container.search_text(
            query, stats=stats, progress=lambda d, t, m: progress.append((d, t, m))
        )
    )
    return hits, stats, progress


def temp_dirs():
    return {p for p in Path(tempfile.gettempdir()).glob(f"{TEMP_PREFIX}*")}


def write(folder, name, text):
    path = folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_single_file_as_root(tmp_path):
    path = write(tmp_path, "one.txt", "тут слово есть")
    hits, stats, _ = search(path)
    assert len(hits) == 1 and stats.files_total == 1 and hits[0].display_path == str(path)


def test_unsupported_extensions_are_not_counted(tmp_path):
    write(tmp_path, "a.txt", "слово")
    write(tmp_path, "b.exe", "слово")
    write(tmp_path, "c.doc", "слово")
    write(tmp_path, "noext", "слово")
    _, stats, _ = search(tmp_path)
    assert stats.files_total == 1


def test_extension_check_ignores_case(tmp_path):
    write(tmp_path, "BIG.TXT", "слово")
    hits, _, _ = search(tmp_path)
    assert len(hits) == 1


def test_symlinks_are_not_followed(tmp_path):
    real = tmp_path / "real"
    write(real, "a.txt", "слово")
    outside = tmp_path / "outside"
    write(outside, "b.txt", "слово")
    try:
        os.symlink(outside, real / "link_dir")
        os.symlink(outside / "b.txt", real / "link.txt")
    except OSError:
        pytest.skip("симлинки недоступны")
    hits, stats, _ = search(real)
    assert [Path(h.display_path).name for h in hits] == ["a.txt"] and stats.files_total == 1


def test_nested_folders_are_walked(tmp_path):
    write(tmp_path, "a/b/c/d.txt", "слово")
    write(tmp_path, "a/e.txt", "слово")
    hits, _, _ = search(tmp_path)
    assert len(hits) == 2


def test_empty_folder_reports_zero_files(tmp_path):
    hits, stats, _ = search(tmp_path)
    assert hits == [] and stats.files_total == 0 and stats.hit_files == 0


def test_hits_per_location_are_capped_but_total_is_reported(tmp_path):
    write(tmp_path, "many.txt", " слово" * 300)
    hits, _, _ = search(tmp_path)
    assert len(hits) == MAX_HITS_PER_LOCATION
    assert {h.match_count for h in hits} == {300}
    assert [h.occurrence for h in hits] == list(range(1, MAX_HITS_PER_LOCATION + 1))


def test_offsets_are_ascending_and_point_at_the_text(tmp_path):
    text = "слово a слово b слово"
    write(tmp_path, "a.txt", text)
    hits, _, _ = search(tmp_path)
    assert [h.offset for h in hits] == [0, 8, 16]
    assert all(text[h.offset : h.offset + 5] == "слово" for h in hits)


def test_zero_context_keeps_only_ellipsis_marks(tmp_path):
    write(tmp_path, "a.txt", "до слово после")
    hits, _, _ = search(tmp_path, context_chars=0)
    assert hits[0].context == "…слово…"


def test_context_is_clipped_at_both_ends_without_ellipsis(tmp_path):
    write(tmp_path, "a.txt", "слово")
    hits, _, _ = search(tmp_path)
    assert hits[0].context == "слово"


def test_context_collapses_whitespace_and_newlines(tmp_path):
    write(tmp_path, "a.txt", "левый\n\n\tтекст   слово\nправый")
    hits, _, _ = search(tmp_path)
    assert hits[0].context == "левый текст слово правый"


def test_fragment_keeps_original_spelling(tmp_path):
    write(tmp_path, "a.txt", "СЛОВО Слово")
    hits, _, _ = search(tmp_path)
    assert [h.fragment for h in hits] == ["СЛОВО", "Слово"]


def test_case_sensitive_search(tmp_path):
    write(tmp_path, "a.txt", "СЛОВО слово")
    hits, _, _ = search(tmp_path, case_sensitive=True)
    assert [h.fragment for h in hits] == ["слово"]


def test_archives_can_be_skipped(tmp_path):
    make_zip(tmp_path / "a.zip", {"x.txt": "слово"})
    hits, stats, _ = search(tmp_path, include_archives=False)
    assert hits == [] and stats.files_total == 0


def test_archive_counters(tmp_path):
    make_zip(tmp_path / "a.zip", {"x.txt": "слово", "y.txt": "иное", "z.bin": "слово", "d/": ""})
    hits, stats, _ = search(tmp_path)
    assert len(hits) == 1 and stats.archives == 1 and stats.scanned == 3 and stats.hit_files == 1


def test_archive_display_path_and_real_path(tmp_path):
    path = make_zip(tmp_path / "a.zip", {"папка/файл.txt": "слово"})
    hits, _, _ = search(tmp_path)
    assert hits[0].display_path == f"{path}{ARCHIVE_SEPARATOR}папка/файл.txt"
    assert hits[0].real_path == path


def test_nesting_depth_limit(tmp_path):
    deepest = make_zip(tmp_path / "l3.zip", {"doc.txt": "слово на четвёртом уровне"})
    level2 = make_zip(tmp_path / "l2.zip", {"l3.zip": deepest.read_bytes(), "ok.txt": "слово тут"})
    level1 = make_zip(tmp_path / "l1.zip", {"l2.zip": level2.read_bytes()})
    top = make_zip(tmp_path / "top.zip", {"l1.zip": level1.read_bytes()})
    for name in ("l1.zip", "l2.zip", "l3.zip"):
        (tmp_path / name).unlink()
    hits, _, _ = search(tmp_path)
    assert [h.display_path.rsplit(ARCHIVE_SEPARATOR, 1)[-1] for h in hits] == ["ok.txt"]
    assert hits[0].display_path.startswith(str(top))


def test_zip_member_with_flagged_encryption_is_an_error(tmp_path):
    path = make_zip(tmp_path / "enc.zip", {"secret.txt": "слово", "open.txt": "слово"})
    flag_member_as_encrypted(path, "secret.txt")
    hits, stats, _ = search(tmp_path)
    assert [h.display_path.rsplit("/", 1)[-1] for h in hits] == ["open.txt"]
    assert any("зашифрована" in reason for _, reason in stats.errors)


def test_member_over_limit_is_error_and_others_continue(tmp_path, monkeypatch):
    make_zip(tmp_path / "a.zip", {"big.txt": "слово" * 100, "small.txt": "слово"})
    monkeypatch.setattr(service, "MAX_MEMBER_BYTES", 100)
    hits, stats, _ = search(tmp_path)
    assert [h.display_path.rsplit("/", 1)[-1] for h in hits] == ["small.txt"]
    assert stats.failed == 1 and "больше лимита" in stats.errors[0][1]


def test_total_extraction_budget_is_enforced(tmp_path, monkeypatch):
    make_zip(tmp_path / "a.zip", {f"{n}.txt": "слово" * 10 for n in range(4)})
    monkeypatch.setattr(service, "MAX_TOTAL_BYTES", 80)
    hits, stats, _ = search(tmp_path)
    assert len(hits) < 4 and stats.failed >= 1


def test_files_over_size_limit_are_skipped_and_listed(tmp_path):
    big = write(tmp_path, "big.txt", "слово" * 100)
    write(tmp_path, "small.txt", "слово")
    hits, stats, _ = search(tmp_path, max_file_size=100)
    assert stats.skipped == 1 and stats.skipped_files == [str(big)]
    assert [Path(h.display_path).name for h in hits] == ["small.txt"]


def test_progress_is_monotonic_and_ends_complete(tmp_path):
    for n in range(6):
        write(tmp_path, f"{n}.txt", "слово")
    _, _, progress = search(tmp_path)
    done = [d for d, t, _ in progress if t]
    assert done == sorted(done)
    assert progress[0][2] == "Сбор файлов…" and progress[-1] == (6, 6, "Готово")
    assert all(d <= t for d, t, _ in progress if t)


def test_search_is_lazy_and_cancels_between_files(tmp_path):
    for n in range(5):
        write(tmp_path, f"{n}.txt", "слово")
    container = Container.build(Settings(workers=0))
    token = CancelToken()
    stream = container.search_text(
        SearchQuery(text="слово", root=tmp_path), cancel=token, stats=SearchStats()
    )
    next(stream)
    token.cancel()
    with pytest.raises(OperationCancelledError):
        list(stream)


def test_temp_folders_are_removed_after_normal_run(tmp_path):
    make_zip(tmp_path / "a.zip", {"x.txt": "слово"})
    before = temp_dirs()
    search(tmp_path)
    assert temp_dirs() == before


def test_temp_folders_are_removed_when_generator_is_abandoned(tmp_path):
    make_zip(tmp_path / "a.zip", {"x.txt": "слово", "y.txt": "слово"})
    before = temp_dirs()
    container = Container.build(Settings(workers=0))
    stream = container.search_text(SearchQuery(text="слово", root=tmp_path))
    next(stream)
    assert temp_dirs() - before
    stream.close()
    assert temp_dirs() == before


def test_pool_gives_same_hits_as_local_run(tmp_path):
    for n in range(32):
        write(tmp_path, f"f{n:02d}.txt", f"файл {n} слово")
    local, _, _ = search(tmp_path, workers=0)
    pooled, stats, _ = search(tmp_path, workers=2)

    def key(hit):
        return (hit.display_path, hit.location, hit.offset)

    assert sorted(map(key, pooled)) == sorted(map(key, local)) and len(local) == 32
    assert stats.with_text == 32


def test_broken_file_in_pool_is_reported_and_others_survive(tmp_path):
    for n in range(31):
        write(tmp_path, f"f{n:02d}.txt", "слово")
    (tmp_path / "bad.docx").write_bytes(b"not a docx")
    hits, stats, _ = search(tmp_path, workers=2)
    assert len(hits) == 31 and stats.failed == 1 and "bad.docx" in stats.errors[0][0]


def test_docx_in_archive_is_searched(tmp_path):
    document = Document()
    document.add_paragraph("абзац со словом внутри")
    inner = tmp_path / "inner.docx"
    document.save(inner)
    make_zip(tmp_path / "a.zip", {"inner.docx": inner.read_bytes()})
    inner.unlink()
    hits, _, _ = search(tmp_path)
    assert len(hits) == 1 and hits[0].location.startswith("абзацы")


def test_file_with_text_but_no_match_counts_as_with_text(tmp_path):
    write(tmp_path, "a.txt", "ничего общего")
    hits, stats, _ = search(tmp_path)
    assert hits == [] and stats.with_text == 1 and stats.without_text == 0


def test_blank_and_empty_files_go_to_without_text(tmp_path):
    write(tmp_path, "blank.txt", "   \n")
    (tmp_path / "empty.md").write_bytes(b"")
    _, stats, _ = search(tmp_path)
    assert stats.without_text == 2 and len(stats.no_text_files) == 2


def test_pdf_without_text_layer_is_reported_when_ocr_is_off(tmp_path):
    make_image_pdf(tmp_path / "scan.pdf")
    _, stats, _ = search(tmp_path)
    assert stats.without_text == 1 and not stats.ocr_available


def test_large_pdf_is_split_into_page_ranges_for_ocr(tmp_path):
    path = make_image_pdf(tmp_path / "big.pdf", pages=10, noisy=True)
    assert path.stat().st_size >= service.SPLIT_PDF_MIN_BYTES - 200_000
    monkey = pytest.MonkeyPatch()
    monkey.setattr(service, "SPLIT_PDF_MIN_BYTES", 1)
    try:
        engine = TextSearchService(ocr_factory=lambda: (lambda image: "найденный текст"), workers=0)
        stats = SearchStats()
        progress = []
        query = SearchQuery(text="найденный", root=tmp_path)
        hits = list(
            engine.search(
                query,
                progress=lambda d, t, m: progress.append((d, t, m)),
                cancel=CancelToken(),
                stats=stats,
            )
        )
    finally:
        monkey.undo()
    assert sorted(h.page for h in hits) == list(range(1, 11))
    assert all("(OCR)" in h.location for h in hits)
    assert stats.with_text == 1 and stats.files_total == 1 and stats.ocr_available
    assert any("стр. 1–4 из 10" in m for _, _, m in progress)
    assert progress[-1][0] == progress[-1][1]


def test_one_failing_part_marks_the_whole_file_as_failed(tmp_path):
    make_image_pdf(tmp_path / "big.pdf", pages=9)
    calls = []

    def flaky(image):
        calls.append(1)
        if len(calls) == 6:
            raise RuntimeError("распознавание упало")
        return "текст со словом"

    monkey = pytest.MonkeyPatch()
    monkey.setattr(service, "SPLIT_PDF_MIN_BYTES", 1)
    try:
        engine = TextSearchService(ocr_factory=lambda: flaky, workers=0)
        stats = SearchStats()
        list(
            engine.search(
                SearchQuery(text="слово", root=tmp_path),
                progress=lambda d, t, m: None,
                cancel=CancelToken(),
                stats=stats,
            )
        )
    finally:
        monkey.undo()
    assert stats.failed == 1 and "распознавание упало" in stats.errors[0][1]
    assert stats.with_text == 0


def test_text_pdf_with_ocr_enabled_never_calls_ocr(tmp_path):
    make_text_pdf(tmp_path / "t.pdf", ["plain words here"] * 6)

    def forbidden():
        def run(image):
            raise AssertionError("OCR не нужен")

        return run

    engine = TextSearchService(ocr_factory=forbidden, workers=0)
    hits = list(
        engine.search(
            SearchQuery(text="plain", root=tmp_path),
            progress=lambda d, t, m: None,
            cancel=CancelToken(),
            stats=SearchStats(),
        )
    )
    assert len(hits) == 6 and all('OCR' not in h.location for h in hits)
