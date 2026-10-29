import random
import re

import pytest

from krmanfi_search.domain import SearchMode, SearchQuery
from krmanfi_search.infrastructure.search.matchers import (
    RegexMatcher,
    SubstringMatcher,
    fold,
    make_matcher,
)
from krmanfi_search.shared.exceptions import SearchError
from tests.helpers import random_text


def spans(matcher, text):
    return [(m.start, m.end) for m in matcher.find(text)]


@pytest.mark.parametrize("text", ["İstanbul", "STRASSE ß", "ǅ", "ΑΣ", "ẞ", "Ёлка ЁЖ", "ﬃ", "ŉ"])
def test_fold_never_changes_length(text):
    assert len(fold(text)) == len(text)


def test_fold_lowercases_and_replaces_yo():
    assert fold("Ёлка ПОДЪЁМ") == "елка подъем"


def test_fold_is_idempotent():
    for text in ("Привет, Мир!", "Ёё", "ABC xyz"):
        assert fold(fold(text)) == fold(text)


def test_empty_needle_matches_nothing():
    assert SubstringMatcher("", False).find("текст") == []


def test_needle_longer_than_text():
    assert SubstringMatcher("длинная строка", False).find("коротко") == []


def test_overlapping_needle_gives_non_overlapping_matches():
    assert spans(SubstringMatcher("aa", False), "aaaaa") == [(0, 2), (2, 4)]


def test_yo_in_needle_matches_ye_in_text_and_back():
    assert spans(SubstringMatcher("отчёт", False), "Отчет и ОТЧЁТ") == [(0, 5), (8, 13)]
    assert spans(SubstringMatcher("отчет", False), "отчёт") == [(0, 5)]


def test_case_sensitive_keeps_yo_and_case():
    matcher = SubstringMatcher("Отчёт", True)
    assert spans(matcher, "Отчёт отчёт Отчет") == [(0, 5)]


def test_matches_at_text_edges():
    assert spans(SubstringMatcher("ab", False), "ab--ab") == [(0, 2), (4, 6)]


def test_regex_is_multiline():
    matcher = RegexMatcher(r"^итого$", False)
    assert spans(matcher, "итого\nвсего итого\nИТОГО") == [(0, 5), (18, 23)]


def test_regex_case_sensitivity_flag():
    assert RegexMatcher("ДОГОВОР", True).find("договор") == []
    assert len(RegexMatcher("ДОГОВОР", False).find("договор Договор")) == 2


def test_regex_skips_empty_matches():
    assert spans(RegexMatcher(r"a*", False), "baaab") == [(1, 4)]


def test_regex_groups_and_alternation():
    matcher = RegexMatcher(r"(ИНН|КПП)\s*\d{4,}", False)
    assert len(matcher.find("ИНН 7707083893, кпп 770701001")) == 2


@pytest.mark.parametrize("pattern", ["(", "[a-", "*abc", "(?P<n", "a{2,1}"])
def test_invalid_regex_gives_search_error(pattern):
    with pytest.raises(SearchError, match="Некорректное регулярное выражение"):
        RegexMatcher(pattern, False)


def test_make_matcher_picks_class_by_mode(tmp_path):
    substring = make_matcher(SearchQuery(text="a", root=tmp_path))
    regex = make_matcher(SearchQuery(text="a", root=tmp_path, mode=SearchMode.REGEX))
    assert isinstance(substring, SubstringMatcher) and isinstance(regex, RegexMatcher)


def test_substring_matcher_agrees_with_naive_search_on_random_text():
    rng = random.Random(7)
    alphabet = "абвгдАБВГДabAB .,-"
    for _ in range(300):
        text = random_text(rng, alphabet, rng.randint(0, 60))
        needle = random_text(rng, alphabet, rng.randint(1, 3))
        expected = []
        position = text.lower().find(needle.lower())
        while position != -1:
            expected.append((position, position + len(needle)))
            position = text.lower().find(needle.lower(), position + len(needle))
        assert spans(SubstringMatcher(needle, False), text) == expected


def test_regex_literal_matches_same_places_as_substring():
    rng = random.Random(11)
    alphabet = "абвгд ab"
    for _ in range(200):
        text = random_text(rng, alphabet, rng.randint(0, 50))
        needle = random_text(rng, alphabet, rng.randint(1, 3))
        regex = RegexMatcher(re.escape(needle), False)
        assert spans(regex, text) == spans(SubstringMatcher(needle, False), text)
