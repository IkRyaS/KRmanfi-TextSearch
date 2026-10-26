"""Собирает ``dist/KRmanfi-TextSearch-source.zip``: исходники и инструкция запуска из Python.

В архив попадают только нужные файлы (белый список), затем он проверяется
``check_release.py``. Запуск: ``python scripts/make_source_zip.py``.
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import check_release
from package import write_checksums

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
TOP = "KRmanfi-TextSearch"
NAME = "KRmanfi-TextSearch-source.zip"
INCLUDE_DIRS = ("src", "scripts", "tests", "demo", "resources", "docs")
INCLUDE_FILES = (
    "README.md",
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
    "pyproject.toml",
    "requirements.txt",
    "uv.lock",
    "settings.toml",
    "krmanfi_search.spec",
    "run.sh",
    "run.bat",
    "setup_linux.sh",
    ".gitignore",
    ".gitlab-ci.yml",
)
EXECUTABLE = {"run.sh", "setup_linux.sh"}


def wanted(path: Path):
    """Файл разрешён к упаковке."""
    relative = path.relative_to(ROOT).as_posix()
    return check_release.bad_name(relative) is None and not relative.startswith("tests/.data")


def main():
    """Создать архив исходников и проверить его."""
    DIST.mkdir(exist_ok=True)
    target = DIST / NAME
    files = [ROOT / name for name in INCLUDE_FILES if (ROOT / name).is_file()]
    for folder in INCLUDE_DIRS:
        files += sorted(p for p in (ROOT / folder).rglob("*") if p.is_file())
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            if not wanted(path):
                continue
            relative = path.relative_to(ROOT).as_posix()
            info = zipfile.ZipInfo.from_file(path, f"{TOP}/{relative}")
            info.compress_type = zipfile.ZIP_DEFLATED
            mode = 0o755 if relative in EXECUTABLE else 0o644
            info.external_attr = (mode | 0o100000) << 16
            archive.writestr(info, path.read_bytes())
    problems = check_release.check(target)
    for problem in problems:
        print(f"  - {problem}")
    write_checksums(DIST)
    print(f"{target}: {target.stat().st_size / 1024 / 1024:.1f} МБ")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
