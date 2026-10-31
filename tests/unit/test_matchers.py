import pytest

from krmanfi_search.domain import SearchMode, SearchQuery
from krmanfi_search.infrastructure.search.matchers import (
    RegexMatcher,
    SubstringMatcher,
    make_matcher,
)
from krmanfi_search.shared.exceptions import SearchError


def spans(matcher, text):
    return [(m.start, m.end) for m in matcher.find(text)]


def test_substring_ignores_case_for_cyrillic():
    assert spans(SubstringMatcher("отчёт", False), "ОТЧЁТ и Отчёт") == [(0, 5), (8, 13)]


def test_substring_respects_case_when_asked():
    assert spans(SubstringMatcher("Отчёт", True), "отчёт Отчёт") == [(6, 11)]


def test_yo_equals_ye_without_case_sensitivity():
    assert spans(SubstringMatcher("отчёт", False), "квартальный отчет") == [(12, 17)]


def test_occurrences_do_not_overlap():
    assert spans(SubstringMatcher("aa", False), "aaaaa") == [(0, 2), (2, 4)]


def test_offsets_survive_special_lowercase():
    assert spans(SubstringMatcher("x", False), "İİİx") == [(3, 4)]


def test_regex_finds_and_skips_empty_matches():
    assert spans(RegexMatcher(r"\d{4}-К", False), "4711-К и 4712-к") == [(0, 6), (9, 15)]
    assert spans(RegexMatcher(r"x*", False), "abc") == []


def test_invalid_regex_gives_readable_error():
    with pytest.raises(SearchError, match="Некорректное регулярное выражение"):
        RegexMatcher("(", False)


def test_factory_follows_mode(tmp_path):
    regex = make_matcher(SearchQuery(text="a.c", root=tmp_path, mode=SearchMode.REGEX))
    plain = make_matcher(SearchQuery(text="a.c", root=tmp_path))
    assert spans(regex, "abc a.c") == [(0, 3), (4, 7)]
    assert spans(plain, "abc a.c") == [(4, 7)]
