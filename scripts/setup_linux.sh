#!/usr/bin/env sh
# Проверка Linux-окружения для KRmanfi Text Search. Ничего не устанавливает сама:
# только сообщает, чего не хватает, и печатает готовую команду для apt.
here=$(dirname "$0")
[ -f "$here/../pyproject.toml" ] && here="$here/.."
cd "$here" || exit 1
missing=""
note() { printf '%s\n' "$1"; }

if [ -x vendor/tesseract/tesseract ]; then
    note "[ok] Tesseract встроен в сборку (vendor/tesseract)"
elif command -v tesseract >/dev/null 2>&1; then
    note "[ok] Tesseract найден: $(command -v tesseract)"
    langs=$(tesseract --list-langs 2>/dev/null)
    echo "$langs" | grep -qx rus || { note "[!] нет языка rus"; missing="$missing tesseract-ocr-rus"; }
    echo "$langs" | grep -qx eng || { note "[!] нет языка eng"; missing="$missing tesseract-ocr-eng"; }
else
    note "[!] Tesseract не найден: сканы PDF не будут распознаваться"
    missing="$missing tesseract-ocr tesseract-ocr-rus tesseract-ocr-eng"
fi

need_lib() {
    ldconfig -p 2>/dev/null | grep -q "$1" || { note "[!] нет библиотеки $1"; missing="$missing $2"; }
}
need_lib libxcb-cursor.so.0 libxcb-cursor0
need_lib libxkbcommon-x11.so.0 libxkbcommon-x11-0
need_lib libxcb-icccm.so.4 libxcb-icccm4
need_lib libxcb-keysyms.so.1 libxcb-keysyms1
need_lib libxcb-shape.so.0 libxcb-shape0
need_lib libGL.so.1 libgl1
need_lib libEGL.so.1 libegl1
need_lib libfontconfig.so.1 libfontconfig1

if [ -z "$missing" ]; then
    note "Всё необходимое установлено. Запуск: scripts/run.sh"
    exit 0
fi
note ""
note "Установите недостающее командой:"
note "  sudo apt install$missing"
exit 1
