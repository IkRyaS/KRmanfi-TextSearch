import pytest

from tests.conftest import needs_tesseract


@needs_tesseract
def test_scanned_pdf_is_searched_through_ocr(run_search, demo):
    hits, stats = run_search(demo / "сканы" / "02_скан_книги.pdf")
    assert [(h.page, h.location) for h in hits] == [(2, "стр. 2 (OCR)")]
    assert stats.ocr_available


@needs_tesseract
def test_photo_and_rotated_pages_are_recognised(run_search, demo):
    hits, _ = run_search(demo / "сканы")
    names = {h.display_path.rsplit("/", 1)[-1] for h in hits}
    assert {"18_фото_страницы.pdf", "19_повёрнутый_скан.pdf", "02_скан_книги.pdf"} <= names


@needs_tesseract
def test_blank_page_is_skipped_and_reported(run_search, demo):
    hits, stats = run_search(demo / "сканы" / "15_пустая_страница.pdf")
    assert hits == [] and stats.without_text == 1


def test_without_ocr_scans_have_no_text(run_search, demo):
    hits, stats = run_search(demo / "сканы", ocr_scanned_pdfs=False)
    assert hits == [] and stats.without_text == 4 and not stats.ocr_available


@needs_tesseract
def test_process_pool_gives_same_result(demo):
    from krmanfi_search.container import Container
    from krmanfi_search.domain import SearchQuery
    from krmanfi_search.infrastructure.config import Settings

    pool = Container.build(Settings(workers=2))
    hits = list(pool.search_text(SearchQuery(text="квартальный отчёт", root=demo / "сканы")))
    assert len(hits) == 3


def test_missing_tesseract_does_not_break_search(demo, monkeypatch):
    from krmanfi_search.container import Container
    from krmanfi_search.domain import SearchQuery, SearchStats
    from krmanfi_search.infrastructure.config import Settings
    from krmanfi_search.infrastructure.ocr import tesseract

    monkeypatch.setattr(tesseract, "find_tesseract", lambda explicit=None: None)
    container = Container.build(Settings(workers=0))
    assert "Tesseract не найден" in (container.ocr.status_text() or "")
    stats = SearchStats()
    hits = list(
        container.search_text(
            SearchQuery(text="квартальный отчёт", root=demo / "документы"), stats=stats
        )
    )
    assert hits and not stats.ocr_available


def test_settings_fall_back_on_broken_file(tmp_path):
    from krmanfi_search.infrastructure.config import Settings

    broken = tmp_path / "settings.toml"
    broken.write_text("workers = [", encoding="utf-8")
    loaded = Settings.load(broken)
    assert loaded.workers == 0 and loaded.load_error
    assert pytest is not None
