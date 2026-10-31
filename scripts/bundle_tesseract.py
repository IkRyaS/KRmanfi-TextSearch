from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

LANGS = ("rus", "eng", "osd")
TESSDATA_URL = "https://github.com/tesseract-ocr/tessdata_fast/raw/main/{lang}.traineddata"
GLIBC = re.compile(
    r"^(ld-linux.*|libc|libm|libdl|libpthread|librt|libresolv|libutil|libnsl|libmvec|"
    r"libanl|libBrokenLocale|libcrypt|libthread_db)\.so"
)
WINDOWS_DIRS = (r"C:\Program Files\Tesseract-OCR", r"C:\Program Files (x86)\Tesseract-OCR")


def find_tesseract():
    """Путь к установленному ``tesseract`` или ``None``."""
    found = shutil.which("tesseract")
    if found:
        return Path(found).resolve()
    if sys.platform == "win32":
        for folder in WINDOWS_DIRS:
            candidate = Path(folder) / "tesseract.exe"
            if candidate.is_file():
                return candidate
    return None


def tessdata_dirs(tesseract: Path):
    """Папки ``tessdata``, где может лежать язык."""
    result = []
    try:
        out = subprocess.run(
            [str(tesseract), "--list-langs"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        match = re.search(r'languages in "([^"]+)"', out.stdout + out.stderr)
        if match:
            result.append(Path(match.group(1)))
    except (OSError, subprocess.SubprocessError):
        pass
    if os.environ.get("TESSDATA_PREFIX"):
        result.append(Path(os.environ["TESSDATA_PREFIX"]))
    result.append(tesseract.parent / "tessdata")
    return [p for p in result if p.is_dir()]


def copy_tessdata(tesseract: Path, dest: Path):
    """Скопировать языки; недостающие скачать."""
    dest.mkdir(parents=True, exist_ok=True)
    sources = tessdata_dirs(tesseract)
    for lang in LANGS:
        name = f"{lang}.traineddata"
        found = next((s / name for s in sources if (s / name).is_file()), None)
        if found is not None:
            shutil.copy2(found, dest / name)
            continue
        print(f"  скачиваю {name} (tessdata_fast)")
        with urllib.request.urlopen(TESSDATA_URL.format(lang=lang), timeout=120) as response:
            (dest / name).write_bytes(response.read())
    for sub in ("configs", "tessconfigs"):
        source = next((s / sub for s in sources if (s / sub).is_dir()), None)
        if source is not None:
            shutil.copytree(source, dest / sub, dirs_exist_ok=True)


def linux_libraries(binary: Path):
    """Библиотеки бинарника, кроме glibc."""
    out = subprocess.run(["ldd", str(binary)], capture_output=True, text=True, check=False)
    libs = {}
    for line in out.stdout.splitlines():
        match = re.match(r"\s*(\S+)\s+=>\s+(/\S+)", line)
        if match and not GLIBC.match(match.group(1)):
            libs[match.group(1)] = Path(match.group(2)).resolve()
    return libs


def patchelf():
    """Исполняемый файл ``patchelf``."""
    found = shutil.which("patchelf") or str(Path(sys.executable).parent / "patchelf")
    if not Path(found).exists():
        raise SystemExit("patchelf не найден: pip install patchelf")
    return found


def bundle_linux(tesseract: Path, target: Path):
    """Скопировать бинарник и библиотеки Linux."""
    tool = patchelf()
    (target / "lib").mkdir(parents=True, exist_ok=True)
    binary = target / "tesseract"
    shutil.copy2(tesseract, binary)
    subprocess.run([tool, "--set-rpath", "$ORIGIN/lib", str(binary)], check=True)
    for soname, path in linux_libraries(tesseract).items():
        shutil.copy2(path, target / "lib" / soname)
        subprocess.run([tool, "--set-rpath", "$ORIGIN", str(target / "lib" / soname)], check=False)


def bundle_windows(tesseract: Path, target: Path):
    """Скопировать программу и DLL Windows."""
    shutil.copytree(
        tesseract.parent,
        target,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("tessdata", "doc", "*.html", "unins*"),
    )


def bundle(dist: Path):
    """Встроить Tesseract в ``<dist>/vendor/tesseract``.

    Args:
        dist: Папка сборки PyInstaller, например ``dist/KRmanfiSearch``.

    Returns:
        ``True``, если Tesseract найден и встроен; ``False``, если его нет на машине сборки.
    """
    tesseract = find_tesseract()
    if tesseract is None:
        return False
    target = dist / "vendor" / "tesseract"
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    if sys.platform == "win32":
        bundle_windows(tesseract, target)
    elif sys.platform.startswith("linux"):
        bundle_linux(tesseract, target)
    else:
        raise SystemExit("Сборка со встроенным Tesseract поддерживается на Windows и Linux")
    copy_tessdata(tesseract, target / "tessdata")
    size = sum(p.stat().st_size for p in target.rglob("*") if p.is_file())
    print(f"vendor/tesseract: {size / 1024 / 1024:.0f} МБ из {tesseract}")
    return True
