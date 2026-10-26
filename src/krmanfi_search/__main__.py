"""Точка входа: ``python -m krmanfi_search [путь]``."""

from __future__ import annotations

import argparse
import json
import multiprocessing
import sys
from collections.abc import Sequence
from pathlib import Path


def build_parser():
    """Разбор аргументов командной строки."""
    parser = argparse.ArgumentParser(prog="krmanfi_search", description="KRmanfi Text Search")
    parser.add_argument("path", nargs="?", type=Path, help="папка или архив для поиска")
    parser.add_argument(
        "--selftest",
        nargs=2,
        metavar=("ПУТЬ", "ТЕКСТ"),
        help="служебная проверка без окна: выводит JSON с результатами (для smoke_test.py)",
    )
    parser.add_argument("--regex", action="store_true", help="для --selftest: режим regex")
    parser.add_argument("--no-ocr", action="store_true", help="для --selftest: без OCR")
    return parser


def selftest(path: str, text: str, regex: bool, ocr: bool):
    """Выполнить поиск без окна и напечатать результат в JSON.

    Returns:
        Код завершения: 0 — поиск выполнен, 2 — запрос отклонён.
    """
    from krmanfi_search.container import Container
    from krmanfi_search.domain import SearchMode, SearchQuery, SearchStats
    from krmanfi_search.shared.exceptions import SearchError
    from krmanfi_search.shared.logging import configure_logging

    configure_logging("WARNING", to_file=False)
    container = Container.build()
    stats = SearchStats()
    try:
        query = SearchQuery(
            text=text,
            root=Path(path),
            mode=SearchMode.REGEX if regex else SearchMode.SUBSTRING,
            ocr_scanned_pdfs=ocr,
        )
        hits = list(container.search_text(query, stats=stats))
    except (SearchError, ValueError) as exc:
        sys.stdout.write(json.dumps({"error": str(exc)}, ensure_ascii=False) + "\n")
        return 2
    report = {
        "hits": [
            {"path": h.display_path, "location": h.location, "fragment": h.fragment} for h in hits
        ],
        "files_total": stats.files_total,
        "without_text": stats.without_text,
        "errors": [{"path": p, "reason": r} for p, r in stats.errors],
        "skipped": stats.skipped,
        "ocr_available": stats.ocr_available,
    }
    sys.stdout.write(json.dumps(report, ensure_ascii=False) + "\n")
    return 0


def main(argv: Sequence[str] | None = None):
    """Запустить окно или служебную проверку."""
    multiprocessing.freeze_support()
    multiprocessing.set_start_method("spawn", force=True)
    args = build_parser().parse_args(argv)
    if args.selftest:
        return selftest(args.selftest[0], args.selftest[1], args.regex, not args.no_ocr)
    from krmanfi_search.presentation.app import run

    return run(sys.argv[:1], args.path)


if __name__ == "__main__":
    sys.exit(main())
