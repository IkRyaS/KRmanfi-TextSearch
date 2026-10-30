"""Безопасное чтение ZIP-архивов: защита от выхода из папки и от zip-бомб."""

from __future__ import annotations

import os
import zipfile
from pathlib import Path, PurePosixPath

from krmanfi_search.shared.exceptions import SecurityLimitError

ARCHIVE_EXTENSIONS = frozenset({"zip"})
MAX_ARCHIVE_ENTRIES = 100_000
MAX_MEMBER_BYTES = 256 * 1024 * 1024
MAX_TOTAL_BYTES = 10 * 1024**3
MAX_COMPRESSION_RATIO = 200.0
RATIO_CHECK_MIN_BYTES = 1024 * 1024
MAX_ARCHIVE_DEPTH = 3


def is_unsafe_name(name: str):
    """Имя содержит ``..``, абсолютный путь или букву диска."""
    normalised = name.replace("\\", "/")
    if normalised.startswith("/") or (len(normalised) > 1 and normalised[1] == ":"):
        return True
    return ".." in PurePosixPath(normalised).parts


def safe_relative_path(name: str):
    """Безопасный относительный путь для распаковки.

    Raises:
        SecurityLimitError: Если имя пытается выйти за целевую папку.
    """
    if is_unsafe_name(name):
        raise SecurityLimitError(f"недопустимый путь в архиве: {name!r}")
    parts = [p for p in PurePosixPath(name.replace("\\", "/")).parts if p not in {"", "."}]
    return Path(*parts) if parts else Path("_unnamed")


def overlap_bomb(archive: zipfile.ZipFile):
    """Обнаружить zip-бомбу с перекрывающимися записями."""
    spans = sorted(
        (zi.header_offset, zi.header_offset + 30 + len(zi.filename) + zi.compress_size)
        for zi in archive.infolist()
    )
    return any(spans[i][0] < spans[i - 1][1] for i in range(1, len(spans)))


def check_member(info: zipfile.ZipInfo, max_bytes: int):
    """Проверить запись до чтения: размер и степень сжатия.

    Raises:
        SecurityLimitError: Если запись слишком велика или сжата подозрительно сильно.
    """
    if info.file_size > max_bytes:
        raise SecurityLimitError(f"{info.filename}: {info.file_size} байт больше лимита")
    packed = max(info.compress_size, 1)
    if info.file_size >= RATIO_CHECK_MIN_BYTES and info.file_size / packed > MAX_COMPRESSION_RATIO:
        raise SecurityLimitError(f"{info.filename}: подозрительная степень сжатия (zip-бомба)")


class ZipReader:
    """ZIP только для чтения с проверками безопасности (контекстный менеджер)."""

    def __init__(self, path: Path):
        """Открыть архив.

        Raises:
            SecurityLimitError: Для zip-бомбы или слишком большого числа записей.
            zipfile.BadZipFile: Если файл не является ZIP.
        """
        self._zip = zipfile.ZipFile(path)
        try:
            if len(self._zip.infolist()) > MAX_ARCHIVE_ENTRIES:
                raise SecurityLimitError(f"слишком много записей (> {MAX_ARCHIVE_ENTRIES})")
            if overlap_bomb(self._zip):
                raise SecurityLimitError("zip-бомба: перекрывающиеся записи")
        except BaseException:
            self._zip.close()
            raise

    def __enter__(self):
        """Вернуть читателя."""
        return self

    def __exit__(self, *exc: object):
        """Закрыть архив."""
        self._zip.close()

    def members(self):
        """Записи архива."""
        return self._zip.infolist()

    def extract(self, info: zipfile.ZipInfo, dest: Path, max_bytes: int, slot: int):
        """Распаковать одну запись в нумерованную подпапку ``dest``.

        Args:
            info: Запись архива.
            dest: Временная папка.
            max_bytes: Предел размера записи.
            slot: Номер подпапки: имена, различающиеся регистром, не затирают друг друга.

        Raises:
            SecurityLimitError: При выходе за папку, превышении размера или подозрительном сжатии.
        """
        check_member(info, max_bytes)
        folder = dest / f"{slot:06d}"
        target = (folder / safe_relative_path(info.filename)).resolve()
        if not target.is_relative_to(folder.resolve()):
            raise SecurityLimitError(f"выход за пределы папки: {info.filename}")
        target.parent.mkdir(parents=True, exist_ok=True)
        written = 0
        with self._zip.open(info) as src, target.open("wb") as out:
            while chunk := src.read(1024 * 1024):
                written += len(chunk)
                if written > max_bytes:
                    raise SecurityLimitError(f"{info.filename}: фактический размер превышает лимит")
                out.write(chunk)
        os.utime(target)
        return target


def extract_chain(display_path: str, dest: Path, separator: str = "!/"):
    """Распаковать файл по пути вида ``архив.zip!/папка/вложенный.zip!/файл.pdf``.

    Args:
        display_path: Путь из результатов поиска.
        dest: Папка для распаковки.
        separator: Разделитель архива и пути внутри него.

    Returns:
        Путь к временной копии файла.

    Raises:
        SecurityLimitError: Если запись небезопасна или слишком велика.
        KeyError: Если записи нет в архиве.
    """
    head, *inner = display_path.split(separator)
    current = Path(head)
    for level, name in enumerate(inner):
        with ZipReader(current) as reader:
            info = next((i for i in reader.members() if i.filename == name), None)
            if info is None:
                raise KeyError(name)
            folder = dest / f"level{level}"
            current = reader.extract(info, folder, MAX_MEMBER_BYTES, 0)
    return current
