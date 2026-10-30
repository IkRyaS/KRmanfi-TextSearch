import os
from pathlib import Path

import pytest

from krmanfi_search.application import SearchText
from krmanfi_search.container import Container
from krmanfi_search.domain import SearchQuery, SearchStats
from krmanfi_search.infrastructure.config import Settings
from krmanfi_search.infrastructure.search import service
from krmanfi_search.shared.exceptions import SearchError
from krmanfi_search.shared.types import CancelToken


def write(tmp_path, text):
    path = tmp_path / "settings.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_defaults_without_file(tmp_path):
    settings = Settings.load(tmp_path / "missing.toml")
    assert settings.workers == 0 and settings.load_error is None
    assert settings.ocr.languages == ["rus", "eng"] and settings.ocr.pdf_dpi == 300


def test_partial_file_keeps_other_defaults(tmp_path):
    settings = Settings.load(write(tmp_path, "workers = 3\n[ocr]\npdf_dpi = 200\n"))
    assert settings.workers == 3 and settings.ocr.pdf_dpi == 200
    assert settings.context_chars == 60 and settings.max_file_size_mb == 200


def test_ocr_command_and_languages_are_read(tmp_path):
    text = '[ocr]\ntesseract_cmd = "/opt/tesseract"\nlanguages = ["eng"]\n'
    settings = Settings.load(write(tmp_path, text))
    assert settings.ocr.tesseract_cmd == "/opt/tesseract" and settings.ocr.languages == ["eng"]


@pytest.mark.parametrize(
    "text",
    [
        "workers = 100",
        "workers = -1",
        "[ocr]\npdf_dpi = 10",
        "[ocr]\npdf_dpi = 9999",
        "context_chars = 5000",
        "max_file_size_mb = 0",
        'workers = "many"',
        "workers = [",
    ],
)
def test_invalid_values_fall_back_with_message(tmp_path, text):
    path = write(tmp_path, text)
    settings = Settings.load(path)
    assert settings.workers == 0 and settings.ocr.pdf_dpi == 300
    assert settings.load_error and str(path) in settings.load_error


def test_load_error_is_not_dumped_back_to_toml():
    assert "load_error" not in Settings(load_error="x").model_dump()


def test_empty_file_gives_defaults(tmp_path):
    assert Settings.load(write(tmp_path, "")).load_error is None


@pytest.mark.parametrize(("cores", "expected"), [(None, 1), (1, 1), (2, 1), (4, 3), (64, 8)])
def test_default_workers_leaves_a_core_and_caps_at_eight(monkeypatch, cores, expected):
    monkeypatch.setattr(os, "cpu_count", lambda: cores)
    assert service.default_workers() == expected


def test_container_uses_explicit_worker_count():
    container = Container.build(Settings(workers=3))
    assert container.search_text._engine._workers == 3


def test_container_picks_default_workers_when_zero(monkeypatch):
    monkeypatch.setattr(os, "cpu_count", lambda: 4)
    assert Container.build(Settings(workers=0)).search_text._engine._workers == 3


def test_container_passes_dpi_and_languages():
    settings = Settings.model_validate({"ocr": {"pdf_dpi": 150, "languages": ["eng"]}})
    container = Container.build(settings)
    assert container.search_text._engine._pdf_dpi == 150
    assert container.ocr._languages == ["eng"]


class FakeEngine:
    def __init__(self):
        self.calls = []

    def search(self, query, *, progress, cancel, stats):
        self.calls.append((query, progress, cancel, stats))
        return iter(["marker"])


def test_use_case_delegates_with_defaults(tmp_path):
    engine = FakeEngine()
    result = SearchText(engine)(SearchQuery(text="слово", root=tmp_path))
    assert list(result) == ["marker"]
    _, progress, cancel, stats = engine.calls[0]
    assert callable(progress) and isinstance(cancel, CancelToken) and isinstance(stats, SearchStats)


def test_use_case_passes_given_objects_through(tmp_path):
    engine = FakeEngine()
    token, stats, seen = CancelToken(), SearchStats(), []

    def progress(done, total, message):
        seen.append(message)

    SearchText(engine)(
        SearchQuery(text="a", root=tmp_path), progress=progress, cancel=token, stats=stats
    )
    _, given_progress, given_cancel, given_stats = engine.calls[0]
    assert given_progress is progress and given_cancel is token and given_stats is stats


@pytest.mark.parametrize("text", [" ", "\t\n  "])
def test_use_case_rejects_blank_text(tmp_path, text):
    with pytest.raises(SearchError, match="Введите текст"):
        SearchText(FakeEngine())(SearchQuery(text=text, root=tmp_path))


def test_use_case_rejects_missing_path(tmp_path):
    with pytest.raises(SearchError, match="не существует"):
        SearchText(FakeEngine())(SearchQuery(text="a", root=tmp_path / "нет"))


def test_use_case_accepts_single_file(tmp_path):
    path = tmp_path / "a.txt"
    path.write_text("x", encoding="utf-8")
    assert list(SearchText(FakeEngine())(SearchQuery(text="a", root=path))) == ["marker"]


@pytest.mark.skipif(not Path("/dev/null").exists(), reason="нужен /dev/null")
def test_use_case_rejects_special_files():
    with pytest.raises(SearchError, match="Не файл и не папка"):
        SearchText(FakeEngine())(SearchQuery(text="a", root=Path("/dev/null")))


def test_use_case_reports_unreadable_path(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "access", lambda path, mode: False)
    with pytest.raises(SearchError, match="Нет доступа"):
        SearchText(FakeEngine())(SearchQuery(text="a", root=tmp_path))
