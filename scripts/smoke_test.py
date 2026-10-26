r"""Проверка приложения без окна: исходники или собранный бинарник.

Примеры::

    python scripts/smoke_test.py
    python scripts/smoke_test.py --exe dist/KRmanfi-TextSearch/KRmanfiSearch --require-ocr
    python scripts/smoke_test.py --exe dist\\KRmanfi-TextSearch\\KRmanfiSearch-console.exe

Проверяет: запуск окна (offscreen), поиск в TXT, DOCX, PDF, ZIP (в том числе вложенном),
сканы через OCR, неверный regex, битый ZIP, выход за папку, зашифрованный PDF.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PHRASE = "квартальный отчёт"
STARTUP_SECONDS = 6
RUN_TIMEOUT = 600
results = []


def check(name: str, ok: bool, detail: str = ""):
    """Записать и напечатать результат проверки."""
    results.append(ok)
    print(f"[{'OK' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail and not ok else ""))


def command(exe: Path | None):
    """Команда запуска: бинарник или ``python -m krmanfi_search`` из исходников."""
    if exe is not None:
        return [str(exe)]
    return [sys.executable, "-m", "krmanfi_search"]


def environment(exe: Path | None):
    """Окружение процесса; для исходников добавляется ``src`` в путь импорта."""
    env = dict(os.environ)
    env["KRMANFI_SEARCH_DATA_DIR"] = tempfile.mkdtemp(prefix="krmanfi-smoke-data-")
    if exe is None:
        env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    return env


def selftest(exe: Path | None, path: Path, text: str, *flags: str):
    """Выполнить ``--selftest`` и вернуть ``(код, словарь JSON)``."""
    proc = subprocess.run(
        [*command(exe), "--selftest", str(path), text, *flags],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=RUN_TIMEOUT,
        env=environment(exe),
        check=False,
    )
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("{")]
    return proc.returncode, json.loads(lines[-1]) if lines else {}


def names(report: dict):
    """Короткие имена файлов с совпадениями."""
    return {h["path"].split("!/")[-1].replace("\\", "/").rsplit("/", 1)[-1] for h in report["hits"]}


def startup(exe: Path | None):
    """Окно запускается и не падает в течение нескольких секунд."""
    env = environment(exe)
    env["QT_QPA_PLATFORM"] = "offscreen"
    proc = subprocess.Popen(
        command(exe),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    time.sleep(STARTUP_SECONDS)
    alive = proc.poll() is None
    proc.terminate()
    try:
        _, err = proc.communicate(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
        _, err = proc.communicate()
    check("окно запускается (offscreen)", alive and "Traceback" not in err, err[-400:])


def main(argv: list[str] | None = None):
    """Выполнить все проверки."""
    parser = argparse.ArgumentParser(description="Smoke-тест KRmanfi Text Search")
    parser.add_argument("--exe", type=Path, help="собранный бинарник (по умолчанию — исходники)")
    parser.add_argument("--demo", type=Path, default=ROOT / "demo")
    parser.add_argument("--require-ocr", action="store_true", help="считать отсутствие OCR ошибкой")
    args = parser.parse_args(argv)
    exe, demo = args.exe, args.demo
    startup(exe)
    docs = demo / "документы"
    code, report = selftest(exe, docs, PHRASE, "--no-ocr")
    found = names(report) if code == 0 else set()
    for needed in (
        "07_заметки.txt",
        "09_данные.csv",
        "04_протокол.docx",
        "01_текстовый_слой.pdf",
        "05_платежи.xlsx",
        "06_презентация.pptx",
    ):
        check(f"найдено в {needed}", needed in found)
    code, report = selftest(exe, demo / "архивы", PHRASE)
    inside = {h["path"].count("!/") for h in report.get("hits", [])}
    expected = {1, 2} if report.get("ocr_available") else {1}
    check("найдено в ZIP, включая вложенный", expected <= inside, str(inside))
    code, report = selftest(exe, demo / "сканы", PHRASE)
    if report.get("ocr_available"):
        scans = names(report)
        check("сканы находятся через OCR", {"02_скан_книги.pdf", "19_повёрнутый_скан.pdf"} <= scans)
    else:
        check("OCR доступен", not args.require_ocr, "Tesseract не найден")
    code, report = selftest(exe, docs, "(", "--regex", "--no-ocr")
    check("неверный regex не роняет приложение", code == 2 and "Некорректное" in report["error"])
    code, report = selftest(exe, demo / "для_проверки_ошибок", PHRASE, "--no-ocr")
    reasons = " ".join(e["reason"] for e in report.get("errors", []))
    check(
        "битый ZIP, выход за папку и зашифрованный PDF — в ошибках",
        len(report.get("errors", [])) == 3,
        reasons,
    )
    check("совпадения из безопасных записей находятся", "нормальный.txt" in names(report))
    code, report = selftest(exe, demo / "нет_такой_папки", PHRASE)
    check(
        "несуществующая папка — понятная ошибка", code == 2 and "не существует" in report["error"]
    )
    failed = results.count(False)
    print(f"\nПроверок: {len(results)}, провалено: {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
