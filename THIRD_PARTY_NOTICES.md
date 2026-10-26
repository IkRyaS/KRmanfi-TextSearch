# Лицензии сторонних компонентов

KRmanfi Text Search распространяется по лицензии **GNU AGPL-3.0-or-later** (файл `LICENSE`).
Причина — библиотека PyMuPDF: она доступна по AGPL-3.0 либо по коммерческой лицензии Artifex,
поэтому программа, которая её использует, распространяется вместе с открытыми исходниками.
Исходный код лежит в архиве `KRmanfi-TextSearch-source.zip`.

| Компонент | Версия | Лицензия | Где используется |
|---|---|---|---|
| [PyMuPDF](https://pymupdf.readthedocs.io/) | 1.28.2 | **AGPL-3.0** или коммерческая (Artifex) | чтение PDF, отрисовка страниц |
| [PySide6 / Qt for Python](https://doc.qt.io/qtforpython-6/) | 6.11.2 | LGPL-3.0 (или GPL-2.0/3.0) | интерфейс; библиотеки Qt поставляются как отдельные файлы |
| [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) | 5.x | Apache-2.0 | распознавание сканов (встроен в сборки) |
| [tessdata_fast](https://github.com/tesseract-ocr/tessdata_fast) | — | Apache-2.0 | языковые данные `rus`, `eng`, `osd` |
| [pytesseract](https://github.com/madmaze/pytesseract) | 0.3.13 | Apache-2.0 | вызов Tesseract из Python |
| [OpenCV (headless)](https://opencv.org/) | 4.14.0.94 | Apache-2.0 | предобработка изображений для OCR |
| [NumPy](https://numpy.org/) | 2.5.3 | BSD-3-Clause и др. | массивы изображений |
| [Pillow](https://python-pillow.org/) | 12.3.0 | MIT-CMU (HPND) | работа с изображениями |
| [Pydantic](https://docs.pydantic.dev/) | 2.13.5 | MIT | модели предметной области |
| [structlog](https://www.structlog.org/) | 26.1.0 | MIT или Apache-2.0 | журнал |
| [platformdirs](https://github.com/tox-dev/platformdirs) | 4.12.3 | MIT | пользовательские папки |
| [python-docx](https://github.com/python-openxml/python-docx) | 1.2.0 | MIT | чтение DOCX |
| [openpyxl](https://openpyxl.readthedocs.io/) | 3.1.5 | MIT | чтение XLSX |
| [python-pptx](https://github.com/scanny/python-pptx) | 1.0.2 | MIT | чтение PPTX |
| [PyInstaller](https://pyinstaller.org/) | 6.22.3 | GPL-2.0-or-later с исключением для сборки любых программ | только сборка; загрузчик входит в готовые архивы |
| [DejaVu Sans](https://dejavu-fonts.github.io/) | — | Bitstream Vera / свободная | шрифт, использованный при создании демо-файлов (`scripts/make_demo.py`) |

Python-библиотеки в готовых сборках лежат отдельными файлами в папке `_internal`, их лицензии
находятся рядом с пакетами (`*.dist-info`). Установочный пакет Tesseract для Windows
(UB-Mannheim) распространяется по Apache-2.0; в `vendor/tesseract` копируются его программа,
библиотеки и языковые данные без изменений.

Демо-файлы в папке `demo` синтетические, созданы скриптом `scripts/make_demo.py` и не содержат
личных данных.
