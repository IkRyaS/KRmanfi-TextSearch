"""Спецификация PyInstaller: папочная сборка KRmanfi Text Search.

Запуск: ``pyinstaller --noconfirm --clean krmanfi_search.spec`` (результат — ``dist/KRmanfiSearch``).
python-docx и python-pptx читают шаблоны по путям вида ``<пакет>/parts/../templates``; такие
пути работают, только если папка ``parts`` физически есть на диске, поэтому в сборку
добавляются файлы-заглушки. В Windows создаются два exe: оконный ``KRmanfiSearch.exe`` и консольный
``KRmanfiSearch-console.exe`` (для диагностики и smoke_test.py).
"""

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH)
LAZY_MODULES = ["docx", "openpyxl", "pptx", "pymupdf", "pytesseract", "cv2", "numpy", "PIL"]
EXCLUDES = [
    "tkinter",
    "matplotlib",
    "scipy",
    "IPython",
    "pytest",
    "reportlab",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.Qt3DCore",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtDesigner",
    "PySide6.QtSql",
    "PySide6.QtTest",
    "PySide6.QtNetwork",
    "PySide6.QtSvg",
    "PySide6.QtOpenGL",
]

datas = [
    (str(ROOT / "resources"), "resources"),
]
for package in ("docx", "pptx", "openpyxl", "pymupdf"):
    datas += collect_data_files(package)
PLACEHOLDER = str(ROOT / "resources" / "placeholder.txt")
for folder in ("docx/parts", "pptx/oxml", "pptx/shapes"):
    datas.append((PLACEHOLDER, folder))
hiddenimports = collect_submodules("krmanfi_search") + LAZY_MODULES + collect_submodules("pymupdf")

icon = None
if sys.platform == "win32":
    icon = str(ROOT / "resources" / "icons" / "app.ico")

analysis = Analysis(
    [str(ROOT / "src" / "krmanfi_search" / "__main__.py")],
    pathex=[str(ROOT / "src")],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=EXCLUDES,
)
pyz = PYZ(analysis.pure)
windowed = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="KRmanfiSearch",
    console=False,
    icon=icon,
)
executables = [windowed]
if sys.platform == "win32":
    executables.append(
        EXE(
            pyz,
            analysis.scripts,
            [],
            exclude_binaries=True,
            name="KRmanfiSearch-console",
            console=True,
            icon=icon,
        )
    )
collected = COLLECT(*executables, analysis.binaries, analysis.datas, name="KRmanfiSearch")
