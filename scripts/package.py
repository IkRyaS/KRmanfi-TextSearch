"""Собирает готовую папку и архив из результата PyInstaller (``dist/KRmanfiSearch``).

Windows → ``dist/KRmanfi-TextSearch-win64.zip``,
Linux → ``dist/KRmanfi-TextSearch-linux-x64.tar.gz``.
Также обновляет ``dist/SHA256SUMS.txt``. Запуск: ``python scripts/package.py``.
"""

from __future__ import annotations

import hashlib
import shutil
import sys
import tarfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import check_release

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
BUILD = DIST / "KRmanfiSearch"
TOP = "KRmanfi-TextSearch"
COMMON = ("README.md", "LICENSE", "THIRD_PARTY_NOTICES.md", "settings.toml", "run.sh", "run.bat")
LINUX_ONLY = ("setup_linux.sh",)
EXECUTABLES = {"run.sh", "setup_linux.sh", "KRmanfiSearch"}
ARCHIVES = (
    "KRmanfi-TextSearch-win64.zip",
    "KRmanfi-TextSearch-linux-x64.tar.gz",
    "KRmanfi-TextSearch-source.zip",
)


def platform_archive():
    """Имя архива для текущей ОС."""
    if sys.platform == "win32":
        return "KRmanfi-TextSearch-win64.zip"
    if sys.platform.startswith("linux"):
        return "KRmanfi-TextSearch-linux-x64.tar.gz"
    raise SystemExit("Сборка архивов поддерживается на Windows и Linux")


def write_checksums(dist: Path):
    """Пересчитать ``SHA256SUMS.txt`` для всех готовых архивов."""
    lines = []
    for name in ARCHIVES:
        path = dist / name
        if path.is_file():
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            lines.append(f"{digest}  {name}")
    (dist / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def stage():
    """Собрать папку ``dist/KRmanfi-TextSearch``."""
    if not BUILD.is_dir():
        raise SystemExit("Нет dist/KRmanfiSearch: сначала pyinstaller krmanfi_search.spec")
    target = DIST / TOP
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(BUILD, target)
    for metadata in target.glob("_internal/krmanfi_search-*.dist-info"):
        shutil.rmtree(metadata)
    for name in COMMON + (LINUX_ONLY if sys.platform != "win32" else ()):
        shutil.copy2(ROOT / name, target / name)
    shutil.copytree(ROOT / "demo", target / "demo")
    for name in EXECUTABLES:
        path = target / name
        if path.exists():
            path.chmod(0o755)
    return target


def make_zip(folder: Path, archive: Path):
    """ZIP с верхней папкой ``KRmanfi-TextSearch``."""
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                zf.write(path, f"{TOP}/{path.relative_to(folder).as_posix()}")


def make_tar(folder: Path, archive: Path):
    """tar.gz с верхней папкой ``KRmanfi-TextSearch`` (права на запуск сохраняются)."""
    with tarfile.open(archive, "w:gz", compresslevel=6) as tf:
        tf.add(folder, arcname=TOP)


def main():
    """Собрать архив текущей ОС и проверить его содержимое."""
    folder = stage()
    archive = DIST / platform_archive()
    archive.unlink(missing_ok=True)
    (make_zip if archive.suffix == ".zip" else make_tar)(folder, archive)
    problems = check_release.check(archive)
    for problem in problems:
        print(f"  - {problem}")
    write_checksums(DIST)
    print(f"{archive}: {archive.stat().st_size / 1024 / 1024:.0f} МБ")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
