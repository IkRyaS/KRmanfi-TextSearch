import struct
import zipfile

import pytest

from krmanfi_search.infrastructure.archives import (
    ZipReader,
    extract_chain,
    is_unsafe_name,
    safe_relative_path,
)
from krmanfi_search.shared.exceptions import SecurityLimitError


@pytest.mark.parametrize("name", ["../a.txt", "a/../../b", "/etc/passwd", "C:/x.txt", "..\\a"])
def test_unsafe_names_are_detected(name):
    assert is_unsafe_name(name)
    with pytest.raises(SecurityLimitError):
        safe_relative_path(name)


def test_safe_name_is_kept():
    assert safe_relative_path("папка\\файл.txt").parts == ("папка", "файл.txt")


def test_traversal_member_cannot_be_extracted(tmp_path):
    archive = tmp_path / "a.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../evil.txt", "x")
    with ZipReader(archive) as reader, pytest.raises(SecurityLimitError):
        reader.extract(reader.members()[0], tmp_path / "out", 1000, 0)
    assert not (tmp_path / "evil.txt").exists()


def test_high_compression_ratio_is_refused(tmp_path):
    archive = tmp_path / "bomb.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("zeros.txt", b"\0" * 50 * 1024 * 1024)
    with ZipReader(archive) as reader, pytest.raises(SecurityLimitError, match="сжатия"):
        reader.extract(reader.members()[0], tmp_path / "out", 100 * 1024 * 1024, 0)


def test_member_over_limit_is_refused(tmp_path):
    archive = tmp_path / "big.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("a.txt", b"x" * 2000)
    with ZipReader(archive) as reader, pytest.raises(SecurityLimitError):
        reader.extract(reader.members()[0], tmp_path / "out", 1000, 0)


def test_overlapping_entries_are_rejected(tmp_path):
    archive = tmp_path / "overlap.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr("a.txt", b"a" * 100)
        zf.writestr("b.txt", b"b" * 100)
    raw = bytearray(archive.read_bytes())
    first = raw.find(b"PK\x01\x02")
    second = raw.find(b"PK\x01\x02", first + 4)
    raw[second + 42 : second + 46] = struct.pack("<I", 0)
    archive.write_bytes(raw)
    with pytest.raises(SecurityLimitError, match="zip-бомба"):
        ZipReader(archive)


def test_extract_chain_unpacks_nested_archives(tmp_path):
    inner = tmp_path / "inner.zip"
    with zipfile.ZipFile(inner, "w") as zf:
        zf.writestr("deep/file.txt", "привет")
    outer = tmp_path / "outer.zip"
    with zipfile.ZipFile(outer, "w") as zf:
        zf.write(inner, "dir/inner.zip")
    copy = extract_chain(f"{outer}!/dir/inner.zip!/deep/file.txt", tmp_path / "tmp")
    assert copy.read_text(encoding="utf-8") == "привет"
