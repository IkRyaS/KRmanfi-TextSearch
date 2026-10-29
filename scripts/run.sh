#!/usr/bin/env sh
# Запуск из исходников: uv сам создаст окружение и поставит библиотеки.
cd "$(dirname "$0")" || exit 1
if ! command -v uv >/dev/null 2>&1; then
    echo "Не найден uv: curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
    exit 1
fi
exec uv run krmanfi-search "$@"
