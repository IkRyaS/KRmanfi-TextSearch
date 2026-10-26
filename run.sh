#!/usr/bin/env sh
# Запуск KRmanfi Text Search: собранная версия или исходники.
cd "$(dirname "$0")" || exit 1

check_qt_libraries() {
    [ -n "${WAYLAND_DISPLAY:-}" ] && return 0
    ldconfig_bin=$(command -v ldconfig || echo /sbin/ldconfig)
    if ! "$ldconfig_bin" -p 2>/dev/null | grep -q "libxcb-cursor.so.0"; then
        echo "Внимание: нет библиотеки libxcb-cursor0, окно может не открыться." >&2
        echo "Выполните ./setup_linux.sh — он напечатает нужную команду apt." >&2
    fi
}

if [ -x ./KRmanfiSearch ]; then
    check_qt_libraries
    exec ./KRmanfiSearch "$@"
fi
if [ -x ./.venv/bin/python ]; then
    check_qt_libraries
    PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}" exec ./.venv/bin/python -m krmanfi_search "$@"
fi
echo "Не найдены ни KRmanfiSearch, ни .venv. Создайте окружение (см. README.md):" >&2
echo "  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
exit 1
