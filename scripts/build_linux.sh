#!/usr/bin/env bash
# Сборка «Поиск по документам» для Linux: только uv. Результат: dist/KRmanfi-Search-linux-x64.tar.gz
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

# setup_linux.sh ничего не ставит сам: проверяет Tesseract и библиотеки Qt и печатает команду apt.
if ! sh ./scripts/setup_linux.sh; then
    echo
    read -r -p "Продолжить сборку без этого? [y/N] " answer
    case "$answer" in
        y | Y | д | Д) ;;
        *) echo "Остановлено. Выполните команду apt выше и запустите скрипт снова."; exit 1 ;;
    esac
fi

echo
echo "Подготовка окружения и сборка. Первый запуск скачивает Python и библиотеки."
uv run --extra dev python scripts/build.py

echo
echo "Готово. Архив лежит в папке dist. Запуск: dist/KRmanfi-Search/KRmanfiSearch"
