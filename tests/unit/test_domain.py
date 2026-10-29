import pytest
from pydantic import ValidationError

from krmanfi_search.domain import (
    MAX_STORED_PROBLEMS,
    SearchHit,
    SearchMode,
    SearchQuery,
    SearchStats,
    TextChunk,
)


def make_hit(**overrides):
    values = {
        "display_path": "a.txt",
        "real_path": "a.txt",
        "location": "строки 1–1",
        "fragment": "x",
        "context": "x",
        "match_count": 1,
    }
    return SearchHit(**{**values, **overrides})


def test_query_defaults(tmp_path):
    query = SearchQuery(text="слово", root=tmp_path)
    assert query.mode is SearchMode.SUBSTRING
    assert not query.case_sensitive
    assert query.context_chars == 60
    assert query.include_archives and query.ocr_scanned_pdfs
    assert query.max_file_size == 200 * 1024 * 1024


def test_query_rejects_empty_text(tmp_path):
    with pytest.raises(ValidationError):
        SearchQuery(text="", root=tmp_path)


@pytest.mark.parametrize("value", [-1, 2001])
def test_query_rejects_context_out_of_range(tmp_path, value):
    with pytest.raises(ValidationError):
        SearchQuery(text="a", root=tmp_path, context_chars=value)


@pytest.mark.parametrize("value", [0, 2000])
def test_query_accepts_context_bounds(tmp_path, value):
    assert SearchQuery(text="a", root=tmp_path, context_chars=value).context_chars == value


def test_query_rejects_non_positive_size(tmp_path):
    with pytest.raises(ValidationError):
        SearchQuery(text="a", root=tmp_path, max_file_size=0)


def test_query_is_immutable(tmp_path):
    query = SearchQuery(text="a", root=tmp_path)
    with pytest.raises(ValidationError):
        query.text = "b"


def test_query_accepts_mode_as_string(tmp_path):
    assert SearchQuery(text="a", root=tmp_path, mode="regex").mode is SearchMode.REGEX


def test_hit_requires_positive_counters():
    with pytest.raises(ValidationError):
        make_hit(match_count=0)
    with pytest.raises(ValidationError):
        make_hit(occurrence=0)


def test_hit_defaults():
    hit = make_hit()
    assert hit.occurrence == 1 and hit.offset == 0 and hit.page is None


def test_chunk_is_immutable():
    chunk = TextChunk(location="стр. 1", page=1, text="t")
    with pytest.raises(ValidationError):
        chunk.text = "other"


def test_stats_error_reason_is_truncated():
    stats = SearchStats()
    stats.add_error("f", "x" * 1000)
    assert len(stats.errors[0][1]) == 300 and stats.failed == 1


def test_stats_lists_are_capped_but_counters_keep_growing():
    stats = SearchStats()
    for number in range(MAX_STORED_PROBLEMS + 25):
        stats.add_error(f"e{number}", "r")
        stats.add_no_text(f"n{number}")
        stats.add_skipped(f"s{number}")
    assert len(stats.errors) == len(stats.no_text_files) == len(stats.skipped_files)
    assert len(stats.errors) == MAX_STORED_PROBLEMS
    assert stats.failed == stats.without_text == stats.skipped == MAX_STORED_PROBLEMS + 25


def test_summary_without_skipped():
    stats = SearchStats(hits=5, hit_files=2, scanned=9, without_text=1, failed=3)
    assert stats.summary() == (
        "найдено 5 фрагментов в 2 файлах; просмотрено 9 файлов; без текста — 1; ошибок — 3"
    )


def test_summary_mentions_skipped_files():
    stats = SearchStats(skipped=4)
    assert stats.summary().endswith("пропущено (слишком большие) — 4")


def test_stats_instances_do_not_share_lists():
    first, second = SearchStats(), SearchStats()
    first.add_error("a", "b")
    assert second.errors == []
