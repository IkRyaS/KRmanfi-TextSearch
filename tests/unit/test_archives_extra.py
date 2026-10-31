import zipfile
from pathlib import Path

import pytest

from krmanfi_search.infrastructure import archives
from krmanfi_search.infrastructure.archives import (
    MAX_COMPRESSION_RATIO,
    RATIO_CHECK_MIN_BYTES,
    ZipReader,
    check_member,
    extract_chain,
    is_unsafe_name,
    overlap_bomb,
    safe_relative_path,
)
from krmanfi_search.shared.exceptions import SecurityLimitError
from tests.helpers import make_zip


def info(size: int, packed: int, name: str = "a.txt"):
    entry = zipfile.ZipInfo(name)
    entry.file_size = size
    entry.compress_size = packed
    return entry


@pytest.mark.parametrize(
    "name",
    [
        "../x",
        "a/../../x",
        "/etc/passwd",
        "C:/Windows/x",
        "c:\\x",
        "..\\x",
        "a\\..\\b",
        "\\\\srv\\sh",
    ],
)
def test_unsafe_names(name):
    assert is_unsafe_name(name)


@pytest.mark.parametrize("name", ["a.txt", "dir/sub/b.pdf", "..hidden", "a..b/c", "папка/файл.txt"])
def test_safe_names(name):
    assert not is_unsafe_name(name)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("a/b/c.txt", Path("a/b/c.txt")),
        ("./a//b.txt", Path("a/b.txt")),
        ("a\\b.txt", Path("a/b.txt")),
        ("", Path("_unnamed")),
        (".", Path("_unnamed")),
        ("папка/Файл.TXT", Path("папка/Файл.TXT")),
    ],
)
def test_safe_relative_path(name, expected):
    assert safe_relative_path(name) == expected


@pytest.mark.parametrize("name", ["../x", "/abs", "D:/x"])
def test_safe_relative_path_rejects_unsafe(name):
    with pytest.raises(SecurityLimitError):
        safe_relative_path(name)


def test_check_member_boundaries():
    check_member(info(100, 10), 100)
    with pytest.raises(SecurityLimitError, match="больше лимита"):
        check_member(info(101, 10), 100)


def test_ratio_is_checked_only_for_large_members():
    check_member(info(RATIO_CHECK_MIN_BYTES - 1, 1), 10**9)
    with pytest.raises(SecurityLimitError, match="zip-бомба"):
        check_member(info(RATIO_CHECK_MIN_BYTES, 1), 10**9)


def test_ratio_exactly_at_limit_is_allowed():
    size = RATIO_CHECK_MIN_BYTES
    packed = int(size / MAX_COMPRESSION_RATIO)
    check_member(info(size, packed + 1), 10**9)


def test_normal_archive_is_not_an_overlap_bomb(tmp_path):
    path = make_zip(tmp_path / "a.zip", {"a.txt": "один", "b.txt": "два", "c/d.txt": "три"})
    with zipfile.ZipFile(path) as archive:
        assert not overlap_bomb(archive)


def test_reader_rejects_non_zip(tmp_path):
    path = tmp_path / "fake.zip"
    path.write_bytes(b"plain text, not an archive")
    with pytest.raises(zipfile.BadZipFile):
        ZipReader(path)


def test_reader_rejects_too_many_entries(tmp_path, monkeypatch):
    path = make_zip(tmp_path / "a.zip", {f"{n}.txt": "x" for n in range(5)})
    monkeypatch.setattr(archives, "MAX_ARCHIVE_ENTRIES", 4)
    with pytest.raises(SecurityLimitError, match="слишком много записей"):
        ZipReader(path)


def test_reader_lists_members_and_closes(tmp_path):
    path = make_zip(tmp_path / "a.zip", {"a.txt": "x", "d/b.txt": "y"})
    with ZipReader(path) as reader:
        assert [m.filename for m in reader.members()] == ["a.txt", "d/b.txt"]
        inner = reader._zip
    assert inner.fp is None


def test_extract_uses_numbered_slot_folders(tmp_path):
    path = make_zip(tmp_path / "a.zip", {"Report.txt": "верхний", "report.txt": "нижний"})
    dest = tmp_path / "out"
    with ZipReader(path) as reader:
        first, second = reader.members()
        one = reader.extract(first, dest, 10**6, 0)
        two = reader.extract(second, dest, 10**6, 1)
    assert one.parent.name == "000000" and two.parent.name == "000001"
    assert one.read_text(encoding="utf-8") == "верхний"
    assert two.read_text(encoding="utf-8") == "нижний"


def test_extract_keeps_subfolders_and_unicode(tmp_path):
    path = make_zip(tmp_path / "a.zip", {"папка/вложенная/файл.txt": "данные"})
    with ZipReader(path) as reader:
        target = reader.extract(reader.members()[0], tmp_path / "out", 10**6, 7)
    parts = target.relative_to(tmp_path / "out").parts
    assert parts == ("000007", "папка", "вложенная", "файл.txt")


def test_extract_refuses_traversal_without_writing(tmp_path):
    path = tmp_path / "evil.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("../evil.txt", "x")
    dest = tmp_path / "out"
    with ZipReader(path) as reader, pytest.raises(SecurityLimitError):
        reader.extract(reader.members()[0], dest, 10**6, 0)
    assert not (tmp_path / "evil.txt").exists() and not dest.exists()


def test_extract_refuses_member_above_limit(tmp_path):
    path = make_zip(tmp_path / "a.zip", {"big.txt": "x" * 500})
    with ZipReader(path) as reader, pytest.raises(SecurityLimitError):
        reader.extract(reader.members()[0], tmp_path / "out", 100, 0)


def test_extract_chain_for_plain_file_returns_it(tmp_path):
    path = tmp_path / "doc.txt"
    path.write_text("x", encoding="utf-8")
    assert extract_chain(str(path), tmp_path / "out") == path


def test_extract_chain_three_levels(tmp_path):
    inner = make_zip(tmp_path / "in.zip", {"deep/файл.txt": "самый глубокий"})
    middle = make_zip(tmp_path / "mid.zip", {"in.zip": inner.read_bytes()})
    outer = make_zip(tmp_path / "out.zip", {"папка/mid.zip": middle.read_bytes()})
    display = f"{outer}!/папка/mid.zip!/in.zip!/deep/файл.txt"
    result = extract_chain(display, tmp_path / "work")
    assert result.read_text(encoding="utf-8") == "самый глубокий"
    assert result.is_relative_to(tmp_path / "work")


def test_extract_chain_missing_member_raises_key_error(tmp_path):
    outer = make_zip(tmp_path / "out.zip", {"a.txt": "x"})
    with pytest.raises(KeyError):
        extract_chain(f"{outer}!/нет_такого.txt", tmp_path / "work")


def test_extract_chain_custom_separator(tmp_path):
    outer = make_zip(tmp_path / "out.zip", {"a.txt": "x"})
    assert extract_chain(f"{outer}|a.txt", tmp_path / "w", separator="|").name == "a.txt"
