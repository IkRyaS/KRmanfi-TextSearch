from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import bundle_tesseract

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build"
DIST = ROOT / "dist"
APP = DIST / "KRmanfiSearch"
TOP = "KRmanfi-Search"
IS_WINDOWS = sys.platform == "win32"
IS_LINUX = sys.platform.startswith("linux")
EXTRA_FILES = ("README.md", "LICENSE", "THIRD_PARTY_NOTICES.md", "settings.toml")
LINUX_FILES = ("scripts/setup_linux.sh",)
EXECUTABLES = ("KRmanfiSearch", "setup_linux.sh")


def step(text: str):
    """Заголовок этапа."""
    print(f"\n=== {text} ===", flush=True)


def clean():
    """Удалить результаты прошлой сборки."""
    for folder in (BUILD, DIST):
        if folder.exists():
            shutil.rmtree(folder)


def run_pyinstaller():
    """Собрать папку ``dist/KRmanfiSearch`` по ``krmanfi_search.spec``."""
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean"]
    subprocess.run([*command, str(ROOT / "scripts" / "krmanfi_search.spec")], cwd=ROOT, check=True)
    if not APP.is_dir():
        raise SystemExit("PyInstaller не создал dist/KRmanfiSearch")


def add_tesseract():
    """Встроить Tesseract, чтобы сканы читались без установки; без него сборка всё равно готова."""
    if bundle_tesseract.bundle(APP):
        return
    print(
        "ВНИМАНИЕ: Tesseract не найден на этой машине,"
        " сканы PDF в сборке распознаваться не будут.\n"
        "  Windows: winget install UB-Mannheim.TesseractOCR\n"
        "  Linux:   sudo apt install tesseract-ocr tesseract-ocr-rus tesseract-ocr-eng\n"
        "  После установки запустите сборку ещё раз."
    )


def stage():
    """Собрать итоговую папку ``dist/KRmanfi-Search``."""
    target = DIST / TOP
    shutil.copytree(APP, target)
    for metadata in target.glob("_internal/krmanfi_search-*.dist-info"):
        shutil.rmtree(metadata)
    names = EXTRA_FILES + (LINUX_FILES if IS_LINUX else ())
    for name in names:
        shutil.copy2(ROOT / name, target / Path(name).name)
    shutil.copytree(ROOT / "demo", target / "demo")
    for name in EXECUTABLES:
        path = target / name
        if path.exists():
            path.chmod(0o755)
    return target


def make_zip(folder: Path, archive: Path):
    """ZIP с верхней папкой ``KRmanfi-Search``."""
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                zf.write(path, f"{TOP}/{path.relative_to(folder).as_posix()}")


def make_tar(folder: Path, archive: Path):
    """tar.gz с верхней папкой ``KRmanfi-Search`` (права на запуск сохраняются)."""
    with tarfile.open(archive, "w:gz", compresslevel=6) as tf:
        tf.add(folder, arcname=TOP)


def main():
    """Выполнить сборку для текущей ОС."""
    if not (IS_WINDOWS or IS_LINUX):
        raise SystemExit("Сборка поддерживается на Windows и Linux")
    step("1/4 Очистка")
    clean()
    step("2/4 PyInstaller")
    run_pyinstaller()
    step("3/4 Tesseract (распознавание сканов)")
    add_tesseract()
    step("4/4 Архив")
    folder = stage()
    if IS_WINDOWS:
        archive = DIST / f"{TOP}-win64.zip"
        make_zip(folder, archive)
    else:
        archive = DIST / f"{TOP}-linux-x64.tar.gz"
        make_tar(folder, archive)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (DIST / "SHA256SUMS.txt").write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
    print(f"\nГотово: {archive}  ({archive.stat().st_size / 1024 / 1024:.0f} МБ)")
    print(f"Папка для запуска без распаковки: {folder}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
