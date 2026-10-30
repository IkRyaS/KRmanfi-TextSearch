#!/usr/bin/env bash
# Сборка для Linux: только uv. Результат: dist/KRmanfi-Search-linux-x64.tar.gz
# Собирайте на Ubuntu 22.04 или новее: готовый файл работает на системах с такой же или более новой glibc.
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONUTF8=1

echo "============================================================"
echo "  Сборка «Поиск по документам» для Linux (только uv)"
echo "============================================================"

if ! command -v uv >/dev/null 2>&1; then
    echo
    echo "[!] Не найден uv. Установите его и запустите скрипт снова:"
    echo "      curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

if ! sh ./scripts/setup_linux.sh; then
    echo
    echo "[!] Для сборки это не помеха, но для запуска программы выполните команду apt выше."
fi

echo
echo "Подготовка окружения и сборка. Первый запуск скачивает Python и библиотеки."
uv run --python 3.13 --extra dev python scripts/build.py

echo
echo "Готово. Архив: dist/KRmanfi-Search-linux-x64.tar.gz"
echo "Запуск без распаковки: dist/KRmanfi-Search/KRmanfiSearch"
