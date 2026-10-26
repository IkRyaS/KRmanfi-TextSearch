"""Проверка содержимого архива или папки: ничего лишнего и никаких секретов.

Правила взяты из требований к выдаче: служебные папки, кэши, журналы, базы, ключи,
личные пути в текстах. Возвращает код 1, если найдено нарушение.
"""

from __future__ import annotations

import fnmatch
import re
import sys
import tarfile
import zipfile
from collections.abc import Iterable
from pathlib import Path, PurePosixPath

FORBIDDEN_DIRS = {
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".hypothesis",
    ".idea",
    ".vscode",
    "build",
}
FORBIDDEN_FILES = ("*.pyc", "*.log", "*.sqlite", "*.sqlite3", "*.db", ".env", "window.ini")
FORBIDDEN_FILES += ("Thumbs.db", ".DS_Store", "id_rsa*", "*.pem", "*.key")
TEXT_SUFFIXES = {".py", ".md", ".toml", ".txt", ".sh", ".bat", ".ps1", ".spec", ".yml", ".json"}
SECRET_PATTERNS = (
    re.compile(r"(password|passwd|secret|api_key|apikey|access_token)\s*[:=]\s*[\"'][^\"']{6,}"),
    re.compile(r"[A-Za-z]:\\Users\\", re.IGNORECASE),
    re.compile(r"/home/(?!user\b)[a-z][\w.-]*/"),
    re.compile(r"BEGIN (RSA|OPENSSH|PRIVATE) KEY"),
)
SELF = "check_release.py"


def bad_name(path: str):
    """Причина, по которой имя файла недопустимо, или ``None``."""
    pure = PurePosixPath(path.replace("\\", "/"))
    for part in pure.parts[:-1]:
        if part in FORBIDDEN_DIRS or part.endswith(".egg-info"):
            return f"служебная папка {part}"
    for pattern in FORBIDDEN_FILES:
        if fnmatch.fnmatch(pure.name, pattern):
            return f"запрещённый файл {pure.name}"
    return None


def secret_hits(path: str, data: bytes):
    """Совпадения с шаблонами секретов и личных путей в тексте файла."""
    if PurePosixPath(path).suffix.lower() not in TEXT_SUFFIXES or path.endswith(SELF):
        return []
    text = data.decode("utf-8", "ignore")
    return [f"{path}: {m.group(0)[:60]}" for p in SECRET_PATTERNS for m in p.finditer(text)]


def entries(source: Path) -> Iterable[tuple[str, bytes]]:
    """Имена и содержимое файлов архива или папки."""
    if source.is_dir():
        for file in sorted(p for p in source.rglob("*") if p.is_file()):
            yield file.relative_to(source).as_posix(), file.read_bytes()
    elif source.suffix == ".zip":
        with zipfile.ZipFile(source) as zf:
            for info in zf.infolist():
                if not info.is_dir():
                    yield info.filename, zf.read(info)
    else:
        with tarfile.open(source) as tf:
            for member in tf:
                if member.isfile():
                    handle = tf.extractfile(member)
                    yield member.name, handle.read() if handle else b""


def check(source: Path):
    """Вернуть список нарушений."""
    problems = []
    for name, data in entries(source):
        reason = bad_name(name)
        if reason:
            problems.append(f"{name}: {reason}")
        problems += secret_hits(name, data)
    return problems


def main(argv: list[str] | None = None):
    """Проверить пути из командной строки."""
    paths = [Path(a) for a in (argv if argv is not None else sys.argv[1:])]
    if not paths:
        sys.exit("Использование: check_release.py <архив-или-папка>...")
    failed = False
    for path in paths:
        problems = check(path)
        print(f"{path}: {'нарушений нет' if not problems else f'нарушений: {len(problems)}'}")
        for problem in problems:
            print(f"  - {problem}")
        failed = failed or bool(problems)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
