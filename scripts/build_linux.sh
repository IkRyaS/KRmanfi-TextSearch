#!/usr/bin/env bash
# Сборка Linux-версии: окружение → PyInstaller → встроенный Tesseract → архив → проверки.
# Собирайте на Ubuntu 22.04 (или в контейнере ubuntu:22.04): бинарник работает на системах
# с такой же или более новой glibc. Нужны: python 3.13 (или uv), tesseract-ocr, tesseract-ocr-rus.
set -euo pipefail
cd "$(dirname "$0")/.."

if command -v uv >/dev/null 2>&1; then
    uv sync --extra dev --frozen
    PY=.venv/bin/python
else
    python3.13 -m venv .venv
    .venv/bin/pip install -r requirements.txt ".[dev]"
    PY=.venv/bin/python
fi

$PY -m ruff check src tests scripts
$PY -m pytest
rm -rf build dist
$PY -m PyInstaller --noconfirm --clean krmanfi_search.spec
$PY scripts/bundle_tesseract.py dist/KRmanfiSearch
$PY scripts/package.py
$PY scripts/smoke_test.py --exe dist/KRmanfi-TextSearch/KRmanfiSearch --require-ocr
$PY scripts/make_source_zip.py
$PY scripts/check_release.py dist/KRmanfi-TextSearch-linux-x64.tar.gz dist/KRmanfi-TextSearch-source.zip
cat dist/SHA256SUMS.txt
