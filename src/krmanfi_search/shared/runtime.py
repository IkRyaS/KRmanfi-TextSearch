from __future__ import annotations

import os
import sys
from functools import cache
from pathlib import Path

import platformdirs

APP_NAME = "KRmanfiSearch"


def is_frozen():
    """Запущена ли программа из сборки PyInstaller."""
    return bool(getattr(sys, "frozen", False))


def app_dir():
    """Папка с исполняемым файлом (сборка) или корень репозитория (исходники)."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[3]


def bundle_dir():
    """Папка с данными сборки: ``_internal`` у PyInstaller, иначе корень репозитория."""
    meipass = getattr(sys, "_MEIPASS", None)
    return Path(meipass) if meipass else app_dir()


def vendor_roots():
    """Папки, где ищутся встроенные программы, от самой приоритетной."""
    roots = []
    override = os.environ.get("KRMANFI_VENDOR_DIR")
    if override:
        roots.append(Path(override))
    for base in (app_dir(), bundle_dir()):
        candidate = base / "vendor"
        if candidate not in roots:
            roots.append(candidate)
    return roots


@cache
def vendor_tesseract():
    """Путь к ``tesseract`` из ``vendor/tesseract`` или ``None``."""
    name = "tesseract.exe" if sys.platform == "win32" else "tesseract"
    for root in vendor_roots():
        candidate = root / "tesseract" / name
        if candidate.is_file():
            return candidate
    return None


@cache
def vendor_tessdata():
    """Папка ``tessdata`` рядом со встроенным Tesseract или ``None``."""
    for root in vendor_roots():
        candidate = root / "tesseract" / "tessdata"
        if candidate.is_dir() and any(candidate.glob("*.traineddata")):
            return candidate
    return None


def data_dir():
    """Пользовательская папка данных (журнал, настройки)."""
    override = os.environ.get("KRMANFI_SEARCH_DATA_DIR")
    if override:
        return Path(override)
    return Path(platformdirs.user_data_dir(APP_NAME, appauthor=False, roaming=True))


def log_dir():
    """Папка журнала."""
    return data_dir() / "logs"


def settings_file():
    """Файл пользовательских настроек: рядом с программой или в папке данных."""
    local = app_dir() / "settings.toml"
    user = data_dir() / "settings.toml"
    return user if user.is_file() else local


def resources_dir():
    """Папка ``resources`` (иконка) в сборке или в исходниках."""
    for base in (bundle_dir(), app_dir()):
        candidate = base / "resources"
        if candidate.is_dir():
            return candidate
    return app_dir() / "resources"
